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
        
        print(f"📝 Session Manager Inizializzato (Smart Upgrade + Strict Title Check)")

    # --- GESTIONE DATABASE ---
    def _init_db(self):
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
            
            cursor.execute("PRAGMA table_info(songs)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'cover' not in columns:
                cursor.execute("ALTER TABLE songs ADD COLUMN cover TEXT")
            conn.commit()

    def _load_session_from_db(self):
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
                    self.playlist.append(song)
                    
                    track_key = f"{song['title']} - {song['artist']}".lower()
                    self.known_songs_cache[track_key] = song
                    if song['id'] >= self._next_id:
                        self._next_id = song['id'] + 1
            else:
                print("🆕 Nessuna sessione precedente trovata. Parto da zero.")

    def _save_song_to_db(self, song):
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO songs (id, title, artist, composer, album, timestamp, duration_ms, score, type, isrc, upc, cover)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    song['id'], song['title'], song['artist'], song['composer'],
                    song['album'], song['timestamp'], song['duration_ms'],
                    song['score'], song['type'], song['isrc'], song['upc'],
                    song.get('cover') 
                ))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore salvataggio DB: {e}")

    def _update_full_song_in_db(self, song):
        """Aggiorna TUTTI i dati di un brano (usato per lo Smart Upgrade)"""
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE songs 
                    SET artist=?, album=?, score=?, type=?, isrc=?, upc=?, cover=?
                    WHERE id=?
                ''', (
                    song['artist'], song['album'], song['score'], song['type'],
                    song['isrc'], song['upc'], song.get('cover'), song['id']
                ))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore Full Update DB: {e}")

    def _update_composer_in_db(self, song_id, composer):
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE songs SET composer = ? WHERE id = ?', (composer, song_id))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore update DB: {e}")

    def _update_cover_in_db(self, song_id, cover_url):
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE songs SET cover = ? WHERE id = ?', (cover_url, song_id))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore update Cover DB: {e}")

    def _delete_from_db(self, song_id):
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM songs WHERE id = ?', (song_id,))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore delete DB: {e}")

    # --- LOGICA MATCHING ---
    def _normalize_string(self, text):
        if not text: return ""
        text = re.sub(r"[\(\[].*?[\)\]]", "", text)
        text = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live)\b.*", "", text)
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", text)
        return clean.strip().lower()

    def _are_songs_equivalent(self, new_s, existing_s):
        """
        Versione PULITA: Solo Titolo e Artista.
        Rimosso il controllo durata che causava falsi positivi.
        """
        tit_new = self._normalize_string(new_s['title'])
        tit_ex = self._normalize_string(existing_s['title'])
        
        # 1. Check Titolo (Dominante)
        similarity = SequenceMatcher(None, tit_new, tit_ex).ratio()
        if similarity > 0.90:
            return True

        # 2. Check Standard (Titolo Simile + Artista Simile)
        if similarity > 0.60:
            art_new = self._normalize_string(new_s['artist'])
            art_ex = self._normalize_string(existing_s['artist'])
            if art_new == art_ex or art_new in art_ex or art_ex in art_new:
                return True

        # RIMOSSO BLOCCO 3 (Durata)
        
        return False

    def _is_better_match(self, new_artist, old_artist, target_artist):
        """Verifica se il nuovo artista è 'migliore' (matcha il target bias) rispetto al vecchio"""
        if not target_artist: return False
        
        target_norm = self._normalize_string(target_artist)
        new_norm = self._normalize_string(new_artist)
        old_norm = self._normalize_string(old_artist)
        
        new_matches = (target_norm in new_norm) or (new_norm in target_norm)
        old_matches = (target_norm in old_norm) or (old_norm in target_norm)
        
        # Se il nuovo è il target e il vecchio NO -> Upgrade!
        if new_matches and not old_matches:
            return True
        return False

    # --- ADD SONG ---
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

            # Check duplicati negli ultimi 15 brani
            for existing_song in self.playlist[-15:]:
                if self._are_songs_equivalent(candidate_song, existing_song):
                    
                    # === SMART UPGRADE ===
                    # Se il titolo è lo stesso, ma il nuovo artista è quello giusto (Target)
                    # mentre quello vecchio era sbagliato (es. Cover Band), AGGIORNIAMO l'esistente!
                    if self._is_better_match(artist, existing_song['artist'], target_artist):
                        print(f"🔄 Smart Upgrade: '{existing_song['artist']}' -> '{artist}'")
                        
                        # Aggiorniamo i dati in RAM
                        existing_song['artist'] = artist
                        existing_song['album'] = song_data.get('album', existing_song['album'])
                        existing_song['score'] = song_data.get('score', existing_song['score'])
                        existing_song['type'] = song_data.get('type', existing_song['type'])
                        existing_song['isrc'] = song_data.get('isrc')
                        existing_song['upc'] = song_data.get('upc')
                        
                        # Se il nuovo ha una cover, usala
                        new_cover = song_data.get('cover')
                        if new_cover: existing_song['cover'] = new_cover

                        # Aggiorniamo i dati nel DB
                        self._update_full_song_in_db(existing_song)
                        
                        # Rilanciamo l'arricchimento (magari ora troviamo i compositori giusti!)
                        existing_song['composer'] = "⏳ Aggiornamento..."
                        threading.Thread(
                            target=self._background_enrichment,
                            args=(existing_song, target_artist),
                            daemon=True
                        ).start()
                        
                        return {"added": True, "updated": True, "song": existing_song}
                    
                    # Se non è un upgrade, scartiamo come duplicato normale
                    print(f"♻️ Duplicato Scartato: {title} (Artist: {artist})")
                    return {"added": False, "reason": "Duplicate", "song": existing_song}

            # --- NUOVO INSERIMENTO (Se non è duplicato) ---
            track_key = f"{title} - {artist}".lower()
            cached_entry = self.known_songs_cache.get(track_key)
            
            if cached_entry:
                print(f"⚡ Cache Hit! {title}")
                composer_name = cached_entry['composer']
                isrc = cached_entry.get('isrc')
                upc = cached_entry.get('upc')
                cover_url = cached_entry.get('cover') or song_data.get('cover')
                status_enrichment = "Done"
            else:
                composer_name = "⏳ Ricerca..."
                isrc = song_data.get('isrc')
                upc = song_data.get('upc')
                cover_url = song_data.get('cover')
                status_enrichment = "Pending"

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
                "type": song_data.get('type', 'Original'),
                "isrc": isrc, 
                "upc": upc,
                "cover": cover_url,
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

        # 1. SPOTIFY HD
        if self.spotify_bot:
            try:
                hd_cover = self.spotify_bot.get_hd_cover(entry['title'], entry['artist'])
                if hd_cover: final_cover = hd_cover
            except: pass

        # 2. RICERCA COMPOSITORE
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
                time.sleep(1)

        # 3. SALVATAGGIO FINALE
        with self.lock:
            # Ricarichiamo l'oggetto dalla playlist per essere sicuri di aggiornare quello vivo
            target_song = next((s for s in self.playlist if s['id'] == entry['id']), None)
            
            if target_song:
                target_song['composer'] = found_composer
                self._update_composer_in_db(target_song['id'], found_composer)
                
                if final_cover and final_cover != target_song.get('cover'):
                    target_song['cover'] = final_cover
                    self._update_cover_in_db(target_song['id'], final_cover)
                    print(f"🖼️ [Thread] Cover aggiornata!")

                print(f"📝 [Thread] Compositore: {found_composer}")
                
                # Salviamo in cache solo se abbiamo trovato dati validi
                if success and found_composer not in ["Sconosciuto", "Errore Conn."]:
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
        with self.lock:
            try:
                song_id = int(song_id)
                self.playlist = [s for s in self.playlist if s['id'] != song_id]
                self._delete_from_db(song_id)
                return True
            except ValueError:
                return False