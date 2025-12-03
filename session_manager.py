import threading
import time
import re
from datetime import datetime
from threading import Lock
from metadata_manager import MetadataManager

class SessionManager:
    def __init__(self):
        self.playlist = [] 
        self.known_songs_cache = {} 
        self.meta_bot = MetadataManager()
        self._next_id = 1 
        self.lock = Lock()
        print("📝 Session Manager Inizializzato (Async + Retry)")

    def _normalize_string(self, text):
        """Pulisce le stringhe per il confronto duplicati"""
        if not text: return ""
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        clean = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live)\b.*", "", clean)
        return clean.strip().lower()

    def _is_karaoke_or_cover(self, title, artist):
        """Identifica brani palesemente fake/karaoke"""
        keywords = ['karaoke', 'backing version', 'made popular by', 'tribute to', 'instrumental', 'cover', 'ameritz', 'party hit']
        full_text = (title + " " + artist).lower()
        return any(k in full_text for k in keywords)

    def add_song(self, song_data, target_artist=None):
        """
        Aggiunge un brano alla lista.
        Restituisce SUBITO il controllo, avviando l'arricchimento dati in background.
        """
        # 1. Acquisiamo il lucchetto per leggere/scrivere la lista in sicurezza
        with self.lock:
            if song_data.get('status') != 'success':
                return {"added": False, "reason": "No match"}
            
            title = song_data['title']
            artist = song_data['artist']
            
            clean_new_title = self._normalize_string(title)
            clean_new_artist = self._normalize_string(artist)

            # --- LOGICA DUPLICATI (Invariata) ---
            for existing_song in self.playlist[-15:]:
                clean_ex_title = self._normalize_string(existing_song['title'])
                clean_ex_artist = self._normalize_string(existing_song['artist'])

                # CASO 1: Titoli identici
                if clean_new_title == clean_ex_title and len(clean_new_title) > 3:
                    print(f"🔄 Duplicato per Titolo Identico: '{clean_new_title}' (Artista ignorato: {artist})")
                    return {"added": False, "reason": "Duplicate (Title Match)", "song": existing_song}
                
                # CASO 2: Match Esatto
                if clean_new_title == clean_ex_title and clean_new_artist == clean_ex_artist:
                     return {"added": False, "reason": "Duplicate (Exact match)", "song": existing_song}

            # --- PREPARAZIONE DATI (Modificata per Async) ---
            track_key = f"{title} - {artist}".lower()
            
            # Controlliamo se lo abbiamo già in cache (risposta istantanea)
            cached_entry = self.known_songs_cache.get(track_key)
            
            if cached_entry:
                print(f"⚡ Cache Hit! {title}")
                composer_name = cached_entry['composer']
                isrc = cached_entry.get('isrc')
                upc = cached_entry.get('upc')
                status_enrichment = "Done"
            else:
                # Se è nuovo, mettiamo un segnaposto e attiviamo il thread
                composer_name = "⏳ Ricerca..."
                isrc = song_data.get('isrc')
                upc = song_data.get('upc')
                status_enrichment = "Pending"

            new_entry = {
                "id": self._next_id, 
                "title": title,
                "artist": artist, 
                "composer": composer_name,     
                "album": song_data.get('album', 'Sconosciuto'),
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "duration_ms": song_data.get('duration_ms', 0),
                "score": song_data.get('score', 0),
                "type": song_data.get('type', 'Original'),
                "isrc": isrc, 
                "upc": upc,
                # Salviamo i dati grezzi per il thread di background (nascosti all'utente)
                "_raw_isrc": isrc,
                "_raw_upc": upc
            }

            self.playlist.append(new_entry) 
            self._next_id += 1

            # --- LANCIO THREAD DI BACKGROUND ---
            if status_enrichment == "Pending":
                threading.Thread(
                    target=self._background_enrichment,
                    args=(new_entry, target_artist),
                    daemon=True # Il thread muore se si chiude il programma
                ).start()

            print(f"✅ Aggiunto (Async): {title}")
            return {"added": True, "song": new_entry}

    def _background_enrichment(self, entry, target_artist):
        """
        Funzione eseguita in un thread separato.
        Tenta di recuperare il compositore con logica Retry & Backoff.
        """
        attempts = 0
        max_attempts = 3
        found_composer = "Sconosciuto"
        success = False

        print(f"🧵 [Thread] Inizio ricerca per: {entry['title']}")

        while attempts < max_attempts:
            try:
                # Chiamata a MusicBrainz (potrebbe metterci tempo)
                found_composer = self.meta_bot.find_composer(
                    title=entry['title'], 
                    detected_artist=entry['artist'],
                    isrc=entry.get('_raw_isrc'),
                    upc=entry.get('_raw_upc'),
                    setlist_artist=target_artist
                )
                
                success = True
                break # Usciamo dal ciclo while se ha funzionato

            except Exception as e:
                attempts += 1
                print(f"⚠️ [Thread] Errore MusicBrainz ({attempts}/{max_attempts}): {e}")
                
                if attempts < max_attempts:
                    # Backoff esponenziale: aspetta 2s, poi 4s...
                    wait_time = 2 ** attempts
                    time.sleep(wait_time)
                else:
                    print(f"❌ [Thread] Abbandono ricerca per: {entry['title']}")
                    found_composer = "Errore Conn."

        # --- FASE DI AGGIORNAMENTO SICURO ---
        # Dobbiamo riprendere il Lock per modificare la lista condivisa
        with self.lock:
            # Cerchiamo l'oggetto originale nella lista tramite ID
            # (Non usiamo 'entry' direttamente perché la lista potrebbe essere cambiata)
            target_song = next((s for s in self.playlist if s['id'] == entry['id']), None)
            
            if target_song:
                target_song['composer'] = found_composer
                print(f"📝 [Thread] Compositore aggiornato: {found_composer}")
                
                # Aggiorniamo la cache solo se abbiamo un dato valido
                if success and found_composer not in ["Sconosciuto", "Errore Conn."]:
                    track_key = f"{target_song['title']} - {target_song['artist']}".lower()
                    self.known_songs_cache[track_key] = target_song.copy()

    def get_playlist(self):
        # Restituisce la playlist (il frontend vedrà "⏳ Ricerca..." finché il thread non finisce)
        return self.playlist

    def delete_song(self, song_id):
        with self.lock:
            try:
                song_id = int(song_id)
                self.playlist = [s for s in self.playlist if s['id'] != song_id]
                return True
            except ValueError:
                return False