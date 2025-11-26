import re
from datetime import datetime
from threading import Lock  # <--- 1. Importiamo il Lock
from metadata_manager import MetadataManager

class SessionManager:
    def __init__(self):
        self.playlist = [] 
        self.known_songs_cache = {} 
        self.meta_bot = MetadataManager()
        self._next_id = 1 
        self.lock = Lock()  # <--- 2. Creiamo il lucchetto
        print("📝 Session Manager Inizializzato (Thread-Safe)")

    def _normalize_string(self, text):
        if not text: return ""
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        clean = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live)\b.*", "", clean)
        return clean.strip().lower()

    def _is_karaoke_or_cover(self, title, artist):
        keywords = ['karaoke', 'backing version', 'made popular by', 'tribute to', 'instrumental', 'cover', 'ameritz', 'party hit']
        full_text = (title + " " + artist).lower()
        return any(k in full_text for k in keywords)

    def add_song(self, song_data, target_artist=None):
        # 3. Blocco l'accesso: solo un thread alla volta può eseguire questo codice
        with self.lock:
            if song_data.get('status') != 'success':
                return {"added": False, "reason": "No match"}
            
            title = song_data['title']
            artist = song_data['artist']
            track_key = f"{title} - {artist}".lower()

            clean_new_title = self._normalize_string(title)
            clean_new_artist = self._normalize_string(artist)
            new_is_junk = self._is_karaoke_or_cover(title, artist)

            # --- LOGICA DUPLICATI ---
            # Ora siamo sicuri che nessun altro sta scrivendo nella playlist mentre controlliamo
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

            # --- RECUPERO DATI ---
            # Se siamo qui, il brano non è in lista.
            # Poiché siamo dentro il "with self.lock", gli altri thread devono aspettare
            # che finiamo di interrogare MusicBrainz prima di poter controllare la lista.
            
            if track_key in self.known_songs_cache:
                print(f"⚡ Cache Hit! {title}")
                cached_entry = self.known_songs_cache[track_key]
                composer_name = cached_entry['composer']
                isrc = cached_entry['isrc']
                upc = cached_entry['upc']
            else:
                print("🔍 Brano nuovo. Interrogo MusicBrainz...")
                isrc = song_data.get('isrc')
                upc = song_data.get('upc')
                composer_name = self.meta_bot.find_composer(
                    title=title, 
                    detected_artist=artist,
                    isrc=isrc,
                    upc=upc,
                    setlist_artist=target_artist
                )

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
                "upc": upc
            }

            self.known_songs_cache[track_key] = new_entry
            self.playlist.append(new_entry) # Qui avviene il salvataggio effettivo
            self._next_id += 1

            print(f"✅ Aggiunto: {title}")
            return {"added": True, "song": new_entry}

    def get_playlist(self):
        return self.playlist

    def delete_song(self, song_id):
        with self.lock: # Proteggiamo anche la cancellazione
            try:
                song_id = int(song_id)
                self.playlist = [s for s in self.playlist if s['id'] != song_id]
                return True
            except ValueError:
                return False