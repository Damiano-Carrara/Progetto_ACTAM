import threading
import time
import re
from datetime import datetime
from threading import Lock
from metadata_manager import MetadataManager
from difflib import SequenceMatcher 

class SessionManager:
    def __init__(self):
        self.playlist = [] 
        self.known_songs_cache = {} 
        self.meta_bot = MetadataManager()
        self._next_id = 1 
        self.lock = Lock()
        print("📝 Session Manager Inizializzato (Strict Dedup)")

    def _normalize_string(self, text):
        """Pulisce le stringhe per il confronto duplicati"""
        if not text: return ""
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        clean = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live)\b.*", "", clean)
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)
        return clean.strip().lower()

    def _are_songs_equivalent(self, new_s, existing_s):
        """
        Controlla duplicati con SOGLIE INNALZATE (Fix: I Belong to You vs Più Bella Cosa).
        """
        # 1. CONTROLLO ARTISTA (Rigido)
        art_new = self._normalize_string(new_s['artist'])
        art_ex = self._normalize_string(existing_s['artist'])
        
        if art_new != art_ex and art_new not in art_ex and art_ex not in art_new:
            return False

        # 2. CALCOLO SIMILARITÀ TITOLO
        tit_new = self._normalize_string(new_s['title'])
        tit_ex = self._normalize_string(existing_s['title'])
        similarity = SequenceMatcher(None, tit_new, tit_ex).ratio()

        # CASO A: Titoli Praticamente Uguali -> Duplicato sicuro
        if similarity > 0.82: 
            return True

        # 3. CONTROLLO DURATA (Con validazione rigorosa)
        try:
            dur_new = int(new_s.get('duration_ms', 0) or 0)
            dur_ex = int(existing_s.get('duration_ms', 0) or 0)
        except:
            dur_new, dur_ex = 0, 0

        MIN_VALID_DURATION = 30000 

        if dur_new > MIN_VALID_DURATION and dur_ex > MIN_VALID_DURATION:
            diff = abs(dur_new - dur_ex)
            
            # --- LOGICA TOLLERANZA (SOGLIA ALZATA A 0.60) ---
            # Abbiamo eliminato la fascia "media" (0.45-0.60) che causava falsi positivi.
            
            if similarity > 0.60:
                # Simili / Traduzioni (es. Favola/Fabula ~0.66) -> Tolleranza ampia
                tolerance = 12000 
            else:
                # Diversi (es. I belong to you/Più bella cosa ~0.50) -> Tolleranza ZERO.
                # Devono essere identici al decimo di secondo (stesso file) per essere uniti.
                tolerance = 100 
            
            if diff < tolerance:
                print(f"🔄 Duplicato (Livello {similarity:.2f}): '{tit_new}' == '{tit_ex}' (Diff: {diff}ms)")
                return True
        
        return False
    
    def add_song(self, song_data, target_artist=None):
        with self.lock:
            if song_data.get('status') != 'success':
                return {"added": False, "reason": "No match"}
            
            title = song_data['title']
            artist = song_data['artist']
            
            candidate_song = {
                'title': title,
                'artist': artist,
                'duration_ms': song_data.get('duration_ms', 0)
            }

            # Controlliamo gli ultimi 15 brani
            for existing_song in self.playlist[-15:]:
                if self._are_songs_equivalent(candidate_song, existing_song):
                    print(f"♻️ Duplicato Scartato: {title}")
                    return {"added": False, "reason": "Duplicate (Smart Match)", "song": existing_song}

            track_key = f"{title} - {artist}".lower()
            cached_entry = self.known_songs_cache.get(track_key)
            
            if cached_entry:
                print(f"⚡ Cache Hit! {title}")
                composer_name = cached_entry['composer']
                isrc = cached_entry.get('isrc')
                upc = cached_entry.get('upc')
                status_enrichment = "Done"
            else:
                composer_name = "⏳ Ricerca..."
                isrc = song_data.get('isrc')
                upc = song_data.get('upc')
                status_enrichment = "Pending"

            raw_meta_package = {
                "spotify": song_data.get('external_metadata', {}).get('spotify', {}),
                "contributors": song_data.get('contributors', {}) # <--- AGGIUNTO QUI
            }

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
                "_raw_isrc": isrc,
                "_raw_upc": upc,
                "_raw_meta": raw_meta_package # <--- NUOVO CAMPO FONDAMENTALE
            }

            self.playlist.append(new_entry) 
            self._next_id += 1

            if status_enrichment == "Pending":
                threading.Thread(
                    target=self._background_enrichment,
                    args=(new_entry, target_artist),
                    daemon=True
                ).start()

            print(f"✅ Aggiunto (Async): {title}")
            return {"added": True, "song": new_entry}

    def _background_enrichment(self, entry, target_artist):
        attempts = 0
        max_attempts = 3
        found_composer = "Sconosciuto"
        success = False

        print(f"🧵 [Thread] Inizio ricerca per: {entry['title']}")

        while attempts < max_attempts:
            try:
                found_composer = self.meta_bot.find_composer(
                    title=entry['title'], 
                    detected_artist=entry['artist'],
                    isrc=entry.get('_raw_isrc'),
                    upc=entry.get('_raw_upc'),
                    setlist_artist=target_artist,
                    raw_acr_meta=entry.get('_raw_meta') # <--- PASSIAMO I DATI GREZZI
                )
                success = True
                break 

            except Exception as e:
                attempts += 1
                if attempts < max_attempts:
                    time.sleep(2 ** attempts)
                else:
                    found_composer = "Errore Conn."

        with self.lock:
            target_song = next((s for s in self.playlist if s['id'] == entry['id']), None)
            
            if target_song:
                target_song['composer'] = found_composer
                print(f"📝 [Thread] Compositore aggiornato: {found_composer}")
                
                if success and found_composer not in ["Sconosciuto", "Errore Conn."]:
                    track_key = f"{target_song['title']} - {target_song['artist']}".lower()
                    self.known_songs_cache[track_key] = target_song.copy()

    def get_playlist(self):
        return self.playlist

    def delete_song(self, song_id):
        with self.lock:
            try:
                song_id = int(song_id)
                self.playlist = [s for s in self.playlist if s['id'] != song_id]
                return True
            except ValueError:
                return False