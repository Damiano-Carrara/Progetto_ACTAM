import threading
import time
import re
import unicodedata
from datetime import datetime
from threading import Lock
from metadata_manager import MetadataManager
from spotify_manager import SpotifyManager
from difflib import SequenceMatcher
from firebase_admin import firestore

class SessionManager:
    def __init__(self, db_instance):
        """
        Gestisce la sessione usando Google Firestore.
        Richiede un'istanza 'db' (firestore.client()) passata da app.py.
        """
        self.db = db_instance
        self.playlist = []     # Cache locale per velocità e controlli duplicati
        self.known_songs_cache = {}
        
        # Bot ausiliari
        self.meta_bot = MetadataManager()
        self.spotify_bot = SpotifyManager()
        
        self.lock = Lock()
        
        # --- GESTIONE SESSIONE UTENTE ---
        # In un'app reale, questo ID dovrebbe arrivare dal Login. 
        # Per ora usiamo un utente "demo" fisso o passalo dinamicamente.
        self.user_id = "demo_user_01" 
        
        # Creiamo un ID sessione basato sul timestamp
        session_id = f"session_{int(time.time())}"
        
        # Riferimenti Firestore
        # Struttura: users -> {uid} -> sessions -> {sess_id} -> songs -> {song_id}
        self.user_ref = self.db.collection('users').document(self.user_id)
        self.session_ref = self.user_ref.collection('sessions').document(session_id)
        
        # Inizializza il documento della sessione
        self.session_ref.set({
            'created_at': firestore.SERVER_TIMESTAMP,
            'status': 'live',
            'device': 'python_backend'
        }, merge=True)

        print(f"🔥 Session Manager Connesso a Firestore. Session ID: {session_id}")

    # --- SALVATAGGIO SU FIREBASE ---
    def _save_song_to_db(self, song):
        try:
            # Usiamo l'ID numerico come ID del documento (convertito in stringa)
            doc_ref = self.session_ref.collection('songs').document(str(song['id']))
            doc_ref.set(song)
            print(f"☁️ Salvato su Cloud: {song['title']}")
        except Exception as e:
            print(f"❌ Errore scrittura Firestore: {e}")

    def _update_full_song_in_db(self, song):
        try:
            doc_ref = self.session_ref.collection('songs').document(str(song['id']))
            doc_ref.set(song, merge=True) # merge=True aggiorna solo i campi cambiati
            print(f"🔄 Aggiornato su Cloud: {song['title']}")
        except Exception as e:
            print(f"❌ Errore update Firestore: {e}")

    def _update_single_field(self, song_id, field, value):
        try:
            doc_ref = self.session_ref.collection('songs').document(str(song_id))
            doc_ref.update({field: value})
        except Exception as e:
            print(f"❌ Errore update campo '{field}': {e}")

    def _delete_from_db(self, song_id):
        try:
            self.session_ref.collection('songs').document(str(song_id)).delete()
            print(f"🗑️ Eliminato da Cloud: ID {song_id}")
        except Exception as e:
            print(f"❌ Errore delete Firestore: {e}")

    # --- LOGICA MATCHING (Invariata, usa la cache locale) ---
    def _normalize_string(self, text):
        if not text: return ""
        
        # 1. Rimuovi Branding Piattaforme
        platform_patterns = r"(?i)\b(amazon\s+music|apple\s+music|spotify|deezer|youtube|vevo)\b.*"
        text = re.sub(platform_patterns, "", text)

        # 2. Pulizia standard
        text = re.sub(r"[\(\[].*?[\)\]]", "", text)
        text = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live)\b.*", "", text)
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        
        # CORREZIONE QUI SOTTO: L'input deve essere 'text', non 'clean'
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", text) 
        
        return clean.strip().lower()

    def _are_songs_equivalent(self, new_s, existing_s):
        # Versione ROBUSTA (quella che abbiamo corretto prima)
        tit_new = self._normalize_string(new_s['title'])
        tit_ex = self._normalize_string(existing_s['title'])
        
        if tit_new == tit_ex: return True

        similarity = SequenceMatcher(None, tit_new, tit_ex).ratio()
        
        if similarity > 0.90: return True

        if similarity > 0.80:
            art_new = self._normalize_string(new_s['artist'])
            art_ex = self._normalize_string(existing_s['artist'])
            
            if art_new == art_ex or art_new in art_ex or art_ex in art_new:
                len_diff = abs(len(tit_new) - len(tit_ex))
                if len_diff > 4: return False
                return True
        return False

    def _is_better_match(self, new_artist, old_artist, target_artist):
        if not target_artist: return False
        target_norm = self._normalize_string(target_artist)
        new_norm = self._normalize_string(new_artist)
        old_norm = self._normalize_string(old_artist)
        new_matches = (target_norm in new_norm) or (new_norm in target_norm)
        old_matches = (target_norm in old_norm) or (old_norm in target_norm)
        if new_matches and not old_matches: return True
        return False

    # --- ADD SONG (Logica Core) ---
    def add_song(self, song_data, target_artist=None):
        with self.lock:
            if song_data.get('status') != 'success':
                return {"added": False, "reason": "No match"}
            
            title = song_data['title']
            artist = song_data['artist']
            
            candidate_song = {
                'title': title, 'artist': artist,
                'duration_ms': song_data.get('duration_ms', 0)
            }

            # Check duplicati (su cache locale per velocità)
            for existing_song in self.playlist[-15:]:
                if self._are_songs_equivalent(candidate_song, existing_song):
                    # Smart Upgrade
                    if self._is_better_match(artist, existing_song['artist'], target_artist):
                        print(f"🔄 Smart Upgrade: '{existing_song['artist']}' -> '{artist}'")
                        existing_song.update({
                            'artist': artist,
                            'album': song_data.get('album', existing_song['album']),
                            'score': song_data.get('score', existing_song['score']),
                            'type': song_data.get('type', existing_song['type']),
                            'isrc': song_data.get('isrc'),
                            'upc': song_data.get('upc')
                        })
                        if song_data.get('cover'): existing_song['cover'] = song_data.get('cover')
                        
                        # Aggiorniamo Cloud e Cache
                        self._update_full_song_in_db(existing_song)
                        
                        existing_song['composer'] = "⏳ Aggiornamento..."
                        threading.Thread(target=self._background_enrichment, args=(existing_song, target_artist), daemon=True).start()
                        return {"added": True, "updated": True, "song": existing_song}
                    
                    return {"added": False, "reason": "Duplicate", "song": existing_song}

            # Nuovo Inserimento
            track_key = f"{title} - {artist}".lower()
            cached_entry = self.known_songs_cache.get(track_key)
            
            # Calcolo ID progressivo (basato su lunghezza playlist locale attuale)
            next_id = len(self.playlist) + 1
            
            if cached_entry:
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
                "id": next_id, 
                "title": title,
                "artist": artist, 
                "composer": composer_name,     
                "album": song_data.get('album', 'Sconosciuto'),
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "duration_ms": song_data.get('duration_ms', 0),
                "score": song_data.get('score', 0),
                "type": song_data.get('type', 'Original'),
                "isrc": isrc, "upc": upc, "cover": cover_url,
                "_raw_isrc": isrc, "_raw_upc": upc, "_raw_meta": raw_meta_package,
                "confirmed": True # Default true per visualizzazione
            }

            self.playlist.append(new_entry)
            self._save_song_to_db(new_entry)

            if status_enrichment == "Pending":
                threading.Thread(target=self._background_enrichment, args=(new_entry, target_artist), daemon=True).start()

            print(f"✅ Aggiunto: {title}")
            return {"added": True, "song": new_entry}

    # --- THREAD DI ARRICCHIMENTO ---
    def _background_enrichment(self, entry, target_artist):
        attempts = 0
        max_attempts = 3
        found_composer = "Sconosciuto"
        final_cover = entry.get('cover') 
        success = False

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
                if not final_cover and cover_fallback: final_cover = cover_fallback
                success = True
                break 
            except:
                attempts += 1
                time.sleep(1)

        # 3. SALVATAGGIO FINALE SU CLOUD
        with self.lock:
            # Aggiorniamo la copia locale
            target_song = next((s for s in self.playlist if s['id'] == entry['id']), None)
            
            if target_song:
                target_song['composer'] = found_composer
                self._update_single_field(target_song['id'], 'composer', found_composer)
                
                if final_cover and final_cover != target_song.get('cover'):
                    target_song['cover'] = final_cover
                    self._update_single_field(target_song['id'], 'cover', final_cover)

                if success and found_composer not in ["Sconosciuto", "Errore Conn."]:
                    track_key = f"{target_song['title']} - {target_song['artist']}".lower()
                    self.known_songs_cache[track_key] = target_song.copy()

    # --- METODI UTILITY ---
    def get_playlist(self):
        return self.playlist

    def clear_session(self):
        with self.lock:
            self.playlist = []
            self.known_songs_cache = {}
            # Nota: Su Firestore cancellare intere collezioni non è banale.
            # Per ora resettiamo solo la lista locale e cambiamo Session ID al prossimo riavvio.
            return True

    def delete_song(self, song_id):
        with self.lock:
            try:
                song_id = int(song_id)
                self.playlist = [s for s in self.playlist if s['id'] != song_id]
                self._delete_from_db(song_id)
                return True
            except ValueError: return False