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
        
        # Default user ID (modalità ospite/iniziale)
        self.user_id = "demo_user_01"
        self.session_ref = None
        self.user_ref = None

        if self.db:
            # Creiamo una sessione iniziale di default
            self._start_new_firestore_session()
        else:
            print("⚠️ Session Manager in modalità OFFLINE.")

    def _start_new_firestore_session(self):
        """Crea un nuovo documento sessione su Firestore per l'utente CORRENTE."""
        if not self.db: return

        try:
            # 1. Aggiorniamo il riferimento Utente
            self.user_ref = self.db.collection('users').document(str(self.user_id))
            
            # 2. Creiamo un nuovo ID Sessione basato sul tempo
            session_id = f"session_{int(time.time())}"
            
            # 3. Aggiorniamo il riferimento Sessione (Qui stava il problema!)
            self.session_ref = self.user_ref.collection('sessions').document(session_id)
            
            # 4. Scriviamo i metadati iniziali
            self.session_ref.set({
                'created_at': firestore.SERVER_TIMESTAMP,
                'status': 'live',
                'device': 'python_backend',
                'user_id': self.user_id # Utile per debug
            }, merge=True)
            
            print(f"🔥 Nuova Sessione Firestore creata: users/{self.user_id}/sessions/{session_id}")
            
        except Exception as e:
            print(f"❌ Errore creazione sessione Firestore: {e}")

    # --- METODI AUTH ---
    def register_user(self, user_data):
        """Registra utente con controllo doppio (Username o Email)."""
        if not self.db: return {"success": False, "error": "Database offline"}

        username = user_data.get("username", "").strip()
        email = user_data.get("email", "").strip()
        role = user_data.get("role")
        
        if not username or not email:
            return {"success": False, "error": "Username ed Email obbligatori"}

        users_ref = self.db.collection('users')
        
        # Controllo esistenza
        if users_ref.document(username).get().exists:
            return {"success": False, "error": "Username già utilizzato"}
        
        if any(users_ref.where("email", "==", email).stream()):
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
        if role == "composer":
            new_user["stage_name"] = user_data.get("stage_name", "").strip()

        try:
            users_ref.document(username).set(new_user)
            print(f"👤 Nuovo utente registrato: {username}")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def login_user(self, identifier, password, required_role):
        """Login che aggiorna l'utente corrente e crea una nuova sessione."""
        if not self.db: 
            if identifier == "admin" and password == "admin": return {"success": True}
            return {"success": False, "error": "Database offline"}

        users_ref = self.db.collection('users')
        user_data = None
        
        # Ricerca utente (Username o Email)
        doc = users_ref.document(identifier).get()
        if doc.exists:
            user_data = doc.to_dict()
        else:
            query = users_ref.where("email", "==", identifier).limit(1).stream()
            for q_doc in query:
                user_data = q_doc.to_dict()
                identifier = user_data.get('username', identifier) # Normalizziamo identifier allo username
                break
        
        if not user_data:
            return {"success": False, "error": "Utente non trovato"}

        if not check_password_hash(user_data['password'], password):
            return {"success": False, "error": "Password errata"}

        if user_data.get('role') != required_role:
            return {"success": False, "error": f"Ruolo errato. Richiesto: {required_role}"}

        # === PUNTO CRUCIALE: AGGIORNIAMO L'UTENTE E LA SESSIONE ===
        self.user_id = identifier
        print(f"✅ Login effettuato come: {self.user_id}")
        
        # Resettiamo la memoria locale
        self.clear_session() 
        # (clear_session ora chiamerà anche _start_new_firestore_session grazie alla modifica sotto)
        
        return {"success": True, "user": user_data}

    # --- GESTIONE DATI SU DB ---
    def _save_song_to_db(self, song):
        if not self.session_ref: return
        try:
            doc_ref = self.session_ref.collection('songs').document(str(song['id']))
            doc_ref.set(song)
            print(f"☁️ Salvato su Cloud ({self.user_id}): {song['title']}")
        except Exception as e:
            print(f"❌ Errore scrittura Firestore: {e}")

    def _update_single_field(self, song_id, field, value):
        if not self.session_ref: return
        try:
            doc_ref = self.session_ref.collection('songs').document(str(song_id))
            doc_ref.update({field: value})
        except Exception as e:
            print(f"❌ Errore update campo '{field}': {e}")

    # ... [I metodi _normalize_string e _are_songs_equivalent restano uguali] ...
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

    def add_song(self, song_data, target_artist=None):
        with self.lock:
            if song_data.get('status') != 'success':
                return {"added": False, "reason": "No match"}
            
            raw_title_for_report = song_data['title']
            raw_artist_for_report = song_data['artist']
            title = song_data['title']
            artist = song_data['artist']
            
            candidate_song = {
                'title': title, 'artist': artist,
                'duration_ms': song_data.get('duration_ms', 0),
                'cover': song_data.get('cover')
            }

            if self.spotify_bot:
                try:
                    clean_title_base = re.sub(r"[\(\[].*?[\)\]]", "", title).strip()
                    clean_title_base = re.sub(r"(?i)\b(live\s+(at|in|from|on))\b.*", "", clean_title_base)
                    clean_title_base = re.sub(r"(?i)\s-\s.*live.*", "", clean_title_base)
                    clean_title_base = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version)\b.*", "", clean_title_base).strip()

                    bias_resolved = False
                    if target_artist:
                        t_norm = self._normalize_string(target_artist)
                        a_norm = self._normalize_string(artist)
                        if t_norm not in a_norm and a_norm not in t_norm:
                            match_info = self.spotify_bot.search_specific_version(clean_title_base, target_artist)
                            if match_info:
                                new_art, new_cov = match_info
                                new_art_norm = self._normalize_string(new_art)
                                if t_norm in new_art_norm or new_art_norm in t_norm:
                                    artist = new_art
                                    title = clean_title_base 
                                    candidate_song['artist'] = new_art
                                    candidate_song['title'] = clean_title_base
                                    if new_cov:
                                        candidate_song['cover'] = new_cov
                                        song_data['cover'] = new_cov
                                    bias_resolved = True 
                    
                    if not bias_resolved:
                        better_version = self.spotify_bot.get_most_popular_version(title, artist)
                        if better_version:
                            new_artist, new_cover, popularity = better_version
                            artist = new_artist
                            candidate_song['artist'] = new_artist
                            candidate_song['title'] = clean_title_base 
                            title = clean_title_base
                            if new_cover:
                                candidate_song['cover'] = new_cover
                                song_data['cover'] = new_cover 
                except Exception as e:
                    print(f"⚠️ Errore Smart Fix Cascata: {e}")

            for existing_song in self.playlist[-15:]:
                if self._are_songs_equivalent(candidate_song, existing_song):
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

            new_entry = {
                "id": next_id, 
                "title": title,
                "artist": artist,
                "composer": composer_name,      
                "album": song_data.get('album', 'Sconosciuto'),
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "duration_ms": song_data.get('duration_ms', 0),
                "isrc": song_data.get('isrc'), "upc": song_data.get('upc'), 
                "cover": cover_url,
                "_raw_meta": song_data.get('external_metadata', {}),
                "original_title": raw_title_for_report,
                "original_artist": raw_artist_for_report,
                "original_composer": composer_name,
                "confirmed": True,
                "is_deleted": False,
                "manual": False
            }

            self.playlist.append(new_entry)
            self._save_song_to_db(new_entry)

            if status_enrichment == "Pending":
                threading.Thread(target=self._background_enrichment, args=(new_entry, target_artist), daemon=True).start()

            print(f"✅ Aggiunto: {title} - {artist}")
            return {"added": True, "song": new_entry}

    # ... [Il metodo _background_enrichment resta uguale] ...
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

    def recover_last_session(self):
        """
        Cerca nello storico dell'utente l'ultima sessione che contenga dati (ignora quelle vuote).
        """
        if not self.db or self.user_id == "demo_user_01":
            return {"success": False, "message": "Funzione non disponibile per ospiti o offline."}

        try:
            # 1. Scarichiamo le ultime 5 sessioni (non solo 1)
            sessions_ref = self.user_ref.collection('sessions')
            query = sessions_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(5)
            last_sessions = list(query.stream())

            if not last_sessions:
                return {"success": False, "message": "Nessuna sessione trovata nello storico."}

            found_playlist = []
            target_session_doc = None

            # 2. Scorriamo le sessioni partendo dalla più recente
            for session_doc in last_sessions:
                songs_ref = session_doc.reference.collection('songs')
                songs_docs = list(songs_ref.stream())
                
                # Se questa sessione ha canzoni, è quella che cerchiamo!
                if len(songs_docs) > 0:
                    target_session_doc = session_doc
                    for doc in songs_docs:
                        found_playlist.append(doc.to_dict())
                    break # Trovata, ci fermiamo qui
            
            if not found_playlist or not target_session_doc:
                return {"success": False, "message": "Trovate sessioni recenti, ma sono tutte vuote."}

            # 3. Ordiniamo e carichiamo in RAM
            found_playlist.sort(key=lambda x: int(x['id']) if isinstance(x['id'], int) else 0)

            with self.lock:
                self.playlist = found_playlist
                # Ricostruiamo la cache
                self.known_songs_cache = {
                    f"{s['title']} - {s['artist']}".lower(): s
                    for s in found_playlist
                }
                # IMPORTANTE: Riagganciamo il puntatore sessione a quella recuperata!
                # Altrimenti le nuove modifiche finirebbero nella sessione vuota corrente.
                self.session_ref = target_session_doc.reference

            print(f"♻️ Ripristinata sessione del {target_session_doc.id}: {len(self.playlist)} brani.")
            return {"success": True, "count": len(self.playlist)}

        except Exception as e:
            print(f"❌ Errore recupero sessione: {e}")
            return {"success": False, "message": str(e)}
    
    def get_playlist(self):
        return self.playlist

    def clear_session(self):
        """Resetta la playlist E crea un nuovo documento su Firestore per la nuova sessione."""
        with self.lock:
            self.playlist = []
            self.known_songs_cache = {}
            # CRUCIALE: Ogni volta che si resetta (Start Session), 
            # creiamo un nuovo documento per l'utente attualmente loggato.
            self._start_new_firestore_session()
            return True

    def delete_song(self, song_id):
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