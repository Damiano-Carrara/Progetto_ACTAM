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
            self.user_ref = self.db.collection('users').document(str(self.user_id))
            session_id = f"session_{int(time.time())}"
            self.session_ref = self.user_ref.collection('sessions').document(session_id)
            
            # 1. Crea la sessione
            self.session_ref.set({
                'created_at': firestore.SERVER_TIMESTAMP,
                'status': 'live',
                'device': 'python_backend',
                'song_count': 0  # Inizializziamo a 0
            }, merge=True)
            
            # 2. AGGIORNAMENTO STATS UTENTE: Incrementa contatore sessioni totali
            self.user_ref.set({
                'stats': {
                    'total_sessions': firestore.Increment(1)
                }
            }, merge=True)
            
            print(f"🔥 Nuova Sessione Firestore creata: users/{self.user_id}/sessions/{session_id}")
            
        except Exception as e:
            print(f"❌ Errore creazione sessione Firestore: {e}")

    # --- METODI AUTH ---
    def register_user(self, user_data):
        """Registra utente con inizializzazione statistiche."""
        if not self.db: return {"success": False, "error": "Database offline"}

        username = user_data.get("username", "").strip()
        email = user_data.get("email", "").strip()
        role = user_data.get("role")
        
        if not username or not email:
            return {"success": False, "error": "Username ed Email obbligatori"}

        users_ref = self.db.collection('users')
        
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
            "created_at": firestore.SERVER_TIMESTAMP,
            # --- INIZIALIZZAZIONE STATISTICHE A ZERO ---
            "stats": {
                "total_sessions": 0,
                "total_songs": 0
            }
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

        # === AGGIORNIAMO L'UTENTE E LA SESSIONE ===
        self.user_id = identifier
        print(f"✅ Login effettuato come: {self.user_id}")
        
        # Resettiamo la memoria locale
        self.clear_session() 
        
        return {"success": True, "user": user_data}
    
    def logout_user(self):
        """Resetta l'utente corrente a quello di default (Ospite)."""
        self.user_id = "demo_user_01"
        # Resetta anche la sessione in memoria per evitare mix di dati
        self.clear_session()
        print("👋 Logout effettuato. Tornato a demo_user_01.")
        return {"success": True}

    # --- NUOVI METODI PER PROFILO UTENTE ---
    def update_user_data(self, old_username, new_data):
        """Aggiorna username e/o password."""
        if not self.db: return {"success": False, "error": "DB Offline"}
        
        users_ref = self.db.collection('users')
        user_doc_ref = users_ref.document(old_username)
        
        if not user_doc_ref.get().exists:
            return {"success": False, "error": "Utente non trovato"}

        updates = {}
        new_username = new_data.get("new_username")
        new_password = new_data.get("new_password")

        # Se cambia username, dobbiamo creare nuovo doc, copiare dati e cancellare vecchio (Firestore limitation)
        # Ma per semplicità, se cambia username, verifichiamo prima che non esista
        if new_username and new_username != old_username:
            if users_ref.document(new_username).get().exists:
                return {"success": False, "error": "Nuovo username già in uso"}
            
            # Copia dati
            old_data = user_doc_ref.get().to_dict()
            old_data['username'] = new_username
            if new_password:
                old_data['password'] = generate_password_hash(new_password)
            
            # Crea nuovo
            try:
                users_ref.document(new_username).set(old_data)
                
                # IMPORTANTE: Migrare anche le sottocollezioni 'sessions' è complicato.
                # Per ora, in questo MVP, se cambi username perdi lo storico o lo lasciamo lì orfano.
                # Una soluzione semplice è vietare il cambio username se ci sono dati, 
                # oppure per ora permettiamo solo cambio password se non vogliamo complicare troppo il codice.
                # IMPLEMENTAZIONE PARZIALE: Aggiorniamo solo la password se l'username è lo stesso,
                # Se l'username cambia, facciamo la migrazione semplice (senza sessioni per ora per evitare timeout).
                
                # Cancellazione vecchio doc
                user_doc_ref.delete()
                
                self.user_id = new_username
                return {"success": True, "new_username": new_username}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Se cambia solo password
        if new_password:
            updates['password'] = generate_password_hash(new_password)
            try:
                user_doc_ref.update(updates)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        return {"success": True, "message": "Nessuna modifica richiesta"}

    def delete_full_account(self, username):
        """Cancella l'utente e tenta di pulire le sue sessioni."""
        if not self.db: return {"success": False, "error": "DB Offline"}
        
        try:
            user_ref = self.db.collection('users').document(username)
            
            # 1. Cancellazione manuale delle sessioni (Firestore non ha cascade delete automatico)
            # Recupera tutte le sessioni
            sessions = user_ref.collection('sessions').stream()
            for sess in sessions:
                # Recupera canzoni della sessione
                songs = sess.reference.collection('songs').stream()
                for song in songs:
                    song.reference.delete()
                # Cancella sessione
                sess.reference.delete()
            
            # 2. Cancella documento utente
            user_ref.delete()
            
            print(f"🗑️ Account {username} eliminato definitivamente.")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
                        # CASO 1: L'artista rilevato è GIÀ il target (o molto simile)
                        # Dobbiamo segnare il bias come risolto per evitare che
                        # la logica successiva di popolarità lo sovrascriva.
                        if t_norm in a_norm or a_norm in t_norm:
                            print(f"🎯 [Bias] Artista target '{target_artist}' confermato. Skip popolarità.")
                            bias_resolved = True
                        
                        # CASO 2: L'artista è diverso, cerchiamo se il target ha fatto quel brano
                        else:
                            match_info = self.spotify_bot.search_specific_version(clean_title_base, target_artist)
                            if match_info:
                                new_art, new_cov = match_info
                                # Doppio controllo fuzzy per essere sicuri
                                new_art_norm = self._normalize_string(new_art)
                                if t_norm in new_art_norm or new_art_norm in t_norm:
                                    print(f"🔄 [Bias] Trovata versione target: {new_art}")
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

            # --- NUOVO: Aggiorna statistiche utente ---
            self._update_user_personal_stats(title, artist)

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

                if found_composer != "Sconosciuto":
                    self._update_global_stats(found_composer, target_song['title'])

    def get_composer_stats(self, stage_name):
        if not self.db: return {"error": "DB Offline"}
        
        comp_id = self._normalize_string(stage_name).replace(" ", "_")
        doc_ref = self.db.collection('stats_composers').document(comp_id)
        
        doc = doc_ref.get()
        if not doc.exists:
            return {
                "total_plays": 0,
                "top_tracks": [],
                "history": {},
                "display_name": stage_name
            }

        data = doc.to_dict()
        
        tracks_ref = doc_ref.collection('top_tracks').stream()
        tracks = [{"title": t.get("title"), "count": t.get("play_count")} for t in [d.to_dict() for d in tracks_ref]]
        top_5 = sorted(tracks, key=lambda x: x['count'], reverse=True)[:5]

        hist_ref = doc_ref.collection('history').stream()
        history = {d.id: d.to_dict().get("play_count") for d in hist_ref} 

        return {
            "total_plays": data.get("total_plays", 0),
            "top_tracks": top_5,
            "history": history,
            "display_name": data.get("display_name", stage_name)
        }
    
    def recover_last_session(self):
        if not self.db or self.user_id == "demo_user_01":
            return {"success": False, "message": "Funzione non disponibile per ospiti o offline."}

        try:
            sessions_ref = self.user_ref.collection('sessions')
            query = sessions_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(5)
            last_sessions = list(query.stream())

            if not last_sessions:
                return {"success": False, "message": "Nessuna sessione trovata nello storico."}

            found_playlist = []
            target_session_doc = None

            for session_doc in last_sessions:
                songs_ref = session_doc.reference.collection('songs')
                songs_docs = list(songs_ref.stream())
                
                if len(songs_docs) > 0:
                    target_session_doc = session_doc
                    for doc in songs_docs:
                        found_playlist.append(doc.to_dict())
                    break 
            
            if not found_playlist or not target_session_doc:
                return {"success": False, "message": "Trovate sessioni recenti, ma sono tutte vuote."}

            found_playlist.sort(key=lambda x: int(x['id']) if isinstance(x['id'], int) else 0)

            with self.lock:
                self.playlist = found_playlist
                self.known_songs_cache = {
                    f"{s['title']} - {s['artist']}".lower(): s
                    for s in found_playlist
                }
                self.session_ref = target_session_doc.reference

            print(f"♻️ Ripristinata sessione del {target_session_doc.id}: {len(self.playlist)} brani.")
            return {"success": True, "count": len(self.playlist)}

        except Exception as e:
            print(f"❌ Errore recupero sessione: {e}")
            return {"success": False, "message": str(e)}
    
    def get_playlist(self):
        return self.playlist

    def clear_session(self):
        with self.lock:
            self.playlist = []
            self.known_songs_cache = {}
            self._start_new_firestore_session()
            return True

    def _update_global_stats(self, composer_raw, title):
        if not self.db or not composer_raw or composer_raw in ["Sconosciuto", "Pending", "⏳ Ricerca..."]:
            return

        composers = [c.strip() for c in composer_raw.replace("/", ",").split(",") if len(c.strip()) > 2]
        
        month_key = datetime.now().strftime("%Y-%m")

        batch = self.db.batch()
        
        for comp in composers:
            comp_id = self._normalize_string(comp).replace(" ", "_")
            if not comp_id: continue

            comp_ref = self.db.collection('stats_composers').document(comp_id)
            
            batch.set(comp_ref, {
                'display_name': comp,
                'total_plays': firestore.Increment(1),
                'last_updated': firestore.SERVER_TIMESTAMP
            }, merge=True)

            track_ref = comp_ref.collection('top_tracks').document(self._normalize_string(title).replace(" ", "_"))
            batch.set(track_ref, {
                'title': title,
                'play_count': firestore.Increment(1)
            }, merge=True)

            hist_ref = comp_ref.collection('history').document(month_key)
            batch.set(hist_ref, {
                'date': month_key,
                'play_count': firestore.Increment(1)
            }, merge=True)

        try:
            batch.commit()
            print(f"📈 Stats aggiornate per: {composers}")
        except Exception as e:
            print(f"❌ Errore aggiornamento stats: {e}")
    
    def _update_user_personal_stats(self, title, artist):
        """Aggiorna le statistiche aggregate personali dell'utente."""
        if not self.db or self.user_id == "demo_user_01": return

        try:
            batch = self.db.batch()
            
            # 1. Incrementa contatore globale canzoni
            batch.set(self.user_ref, {
                'stats': {'total_songs': firestore.Increment(1)}
            }, merge=True)
            
            # 2. Incrementa contatore brani nella sessione corrente
            if self.session_ref:
                batch.update(self.session_ref, {'song_count': firestore.Increment(1)})

            # 3. Aggiorna Top Tracks Personali (Collection: users/{uid}/stats_tracks/{track_id})
            track_id = self._normalize_string(f"{title} - {artist}").replace(" ", "_")
            track_stats_ref = self.user_ref.collection('stats_tracks').document(track_id)
            
            batch.set(track_stats_ref, {
                'title': title,
                'artist': artist,
                'play_count': firestore.Increment(1),
                'last_played': firestore.SERVER_TIMESTAMP
            }, merge=True)

            batch.commit()
        except Exception as e:
            print(f"⚠️ Errore aggiornamento stats personali: {e}")
    
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

    def get_user_profile_stats(self):
        """Recupera stats, calcolando le sessioni valide dinamicamente."""
        if not self.db or not self.user_ref: 
            return {"total_sessions": 0, "total_songs": 0, "top_artist": "N/D", "top_tracks": []}
        
        try:
            doc_snap = self.user_ref.get()
            if not doc_snap.exists: return {}
            user_doc = doc_snap.to_dict()
            stats = user_doc.get('stats', {})
            
            total_songs = stats.get('total_songs', 0)

            # --- CORREZIONE CONTEGGIO SESSIONI ---
            # Invece di usare il contatore incrementale (che include quelle vuote),
            # contiamo quante sessioni valide ci sono nello storico recente o facciamo una query count
            # Per semplicità e coerenza con la lista, usiamo la lunghezza della history valida
            valid_history = self.get_user_session_history()
            total_sessions_valid = len(valid_history)
            # -------------------------------------
            
            # Recupera Top Tracks
            top_tracks = []
            try:
                tracks_ref = self.user_ref.collection('stats_tracks')\
                    .order_by('play_count', direction=firestore.Query.DESCENDING).limit(5)
                for doc in tracks_ref.stream(): top_tracks.append(doc.to_dict())
            except: pass
            
            top_artist = top_tracks[0]['artist'] if top_tracks else "N/D"

            return {
                "total_sessions": total_sessions_valid, # Usa il numero calcolato pulito
                "total_songs": total_songs,
                "top_artist": top_artist,
                "top_tracks": top_tracks
            }
        except Exception as e:
            print(f"❌ Errore stats: {e}")
            return {}

    def get_user_session_history(self):
        """Recupera le ultime sessioni IGNORANDO quelle vuote (song_count=0)."""
        if not self.db or not self.user_ref: return []
        
        try:
            history = []
            sessions_ref = self.user_ref.collection('sessions')
            
            # Recuperiamo tutto lo stream (limitato a 50 per sicurezza)
            # Non usiamo where('song_count', '>', 0) lato server per evitare problemi di indici mancanti
            sessions = sessions_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(50).stream()
            
            for s in sessions:
                data = s.to_dict()
                s_count = data.get('song_count', 0)
                
                # --- FILTRO: Se la sessione è vuota, la saltiamo ---
                if s_count == 0:
                    continue
                # ---------------------------------------------------

                created = data.get('created_at')
                date_str = "Data sconosciuta"
                
                if created:
                    try:
                        if hasattr(created, 'strftime'):
                            date_str = created.strftime("%d/%m/%Y • %H:%M")
                        elif hasattr(created, 'to_datetime'):
                             date_str = created.to_datetime().strftime("%d/%m/%Y • %H:%M")
                    except: pass
                
                history.append({
                    "id": s.id,
                    "date": date_str,
                    "song_count": s_count,
                    "status": data.get('status', 'closed')
                })
            
            return history
        except Exception as e:
            print(f"❌ Errore fetch history: {e}")
            return []
        

    def get_past_session_songs(self, session_id):
        """Recupera i brani di una sessione specifica archiviata."""
        if not self.db or not self.user_ref: return []
        
        try:
            sess_ref = self.user_ref.collection('sessions').document(session_id)
            songs_ref = sess_ref.collection('songs')
            
            # Recupera i brani
            songs = []
            for doc in songs_ref.stream():
                songs.append(doc.to_dict())
            
            # Ordina per ID o Timestamp
            songs.sort(key=lambda x: int(x.get('id', 0)))
            return songs
        except Exception as e:
            print(f"❌ Errore recupero sessione passata: {e}")
            return []