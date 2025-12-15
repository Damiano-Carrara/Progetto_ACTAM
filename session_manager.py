import threading
import time
import re
import sqlite3
import unicodedata
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
        
        print(f"📝 Session Manager Inizializzato (Accent-Insensitive + SQLite: {self.db_path})")

    # --- GESTIONE DATABASE (Merge: Logica Collega per migrazione colonne) ---
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
            
            # 2. Controllo/Migrazione Colonna 'cover'
            cursor.execute("PRAGMA table_info(songs)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'cover' not in columns:
                print("🔧 [DB] Aggiungo colonna mancante: 'cover'")
                cursor.execute("ALTER TABLE songs ADD COLUMN cover TEXT")
            
            conn.commit()

    def _load_session_from_db(self):
        """Ricarica la sessione precedente"""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row 
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM songs ORDER BY id ASC')
            rows = cursor.fetchall()
            
            if rows:
                print(f"♻️ Ripristino sessione: trovati {len(rows)} brani nel database.")
                for row in rows:
                    song = dict(row)
                    song['_raw_meta'] = {} # Init vuoto
                    
                    # [IMPORTANTE] Inizializza campi per reportistica RAW se mancano nel DB
                    if 'original_title' not in song: song['original_title'] = song['title']
                    if 'original_composer' not in song: song['original_composer'] = song['composer']
                    if 'original_artist' not in song: song['original_artist'] = song['artist']
                    
                    # Default: se carico dal DB, assumo non sia cancellato (hard persistence)
                    song['is_deleted'] = False 

                    self.playlist.append(song)
                    
                    track_key = f"{song['title']} - {song['artist']}".lower()
                    self.known_songs_cache[track_key] = song
                    if song['id'] >= self._next_id:
                        self._next_id = song['id'] + 1
            else:
                print("🆕 Nessuna sessione precedente trovata. Parto da zero.")

    def _save_song_to_db(self, song):
        """Salva un nuovo brano nel DB (inclusa cover)"""
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

    def _update_composer_in_db(self, song_id, composer):
        """Aggiorna solo il compositore"""
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE songs SET composer = ? WHERE id = ?', (composer, song_id))
                conn.commit()
        except Exception as e:
            print(f"❌ Errore update DB: {e}")

    def _update_cover_in_db(self, song_id, cover_url):
        """Aggiorna solo la cover (Nuovo metodo)"""
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

    # --- LOGICA MATCHING (TUA VERSIONE - MANTENUTA INTATTA) ---
    def _normalize_string(self, text):
        if not text: return ""
        text = re.sub(r"[\(\[].*?[\)\]]", "", text)
        text = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live)\b.*", "", text)
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", text)
        return clean.strip().lower()

    def _are_songs_equivalent(self, new_s, existing_s):
        # [MODIFICA] Se un brano è cancellato logicamente, ignoralo nei controlli duplicati
        if existing_s.get('is_deleted'):
            return False

        # 1. CONTROLLO ARTISTA (Rigido)
        # Se gli artisti sono diversi, non è mai un duplicato
        art_new = self._normalize_string(new_s['artist'])
        art_ex = self._normalize_string(existing_s['artist'])
        
        if art_new != art_ex and art_new not in art_ex and art_ex not in art_new:
            return False

        # 2. CALCOLO SIMILARITÀ TITOLO
        tit_new = self._normalize_string(new_s['title'])
        tit_ex = self._normalize_string(existing_s['title'])
        similarity = SequenceMatcher(None, tit_new, tit_ex).ratio()

        # --- SOGLIE AGGIORNATE ---
        
        # Sotto il 60%: Sicuramente DIVERSI (es. "Amore bello" vs "E tu")
        if similarity < 0.60: 
            return False

        # Sopra l'85%: Sicuramente UGUALI (es. "Strada facendo" vs "Strada facend")
        if similarity > 0.85: 
            return True

        # --- ZONA GRIGIA (60% - 85%) ---
        # Qui cadono "Quanto ti voglio" vs "Quante volte" (simil ~64%)
        # Per decidere se sono uguali, controlliamo la DURATA.
        
        try:
            dur_new = int(new_s.get('duration_ms', 0) or 0)
            dur_ex = int(existing_s.get('duration_ms', 0) or 0)
        except:
            dur_new, dur_ex = 0, 0

        # Se non abbiamo la durata di entrambi, nel dubbio NON uniamo (meglio un duplicato visibile che un brano perso)
        if dur_new == 0 or dur_ex == 0:
            return False

        MIN_VALID_DURATION = 30000 
        if dur_new > MIN_VALID_DURATION and dur_ex > MIN_VALID_DURATION:
            diff = abs(dur_new - dur_ex)
            
            # Se la durata è quasi identica (differenza < 2.5 secondi), allora è PROBABILMENTE lo stesso brano
            # (es. rimosso "Remix" dal titolo ma l'audio è quello)
            if diff < 2500: 
                print(f"🔄 Duplicato Smart ({similarity:.2f}): '{tit_new}' == '{tit_ex}' (Diff durata: {diff}ms)")
                return True
        
        # Se siamo nella zona grigia ma la durata è diversa (o non valida),
        # assumiamo che siano DUE CANZONI DIVERSE (es. "Quante volte" 4min vs "Quanto ti voglio" 3min)
        return False

    # --- CORE LOGIC ---
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

            for existing_song in self.playlist[-15:]:
                if self._are_songs_equivalent(candidate_song, existing_song):
                    print(f"♻️ Duplicato Scartato: {title}")
                    return {"added": False, "reason": "Duplicate (Smart Match)", "song": existing_song}

            track_key = f"{title} - {artist}".lower()
            cached_entry = self.known_songs_cache.get(track_key)
            
            # Recupero dati da cache o dal nuovo riconoscimento
            if cached_entry:
                print(f"⚡ Cache Hit! {title}")
                composer_name = cached_entry['composer']
                isrc = cached_entry.get('isrc')
                upc = cached_entry.get('upc')
                # Priorità cover in cache, altrimenti quella nuova
                cover_url = cached_entry.get('cover') or song_data.get('cover')
                status_enrichment = "Done"
                
                # Recupero dati originali dalla cache se esistono
                orig_title = cached_entry.get('original_title', title)
                orig_composer = cached_entry.get('original_composer', composer_name)
                orig_artist = cached_entry.get('original_artist', artist)
            else:
                composer_name = "⏳ Ricerca..."
                isrc = song_data.get('isrc')
                upc = song_data.get('upc')
                cover_url = song_data.get('cover') # Prende la cover da ACRCloud (se c'è)
                status_enrichment = "Pending"
                
                # Nuovi dati originali
                orig_title = title
                orig_composer = composer_name
                orig_artist = artist

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
                "cover": cover_url, # [Nuovo campo]
                "manual": False,
                "is_deleted": False, # [NUOVO] Flag per cancellazione logica
                
                # [NUOVO] Campi Originali Statici per Report Raw
                "original_title": orig_title,
                "original_composer": orig_composer,
                "original_artist": orig_artist,

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

            print(f"✅ Aggiunto (Async + Persistente): {title}")
            return {"added": True, "song": new_entry}

    def _background_enrichment(self, entry, target_artist):
        attempts = 0
        max_attempts = 3
        found_composer = "Sconosciuto"
        found_cover = None # Init
        success = False

        print(f"🧵 [Thread] Inizio ricerca per: {entry['title']}")

        while attempts < max_attempts:
            try:
                # --- PUNTO CRITICO: Unpacking della tupla ---
                # find_composer ora restituisce (composer, cover)
                found_composer, found_cover = self.meta_bot.find_composer(
                    title=entry['title'], 
                    detected_artist=entry['artist'],
                    isrc=entry.get('_raw_isrc'),
                    upc=entry.get('_raw_upc'),
                    setlist_artist=target_artist,
                    raw_acr_meta=entry.get('_raw_meta')
                )
                success = True
                break 

            except Exception as e:
                attempts += 1
                print(f"⚠️ [Thread] Errore API: {e}")
                if attempts < max_attempts:
                    time.sleep(2 ** attempts)
                else:
                    found_composer = "Errore Conn."

        with self.lock:
            target_song = next((s for s in self.playlist if s['id'] == entry['id']), None)
            
            if target_song:
                # 1. Aggiorna Compositore
                target_song['composer'] = found_composer
                
                # [NUOVO] Se è il primo arricchimento, aggiorna anche l'originale se era "Ricerca..."
                if target_song.get('original_composer') == "⏳ Ricerca...":
                    target_song['original_composer'] = found_composer

                self._update_composer_in_db(target_song['id'], found_composer)
                
                # 2. Aggiorna Cover (Se trovata una nuova e migliore)
                if found_cover and not target_song.get('cover'):
                    target_song['cover'] = found_cover
                    self._update_cover_in_db(target_song['id'], found_cover)
                    print(f"🖼️ [Thread] Cover trovata e aggiornata!")
                
                print(f"📝 [Thread] Compositore aggiornato: {found_composer}")
                
                # Aggiorna cache solo se abbiamo risultati validi
                if success and found_composer not in ["Sconosciuto", "Errore Conn."]:
                    track_key = f"{target_song['title']} - {target_song['artist']}".lower()
                    self.known_songs_cache[track_key] = target_song.copy()

    def get_playlist(self, include_deleted=False):
        """Restituisce la playlist. Se include_deleted=False, nasconde i cancellati."""
        if include_deleted:
            return self.playlist
        return [s for s in self.playlist if not s.get('is_deleted', False)]
    
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
        """Soft Delete: marca come cancellato in memoria per il report Raw, rimuove da DB per pulizia"""
        with self.lock:
            try:
                song_id = int(song_id)
                # Soft delete in memoria (così il report Raw può vederlo)
                for s in self.playlist:
                    if s['id'] == song_id:
                        s['is_deleted'] = True
                        break
                
                # Hard delete dal DB (così se riavvio la sessione, il brano non torna più)
                self._delete_from_db(song_id)
                return True
            except ValueError:
                return False