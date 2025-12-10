import threading
import time
import re
import sqlite3 # <--- Il database nativo di Python
from datetime import datetime
from threading import Lock
from metadata_manager import MetadataManager
from difflib import SequenceMatcher 

class SessionManager:
    def __init__(self):
        self.db_path = "session_live.db"
        self.playlist = [] 
        self.known_songs_cache = {} 
        self.meta_bot = MetadataManager()
        self._next_id = 1 
        self.lock = Lock()
        
        # Inizializza il DB e ricarica sessioni precedenti
        self._init_db()
        self._load_session_from_db()
        
        print(f"📝 Session Manager Pronto (SQLite Persistente: {self.db_path})")

    # --- GESTIONE DATABASE ---
    def _init_db(self):
        """Crea la tabella se non esiste"""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS songs (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    artist TEXT,
                    composer TEXT,
                    album TEXT,
                    timestamp TEXT,
                    duration_ms INTEGER,
                    score INTEGER,
                    type TEXT,
                    isrc TEXT,
                    upc TEXT
                )
            ''')
            conn.commit()

    def _load_session_from_db(self):
        """Ricarica la sessione precedente in caso di crash/riavvio"""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row # Per accedere alle colonne per nome
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM songs ORDER BY id ASC')
            rows = cursor.fetchall()
            
            if rows:
                print(f"♻️ Ripristino sessione: trovati {len(rows)} brani nel database.")
                for row in rows:
                    song = dict(row)
                    self.playlist.append(song)
                    
                    # Ripopoliamo la cache e l'ID counter
                    track_key = f"{song['title']} - {song['artist']}".lower()
                    self.known_songs_cache[track_key] = song
                    if song['id'] >= self._next_id:
                        self._next_id = song['id'] + 1
            else:
                print("🆕 Nessuna sessione precedente trovata. Parto da zero.")

    def _save_song_to_db(self, song):
        """Salva un nuovo brano nel DB"""
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO songs (id, title, artist, composer, album, timestamp, duration_ms, score, type, isrc, upc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    song['id'], song['title'], song['artist'], song['composer'],
                    song['album'], song['timestamp'], song['duration_ms'],
                    song['score'], song['type'], song['isrc'], song['upc']
                ))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore salvataggio DB: {e}")

    def _update_composer_in_db(self, song_id, composer):
        """Aggiorna solo il compositore di un brano esistente"""
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE songs SET composer = ? WHERE id = ?', (composer, song_id))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore update DB: {e}")

    def _delete_from_db(self, song_id):
        """Rimuove un brano dal DB"""
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM songs WHERE id = ?', (song_id,))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore delete DB: {e}")

    # --- FINE GESTIONE DB ---

    def _normalize_string(self, text):
        if not text: return ""
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        clean = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live)\b.*", "", clean)
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)
        return clean.strip().lower()

    def _are_songs_equivalent(self, new_s, existing_s):
        # 1. CONTROLLO ARTISTA (Rigido)
        art_new = self._normalize_string(new_s['artist'])
        art_ex = self._normalize_string(existing_s['artist'])
        
        if art_new != art_ex and art_new not in art_ex and art_ex not in art_new:
            return False

        # 2. CALCOLO SIMILARITÀ TITOLO
        tit_new = self._normalize_string(new_s['title'])
        tit_ex = self._normalize_string(existing_s['title'])
        similarity = SequenceMatcher(None, tit_new, tit_ex).ratio()

        if similarity < 0.50: return False
        if similarity > 0.80: return True

        # 3. CONTROLLO DURATA (Zona Grigia)
        try:
            dur_new = int(new_s.get('duration_ms', 0) or 0)
            dur_ex = int(existing_s.get('duration_ms', 0) or 0)
        except:
            dur_new, dur_ex = 0, 0

        MIN_VALID_DURATION = 30000 
        if dur_new > MIN_VALID_DURATION and dur_ex > MIN_VALID_DURATION:
            diff = abs(dur_new - dur_ex)
            tolerance = 12000 
            if diff < tolerance:
                print(f"🔄 Duplicato (Sim: {similarity:.2f}): '{tit_new}' == '{tit_ex}' (Diff: {diff}ms)")
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
                "_raw_upc": upc
            }

            self.playlist.append(new_entry) 
            self._save_song_to_db(new_entry) # <--- SALVATAGGIO IMMEDIATO SU DISCO
            self._next_id += 1

            if status_enrichment == "Pending":
                threading.Thread(
                    target=self._background_enrichment,
                    args=(new_entry, target_artist),
                    daemon=True
                ).start()

            print(f"✅ Aggiunto (Async + Persistente): {title}")
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
                    setlist_artist=target_artist
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
            # Recuperiamo l'oggetto "vivo" dalla playlist
            target_song = next((s for s in self.playlist if s['id'] == entry['id']), None)
            
            if target_song:
                target_song['composer'] = found_composer
                
                # <--- AGGIORNAMENTO DB SU DISCO
                self._update_composer_in_db(target_song['id'], found_composer)
                print(f"📝 [Thread] Compositore aggiornato e salvato: {found_composer}")
                
                if success and found_composer not in ["Sconosciuto", "Errore Conn."]:
                    track_key = f"{target_song['title']} - {target_song['artist']}".lower()
                    self.known_songs_cache[track_key] = target_song.copy()

    def get_playlist(self):
        return self.playlist

    def clear_session(self):
        """
        RESET TOTALE: Cancella tutto dalla RAM e dal Database.
        Da usare quando l'utente preme 'Reset' per iniziare una nuova serata.
        """
        with self.lock:
            # 1. Pulisce la RAM
            self.playlist = []
            self.known_songs_cache = {}
            self._next_id = 1
            
            # 2. Pulisce il Database Fisico (Senza cancellare il file, solo il contenuto)
            try:
                with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM songs') # <--- TABULA RASA
                    conn.commit()
                print("🧹 Sessione resettata: Database e memoria puliti.")
                return True
            except Exception as e:
                print(f"❌ Errore reset DB: {e}")
                return False

    def delete_song(self, song_id):
        with self.lock:
            try:
                song_id = int(song_id)
                self.playlist = [s for s in self.playlist if s['id'] != song_id]
                self._delete_from_db(song_id) # <--- CANCELLAZIONE SU DISCO
                return True
            except ValueError:
                return False