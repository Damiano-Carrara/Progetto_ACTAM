import threading
import time
import re
import sqlite3
import unicodedata
from datetime import datetime
from threading import Lock
from metadata_manager import MetadataManager
from spotify_manager import SpotifyManager
from difflib import SequenceMatcher

class SessionManager:
    def __init__(self):
        self.db_path = "session_live.db"
        self.playlist = []
        self.known_songs_cache = {}
        
        # Inizializziamo i Bot
        self.meta_bot = MetadataManager()
        self.spotify_bot = SpotifyManager()
        
        self._next_id = 1
        self.lock = Lock()
        
        # Inizializza il DB e ricarica sessioni precedenti
        self._init_db()
        self._load_session_from_db()
        
        print(f"📝 Session Manager Inizializzato (Fix 'Ricerca...' su Original Composer)")

    # --- GESTIONE DATABASE ---
    def _init_db(self):
        """Crea la tabella se non esiste e aggiunge colonne mancanti (Auto-Migrazione)"""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            cursor = conn.cursor()
            # 1. Crea tabella base se non esiste
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
            
            # 2. Controllo/Migrazione Colonne mancanti
            cursor.execute("PRAGMA table_info(songs)")
            existing_columns = [info[1] for info in cursor.fetchall()]
            
            if 'cover' not in existing_columns:
                print("🔧 [DB] Aggiungo colonna mancante: 'cover'")
                cursor.execute("ALTER TABLE songs ADD COLUMN cover TEXT")

            # --- NUOVE COLONNE PER IL REPORTING AVANZATO ---
            if 'is_deleted' not in existing_columns:
                cursor.execute("ALTER TABLE songs ADD COLUMN is_deleted INTEGER DEFAULT 0")
            
            if 'is_manual' not in existing_columns:
                cursor.execute("ALTER TABLE songs ADD COLUMN is_manual INTEGER DEFAULT 0")

            if 'original_title' not in existing_columns:
                cursor.execute("ALTER TABLE songs ADD COLUMN original_title TEXT")

            if 'original_artist' not in existing_columns:
                cursor.execute("ALTER TABLE songs ADD COLUMN original_artist TEXT")

            if 'original_composer' not in existing_columns:
                cursor.execute("ALTER TABLE songs ADD COLUMN original_composer TEXT")
            
            conn.commit()

    def _load_session_from_db(self):
        """Ricarica la sessione precedente in caso di crash/riavvio"""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row 
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM songs ORDER BY id ASC')
            rows = cursor.fetchall()
            
            if rows:
                print(f"♻️ Ripristino sessione: trovati {len(rows)} brani nel database.")
                for row in rows:
                    song = dict(row)
                    song['_raw_meta'] = {} 
                    
                    # Convertiamo i flag integer in boolean
                    song['is_deleted'] = bool(song.get('is_deleted', 0))
                    song['manual'] = bool(song.get('is_manual', 0))

                    self.playlist.append(song)
                    
                    # Cache solo se non è cancellato
                    if not song['is_deleted']:
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
                    INSERT INTO songs (
                        id, title, artist, composer, album, timestamp, duration_ms, 
                        score, type, isrc, upc, cover, 
                        is_deleted, is_manual, original_title, original_artist, original_composer
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    song['id'], song['title'], song['artist'], song['composer'],
                    song['album'], song['timestamp'], song['duration_ms'],
                    song['score'], song['type'], song['isrc'], song['upc'],
                    song.get('cover'),
                    1 if song.get('is_deleted') else 0,
                    1 if song.get('manual') else 0,
                    song.get('original_title'),
                    song.get('original_artist'),
                    song.get('original_composer')
                ))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore salvataggio DB: {e}")

    def _update_composer_in_db(self, song_id, composer):
        """Aggiorna il compositore. Sovrascrive ANCHE l'originale se era un placeholder."""
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                
                # 1. Aggiorna il campo corrente (quello modificabile)
                cursor.execute('UPDATE songs SET composer = ? WHERE id = ?', (composer, song_id))
                
                # 2. Aggiorna il campo originale (log tecnico). 
                # FIX: Lo sovrascriviamo SEMPRE quando arriva dal bot di arricchimento,
                # perché il bot rappresenta la "verità tecnica" rispetto al placeholder "Ricerca...".
                cursor.execute('''
                    UPDATE songs 
                    SET original_composer = ? 
                    WHERE id = ?
                ''', (composer, song_id))
                
                conn.commit()
        except Exception as e:
            print(f"❌ Errore update DB: {e}")

    def _update_cover_in_db(self, song_id, cover_url):
        """Aggiorna solo la cover di un brano esistente"""
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE songs SET cover = ? WHERE id = ?', (cover_url, song_id))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore update Cover DB: {e}")

    def _delete_from_db(self, song_id):
        # Soft Delete
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE songs SET is_deleted = 1 WHERE id = ?', (song_id,))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore soft-delete DB: {e}")

    # --- LOGICA MATCHING ---
    def _normalize_string(self, text):
        if not text: return ""
        text = re.sub(r"[\(\[].*?[\)\]]", "", text)
        text = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live)\b.*", "", text)
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", text)
        return clean.strip().lower()

    def _are_songs_equivalent(self, new_s, existing_s):
        art_new = self._normalize_string(new_s['artist'])
        art_ex = self._normalize_string(existing_s['artist'])
        
        if art_new != art_ex and art_new not in art_ex and art_ex not in art_new:
            return False

        tit_new = self._normalize_string(new_s['title'])
        tit_ex = self._normalize_string(existing_s['title'])
        similarity = SequenceMatcher(None, tit_new, tit_ex).ratio()

        if similarity < 0.40: return False
        if similarity > 0.60: return True

        try:
            dur_new = int(new_s.get('duration_ms', 0) or 0)
            dur_ex = int(existing_s.get('duration_ms', 0) or 0)
        except:
            dur_new, dur_ex = 0, 0

        MIN_VALID_DURATION = 30000 
        if dur_new > MIN_VALID_DURATION and dur_ex > MIN_VALID_DURATION:
            diff = abs(dur_new - dur_ex)
            if diff < 200: 
                return True
        
        return False

    # --- ADD SONG ---
    def add_song(self, song_data, target_artist=None):
        with self.lock:
            # Rileviamo se è un inserimento manuale
            is_manual = song_data.get('manual', False)

            if not is_manual and song_data.get('status') != 'success':
                return {"added": False, "reason": "No match"}
            
            title = song_data['title']
            artist = song_data['artist']
            
            candidate_song = {
                'title': title,
                'artist': artist,
                'duration_ms': song_data.get('duration_ms', 0)
            }

            # Check duplicati (solo tra i NON cancellati)
            active_songs = [s for s in self.playlist if not s.get('is_deleted')]
            for existing_song in active_songs[-15:]:
                if self._are_songs_equivalent(candidate_song, existing_song):
                    print(f"♻️ Duplicato Scartato: {title}")
                    return {"added": False, "reason": "Duplicate", "song": existing_song}

            track_key = f"{title} - {artist}".lower()
            cached_entry = self.known_songs_cache.get(track_key)
            
            # Se è manuale, non cerchiamo in cache
            if not is_manual and cached_entry:
                print(f"⚡ Cache Hit! {title}")
                composer_name = cached_entry['composer']
                isrc = cached_entry.get('isrc')
                upc = cached_entry.get('upc')
                cover_url = cached_entry.get('cover') or song_data.get('cover')
                status_enrichment = "Done"
            else:
                composer_name = "⏳ Ricerca..." if not is_manual else ""
                isrc = song_data.get('isrc')
                upc = song_data.get('upc')
                cover_url = song_data.get('cover')
                status_enrichment = "Pending" if not is_manual else "Done"

            raw_meta_package = {
                "spotify": song_data.get('external_metadata', {}).get('spotify', {}),
                "contributors": song_data.get('contributors', {})
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
                "type": song_data.get('type', 'Manual' if is_manual else 'Original'),
                "isrc": isrc, 
                "upc": upc,
                "cover": cover_url,
                "manual": is_manual,
                "is_deleted": False,
                # Salviamo i dati originali per il LOG RAW
                "original_title": title,
                "original_artist": artist,
                "original_composer": composer_name,
                "_raw_isrc": isrc,
                "_raw_upc": upc,
                "_raw_meta": raw_meta_package
            }

            self.playlist.append(new_entry) 
            self._save_song_to_db(new_entry)
            self._next_id += 1

            if status_enrichment == "Pending":
                threading.Thread(
                    target=self._background_enrichment,
                    args=(new_entry, target_artist),
                    daemon=True
                ).start()

            print(f"✅ Aggiunto: {title}")
            return {"added": True, "song": new_entry}

    # --- THREAD DI ARRICCHIMENTO ---
    def _background_enrichment(self, entry, target_artist):
        attempts = 0
        max_attempts = 3
        found_composer = "Sconosciuto"
        final_cover = entry.get('cover') 
        success = False

        print(f"🧵 [Thread] Inizio arricchimento per: {entry['title']}")

        if self.spotify_bot:
            try:
                hd_cover = self.spotify_bot.get_hd_cover(entry['title'], entry['artist'])
                if hd_cover:
                    final_cover = hd_cover
            except Exception as e:
                print(f"     ⚠️ Errore Spotify Cover: {e}")

        while attempts < max_attempts:
            try:
                comp_result, cover_fallback = self.meta_bot.find_composer(
                    title=entry['title'], 
                    detected_artist=entry['artist'],
                    isrc=entry.get('_raw_isrc'),
                    upc=entry.get('_raw_upc'),
                    setlist_artist=target_artist,
                    raw_acr_meta=entry.get('_raw_meta')
                )
                found_composer = comp_result
                
                if not final_cover and cover_fallback:
                    final_cover = cover_fallback
                
                success = True
                break 

            except Exception as e:
                print(f"⚠️ Errore Enrichment (Tentativo {attempts+1}): {e}")
                attempts += 1
                if attempts >= max_attempts:
                    found_composer = "Errore Conn."
                else:
                    time.sleep(1)

        with self.lock:
            target_song = next((s for s in self.playlist if s['id'] == entry['id']), None)
            
            if target_song:
                # 1. Aggiorna in memoria (Lista corrente)
                target_song['composer'] = found_composer
                
                # 2. Aggiorna in memoria (Campo originale per il LOG RAW)
                # IMPORTANTE: Se il bot lo trova, quello diventa il dato originale tecnico.
                target_song['original_composer'] = found_composer
                
                # 3. Aggiorna nel DB (chiamando la funzione fixata sopra)
                self._update_composer_in_db(target_song['id'], found_composer)
                
                if final_cover and final_cover != target_song.get('cover'):
                    target_song['cover'] = final_cover
                    self._update_cover_in_db(target_song['id'], final_cover)

                print(f"📝 [Thread] Compositore: {found_composer}")
                
                if success and found_composer not in ["Sconosciuto", "Errore Conn."]:
                    if not target_song.get('is_deleted'):
                        track_key = f"{target_song['title']} - {target_song['artist']}".lower()
                        self.known_songs_cache[track_key] = target_song.copy()

    def get_playlist(self):
        return self.playlist

    def clear_session(self):
        with self.lock:
            self.playlist = []
            self.known_songs_cache = {}
            self._next_id = 1
            try:
                with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM songs')
                    conn.commit()
                print("🧹 Sessione resettata.")
                return True
            except Exception as e:
                print(f"❌ Errore reset DB: {e}")
                return False

    def delete_song(self, song_id):
        # NOTA: Qui facciamo Soft Delete
        with self.lock:
            try:
                song_id = int(song_id)
                # Aggiorniamo la lista in memoria
                for s in self.playlist:
                    if s['id'] == song_id:
                        s['is_deleted'] = True
                        break
                
                self._delete_from_db(song_id)
                return True
            except ValueError:
                return False