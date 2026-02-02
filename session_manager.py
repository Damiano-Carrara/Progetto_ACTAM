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

        # 2. Pulizia Parentesi (Tonde, Quadre, Graffe)
        # Questo rimuove già cose come "(Live)" o "[Live 2024]"
        text = re.sub(r"[\(\[\{].*?[\)\]\}]", "", text)

        # 3. GESTIONE INTELLIGENTE "LIVE" (Il Fix per i Queen)
        # Invece di tagliare ogni "live", tagliamo solo "Live at/in/from" o " - Live"
        text = re.sub(r"(?i)\b(live\s+(at|in|from|on))\b.*", "", text) # Es. "Live at Wembley"
        text = re.sub(r"(?i)\s-\s.*live.*", "", text)                 # Es. "Titolo - Live Version"

        # 4. Pulizia "Sporcizia" generica (RIMOSSO "live" da qui)
        # Nota: ho tolto 'live' dalla lista qui sotto per proteggere "Who Wants to Live Forever"
        junk_patterns = r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|performed by|originally by|aus|from|theme)\b.*"
        text = re.sub(junk_patterns, "", text)

        # 5. Normalizzazione Unicode
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        
        # 6. Rimozione caratteri non alfanumerici
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", text) 
        
        return clean.strip().lower()

    def _are_songs_equivalent(self, new_s, existing_s):
        # 1. Normalizzazione stringhe
        tit_new = self._normalize_string(new_s['title'])
        tit_ex = self._normalize_string(existing_s['title'])
        art_new = self._normalize_string(new_s['artist'])
        art_ex = self._normalize_string(existing_s['artist'])
        
        # Calcoliamo la somiglianza del titolo
        title_similarity = SequenceMatcher(None, tit_new, tit_ex).ratio()
        
        # --- FIX: IL TITOLO DA SOLO NON BASTA ---
        # Se i titoli sono identici (o molto simili), dobbiamo PER FORZA controllare l'artista
        if title_similarity > 0.90:
            # Caso 1: Artisti identici o uno contenuto nell'altro (es. "Queen" vs "Queen & Bowie")
            if art_new == art_ex or art_new in art_ex or art_ex in art_new:
                return True
            
            # Caso 2: Artisti simili (es. "Guns N Roses" vs "Guns N' Roses")
            art_similarity = SequenceMatcher(None, art_new, art_ex).ratio()
            if art_similarity > 0.60: # Soglia tollerante per l'artista
                return True
            
            # Se siamo qui, i titoli sono uguali ma gli artisti sono DIVERSI.
            # Esempio: "Photograph" (Sheeran) vs "Photograph" (Def Leppard) -> RETURN FALSE
            return False

        # --- LOGICA FUZZY PER TITOLI LEGGERMENTE DIVERSI ---
        # Se il titolo è simile (es. > 80% ma < 90%), richiediamo una corrispondenza artista più forte
        if title_similarity > 0.80:
            if art_new == art_ex or art_new in art_ex or art_ex in art_new:
                # Controllo extra: evitiamo falsi positivi se i titoli differiscono molto in lunghezza
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
                'title': title, 
                'artist': artist,
                'duration_ms': song_data.get('duration_ms', 0),
                'cover': song_data.get('cover')
            }

            # === [LOGICA A CASCATA: BIAS -> POPOLARITÀ] ===
            if self.spotify_bot:
                try:
                    # Pulizia preliminare del titolo
                    clean_title_base = re.sub(r"[\(\[].*?[\)\]]", "", title).strip()
                    clean_title_base = re.sub(r"(?i)\b(live\s+(at|in|from|on))\b.*", "", clean_title_base)
                    clean_title_base = re.sub(r"(?i)\s-\s.*live.*", "", clean_title_base)
                    clean_title_base = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version)\b.*", "", clean_title_base).strip()

                    # Flag per capire se abbiamo risolto con il Bias
                    bias_resolved = False

                    # --- STEP 1: TENTATIVO BIAS ARTIST (Es. Beatles) ---
                    if target_artist:
                        t_norm = self._normalize_string(target_artist)
                        a_norm = self._normalize_string(artist)
                        
                        # Se l'artista rilevato NON è già il target
                        if t_norm not in a_norm and a_norm not in t_norm:
                            print(f"🕵️ Bias Attivo: Controllo se '{clean_title_base}' è di {target_artist}...")
                            match_info = self.spotify_bot.search_specific_version(clean_title_base, target_artist)
                            
                            if match_info:
                                new_art, new_cov = match_info
                                
                                # === FIX CRUCIALE: VALIDAZIONE NOME ARTISTA ===
                                # Se Spotify ci restituisce "David Arnold" cercando "The Beatles",
                                # dobbiamo RIFIUTARE lo swap e passare allo Step 2.
                                new_art_norm = self._normalize_string(new_art)
                                
                                # Controllo permissivo: 'thebeatles' è contenuto in 'new_art'?
                                # Oppure 'new_art' è contenuto in 'thebeatles'?
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
                                    # Qui intercettiamo il "Falso Positivo" (es. Tribute Band, David Arnold, ecc.)
                                    print(f"⚠️ [Bias Reject] Spotify ha proposto '{new_art}' ma cercavo '{target_artist}'. Passo al Fallback.")
                                    bias_resolved = False 
                        else:
                            # L'artista rilevato era già quello giusto
                            bias_resolved = True

                    # --- STEP 2: FALLBACK POPOLARITÀ (Es. John Lennon) ---
                    # Eseguiamo questo solo se il Bias NON ha risolto nulla
                    if not bias_resolved:
                        # Cerchiamo se esiste una versione "originale" molto più famosa
                        # (Utile per Imagine suonata da una tribute band dei Beatles)
                        better_version = self.spotify_bot.get_most_popular_version(title, artist)
                        
                        if better_version:
                            new_artist, new_cover, popularity = better_version
                            print(f"🚀 [Pop Swap] Fallback: {artist} -> {new_artist} (Pop: {popularity})")
                            
                            artist = new_artist
                            candidate_song['artist'] = new_artist
                            candidate_song['original_artist'] = new_artist # Traccia per debug
                            candidate_song['title'] = clean_title_base 
                            title = clean_title_base

                            if new_cover:
                                candidate_song['cover'] = new_cover
                                song_data['cover'] = new_cover 
                            
                except Exception as e:
                    print(f"⚠️ Errore Smart Fix Cascata: {e}")
            # ====================================================

            # Check duplicati (Invariato)
            for existing_song in self.playlist[-15:]:
                if self._are_songs_equivalent(candidate_song, existing_song):
                    print(f"🔄 Duplicato rilevato (Smart): {candidate_song['title']} - {candidate_song['artist']}")
                    return {"added": False, "reason": "Duplicate", "song": existing_song}

            # ... (Resto del codice invariato fino alla fine) ...
            
            # Nuovo Inserimento
            track_key = f"{title} - {artist}".lower()
            cached_entry = self.known_songs_cache.get(track_key)
            
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
                "confirmed": True 
            }

            self.playlist.append(new_entry)
            self._save_song_to_db(new_entry)

            if status_enrichment == "Pending":
                threading.Thread(target=self._background_enrichment, args=(new_entry, target_artist), daemon=True).start()

            print(f"✅ Aggiunto: {title} - {artist}")
            return {"added": True, "song": new_entry}

    # --- THREAD DI ARRICCHIMENTO ---
    def _background_enrichment(self, entry, target_artist):
        attempts = 0
        max_attempts = 3
        found_composer = "Sconosciuto"
        final_cover = entry.get('cover') 
        success = False

        # (RIMOSSO STEP 0: SMART FIX - ORA È IN ADD_SONG)

        # 1. SPOTIFY HD (Se non l'abbiamo già trovata sopra)
        if self.spotify_bot and not final_cover:
            try:
                hd_cover = self.spotify_bot.get_hd_cover(entry['title'], entry['artist'])
                if hd_cover: final_cover = hd_cover
            except: pass

        # 2. RICERCA COMPOSITORE (Ora userà l'artista "famoso" se è stato sostituito!)
        while attempts < max_attempts:
            try:
                comp_result, cover_fallback = self.meta_bot.find_composer(
                    title=entry['title'], 
                    detected_artist=entry['artist'], # Qui ora passa l'artista corretto!
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
            target_song = next((s for s in self.playlist if s['id'] == entry['id']), None)
            
            if target_song:
                # --- MODIFICA INIZIA QUI ---
                # Se abbiamo trovato un compositore, spesso i motori ci hanno dato anche info sull'album
                # (nota: richiederebbe che MetadataManager ritorni anche l'album, ma per ora fixiamo almeno il salvataggio)
                
                # Aggiorniamo il compositore
                target_song['composer'] = found_composer
                self._update_single_field(target_song['id'], 'composer', found_composer)
                
                # Aggiorniamo la cover
                if final_cover and final_cover != target_song.get('cover'):
                    target_song['cover'] = final_cover
                    self._update_single_field(target_song['id'], 'cover', final_cover)
                
                # FIX SUGGERITO: Se l'album è sconosciuto ma abbiamo trovato dati su Spotify/iTunes,
                # dovremmo idealmente aggiornarlo.
                # Per ora, assicurati che la struttura dati sia coerente.

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