import threading
import time
import re
import unicodedata
from datetime import datetime
from threading import Lock
from metadata_manager import MetadataManager
from spotify_manager import SpotifyManager
from difflib import SequenceMatcher
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from firebase_admin import firestore
except ImportError:
    firestore = None

class SessionManager:
    def __init__(self, db_instance):
        self.db = db_instance
        self.playlist = []
        self.known_songs_cache = {}
        self.meta_bot = MetadataManager()
        self.spotify_bot = SpotifyManager()
        self.lock = Lock()
        self.user_id = "demo_user_01" 
        
        if self.db:
            session_id = f"session_{int(time.time())}"
            self.user_ref = self.db.collection('users').document(self.user_id)
            self.session_ref = self.user_ref.collection('sessions').document(session_id)
            self.session_ref.set({
                'created_at': firestore.SERVER_TIMESTAMP,
                'status': 'live',
                'device': 'python_backend'
            }, merge=True)
            print(f"🔥 Session Manager Connesso a Firestore. Session ID: {session_id}")
        else:
            self.session_ref = None
            print("⚠️ Session Manager in modalità OFFLINE.")

    # --- METODI AUTH (Dal Collega) ---
    def register_user(self, user_data):
        """Registra utente con controllo doppio (Username o Email) e campo Nome d'Arte."""
        if not self.db: return {"success": False, "error": "Database offline"}

        username = user_data.get("username", "").strip()
        email = user_data.get("email", "").strip()
        role = user_data.get("role")
        
        if not username or not email:
            return {"success": False, "error": "Username ed Email obbligatori"}

        users_ref = self.db.collection('users')
        
        # 1. Controllo Username (ID Documento)
        doc_user = users_ref.document(username).get()
        if doc_user.exists:
            return {"success": False, "error": "Username già utilizzato"}

        # 2. Controllo Email (Query)
        email_query = users_ref.where("email", "==", email).stream()
        if any(email_query):
            return {"success": False, "error": "Email già utilizzata"}

        hashed_pw = generate_password_hash(user_data.get("password"))

        new_user = {
            "nome": user_data.get("nome"),
            "cognome": user_data.get("cognome"),
            "username": username,
            "email": email,
            "password": hashed_pw,
            "role": role,
            "birthdate": user_data.get("birthdate"),
            "created_at": firestore.SERVER_TIMESTAMP
        }

        # 3. Se Compositore, aggiungi Nome d'Arte
        if role == "composer":
            stage_name = user_data.get("stage_name", "").strip()
            if stage_name:
                new_user["stage_name"] = stage_name

        try:
            users_ref.document(username).set(new_user)
            print(f"👤 Nuovo utente registrato: {username} ({role})")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def login_user(self, identifier, password, required_role):
        """Login che accetta Username O Email."""
        if not self.db: 
            if identifier == "admin" and password == "admin": return {"success": True}
            return {"success": False, "error": "Database offline"}

        users_ref = self.db.collection('users')
        user_data = None
        
        # 1. Prova come Username (Ricerca diretta ID)
        doc = users_ref.document(identifier).get()
        if doc.exists:
            user_data = doc.to_dict()
        else:
            # 2. Prova come Email (Query)
            query = users_ref.where("email", "==", identifier).limit(1).stream()
            for q_doc in query:
                user_data = q_doc.to_dict()
                identifier = user_data.get('username', identifier)
                break
        
        if not user_data:
            return {"success": False, "error": "Utente non trovato"}

        if not check_password_hash(user_data['password'], password):
            return {"success": False, "error": "Password errata"}

        db_role = user_data.get('role')
        if db_role != required_role:
            return {
                "success": False, 
                "error": f"Accesso negato! Sei registrato come '{db_role}', non puoi accedere all'area '{required_role}'."
            }

        self.user_id = identifier
        self.user_ref = self.db.collection('users').document(self.user_id)
        
        return {"success": True, "user": user_data}

    # --- GESTIONE DATI SU DB ---
    def _save_song_to_db(self, song):
        if not self.session_ref: return
        try:
            doc_ref = self.session_ref.collection('songs').document(str(song['id']))
            doc_ref.set(song)
            print(f"☁️ Salvato su Cloud: {song['title']}")
        except Exception as e:
            print(f"❌ Errore scrittura Firestore: {e}")

    def _update_single_field(self, song_id, field, value):
        if not self.session_ref: return
        try:
            doc_ref = self.session_ref.collection('songs').document(str(song_id))
            doc_ref.update({field: value})
        except Exception as e:
            print(f"❌ Errore update campo '{field}': {e}")

    def _normalize_string(self, text):
        if not text: return ""
        text = re.sub(r"(?i)\b(amazon\s+music|apple\s+music|spotify|deezer|youtube|vevo)\b.*", "", text)
        text = re.sub(r"[\(\[\{].*?[\)\]\}]", "", text)
        text = re.sub(r"(?i)\b(live\s+(at|in|from|on))\b.*", "", text)
        text = re.sub(r"(?i)\s-\s.*live.*", "", text)
        text = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|performed by|originally by)\b.*", "", text)
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", text) 
        return clean.strip().lower()

    def _are_songs_equivalent(self, new_s, existing_s):
        # Aggiunta Collega: Ignora canzoni marcate come cancellate
        if existing_s.get('is_deleted', False): return False
        
        tit_new = self._normalize_string(new_s['title'])
        tit_ex = self._normalize_string(existing_s['title'])
        art_new = self._normalize_string(new_s['artist'])
        art_ex = self._normalize_string(existing_s['artist'])
        
        title_similarity = SequenceMatcher(None, tit_new, tit_ex).ratio()
        
        if title_similarity > 0.90:
            if art_new == art_ex or art_new in art_ex or art_ex in art_new: return True
            art_similarity = SequenceMatcher(None, art_new, art_ex).ratio()
            if art_similarity > 0.60: return True
            return False
            
        if title_similarity > 0.80:
            if art_new == art_ex or art_new in art_ex or art_ex in art_new:
                if abs(len(tit_new) - len(tit_ex)) > 4: return False
                return True
        return False

    # --- ADD SONG (Versione MERGED: Struttura Collega + Logica Tua) ---
    def add_song(self, song_data, target_artist=None):
        with self.lock:
            if song_data.get('status') != 'success':
                return {"added": False, "reason": "No match"}
            
            # 1. Dati RAW per il Report (Dal Collega)
            raw_title_for_report = song_data['title']
            raw_artist_for_report = song_data['artist']
            
            # Variabili modificabili dalla logica Smart
            title = song_data['title']
            artist = song_data['artist']
            
            candidate_song = {
                'title': title, 'artist': artist,
                'duration_ms': song_data.get('duration_ms', 0),
                'cover': song_data.get('cover')
            }

            # 2. Logica "SMART FIX" (RIPRISTINATA DALLA TUA VERSIONE)
            if self.spotify_bot:
                try:
                    clean_title_base = re.sub(r"[\(\[].*?[\)\]]", "", title).strip()
                    clean_title_base = re.sub(r"(?i)\b(live\s+(at|in|from|on))\b.*", "", clean_title_base)
                    clean_title_base = re.sub(r"(?i)\s-\s.*live.*", "", clean_title_base)
                    clean_title_base = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version)\b.*", "", clean_title_base).strip()

                    bias_resolved = False

                    # STEP A: Tentativo Bias Artist
                    if target_artist:
                        t_norm = self._normalize_string(target_artist)
                        a_norm = self._normalize_string(artist)
                        
                        if t_norm not in a_norm and a_norm not in t_norm:
                            print(f"🕵️ Bias Attivo: Controllo se '{clean_title_base}' è di {target_artist}...")
                            match_info = self.spotify_bot.search_specific_version(clean_title_base, target_artist)
                            
                            if match_info:
                                new_art, new_cov = match_info
                                new_art_norm = self._normalize_string(new_art)
                                
                                # Validazione
                                if t_norm in new_art_norm or new_art_norm in t_norm:
                                    print(f"🔄 [Bias Swap] Sostituisco {artist} -> {new_art}")
                                    artist = new_art
                                    title = clean_title_base 
                                    candidate_song['artist'] = new_art
                                    candidate_song['title'] = clean_title_base
                                    if new_cov:
                                        candidate_song['cover'] = new_cov
                                        song_data['cover'] = new_cov
                                    bias_resolved = True 
                                else:
                                    print(f"⚠️ [Bias Reject] Spotify ha proposto '{new_art}' ma cercavo '{target_artist}'.")
                        else:
                            bias_resolved = True

                    # STEP B: Fallback Popolarità
                    if not bias_resolved:
                        better_version = self.spotify_bot.get_most_popular_version(title, artist)
                        if better_version:
                            new_artist, new_cover, popularity = better_version
                            print(f"🚀 [Pop Swap] Fallback: {artist} -> {new_artist} (Pop: {popularity})")
                            artist = new_artist
                            candidate_song['artist'] = new_artist
                            candidate_song['title'] = clean_title_base 
                            title = clean_title_base
                            if new_cover:
                                candidate_song['cover'] = new_cover
                                song_data['cover'] = new_cover 
                            
                except Exception as e:
                    print(f"⚠️ Errore Smart Fix Cascata: {e}")

            # 3. Controllo Duplicati
            for existing_song in self.playlist[-15:]:
                if self._are_songs_equivalent(candidate_song, existing_song):
                    # Se è duplicato ma era "cancellato" (soft delete), potremmo volerlo riattivare?
                    # Per ora lo trattiamo come duplicato e basta.
                    return {"added": False, "reason": "Duplicate", "song": existing_song}
            
            track_key = f"{title} - {artist}".lower()
            cached_entry = self.known_songs_cache.get(track_key)
            next_id = len(self.playlist) + 1
            
            if cached_entry:
                composer_name = cached_entry['composer']
                cover_url = cached_entry.get('cover') or song_data.get('cover')
                status_enrichment = "Done"
            else:
                composer_name = "⏳ Ricerca..."
                cover_url = song_data.get('cover')
                status_enrichment = "Pending"

            # 4. Creazione Dizionario Finale (Campi Collega + Dati Corretti)
            new_entry = {
                "id": next_id, 
                "title": title,   # Titolo "Smart"
                "artist": artist, # Artista "Smart"
                "composer": composer_name,      
                "album": song_data.get('album', 'Sconosciuto'),
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "duration_ms": song_data.get('duration_ms', 0),
                "isrc": song_data.get('isrc'), "upc": song_data.get('upc'), 
                "cover": cover_url,
                "_raw_meta": song_data.get('external_metadata', {}),
                
                # CAMPI CHIAVE REPORT / LOG TECNICO
                "original_title": raw_title_for_report,   # Titolo Originale ACR
                "original_artist": raw_artist_for_report, # Artista Originale ACR
                "original_composer": composer_name,
                "confirmed": True,
                "is_deleted": False, # Flag Soft Delete
                "manual": False
            }

            self.playlist.append(new_entry)
            self._save_song_to_db(new_entry)

            if status_enrichment == "Pending":
                threading.Thread(target=self._background_enrichment, args=(new_entry, target_artist), daemon=True).start()

            print(f"✅ Aggiunto: {title} - {artist}")
            return {"added": True, "song": new_entry}

    def _background_enrichment(self, entry, target_artist):
        attempts = 0
        found_composer = "Sconosciuto"
        final_cover = entry.get('cover')
        
        while attempts < 3:
            try:
                comp_result, cover_fallback = self.meta_bot.find_composer(
                    title=entry['title'], detected_artist=entry['artist'],
                    isrc=entry.get('isrc'), upc=entry.get('upc'),
                    setlist_artist=target_artist, raw_acr_meta=entry.get('_raw_meta')
                )
                found_composer = comp_result
                if not final_cover and cover_fallback: final_cover = cover_fallback
                break 
            except:
                attempts += 1
                time.sleep(1)

        with self.lock:
            target_song = next((s for s in self.playlist if s['id'] == entry['id']), None)
            if target_song:
                target_song['composer'] = found_composer
                self._update_single_field(target_song['id'], 'composer', found_composer)
                
                if target_song.get('original_composer') == "⏳ Ricerca...":
                     target_song['original_composer'] = found_composer
                     self._update_single_field(target_song['id'], 'original_composer', found_composer)

                if final_cover and final_cover != target_song.get('cover'):
                    target_song['cover'] = final_cover
                    self._update_single_field(target_song['id'], 'cover', final_cover)

                if found_composer not in ["Sconosciuto", "Errore Conn."]:
                    track_key = f"{target_song['title']} - {target_song['artist']}".lower()
                    self.known_songs_cache[track_key] = target_song.copy()

    def get_playlist(self):
        return self.playlist

    def clear_session(self):
        with self.lock:
            self.playlist = []
            self.known_songs_cache = {}
            return True

    def delete_song(self, song_id):
        # Soft Delete (Dal Collega) - Ottima scelta
        with self.lock:
            try:
                song_id = int(song_id)
                for song in self.playlist:
                    if song['id'] == song_id:
                        song['is_deleted'] = True
                        self._update_single_field(song_id, 'is_deleted', True)
                        print(f"🗑️ Soft Delete (Marked): ID {song_id}")
                        return True
                return False
            except ValueError: return False