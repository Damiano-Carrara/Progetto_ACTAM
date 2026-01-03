import os
import time
import hmac
import hashlib
import base64
import json
import requests
import sounddevice as sd
import scipy.io.wavfile as wav
from scipy import signal
import numpy as np
from dotenv import load_dotenv
import threading
import io
import re
import unicodedata
from collections import deque, Counter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor

# --- NUOVO IMPORT ---
from spotify_manager import SpotifyManager

# --- IMPORT DEI MODULI ESTERNI ---
from lyrics_recognition import LyricsRecognizer
from setlist_manager import SetlistManager

load_dotenv()

class AudioManager:
    def __init__(self, callback_function=None):
        # --- 1. CONFIGURAZIONE CREDENZIALI ---
        self.host = os.getenv("ACRCLOUD_HOST") or os.getenv("ACR_HOST")
        self.access_key = os.getenv("ACRCLOUD_ACCESS_KEY") or os.getenv("ACR_ACCESS_KEY")
        self.access_secret = os.getenv("ACRCLOUD_SECRET_KEY") or os.getenv("ACR_ACCESS_SECRET")
        
        # --- 2. CONFIGURAZIONE SESSIONE HTTP ---
        self.session = requests.Session()
        retry_strategy = Retry(
            total=0,
            backoff_factor=0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # --- 3. CONFIGURAZIONE STREAMING AUDIO ---
        self.sample_rate = 44100
        self.window_duration = 12  # Finestra di ascolto
        self.block_size = 4096
        
        # PARAMETRO DINAMICO: Velocità di invio
        # Parte veloce (6s), se la rete soffre rallenta da solo a 10s o più
        self.overlap_interval = 6 

        # Creiamo i buffer
        self.audio_buffer = deque(
            maxlen=int((self.sample_rate * self.window_duration) / self.block_size) + 10
        )
        self.history_buffer = deque(maxlen=10)

        # --- 4. STATO E VARIABILI ---
        self.is_running = False
        self.stream = None
        self.monitor_thread = None
        self.result_callback = callback_function # Callback passato da app.py
        self.target_artist_bias = None
        self.low_quality_mode = False
        self.upload_lock = threading.Lock()
        
        # [MODIFICA 1: SEMAFORO PER APP.PY]
        self.context_ready = False 

        # --- 5. INIZIALIZZAZIONE BOT E MOTORE PARALLELO ---
        print("🤖 Inizializzazione Bot...")
        
        # Executor per il parallelismo (ACR + Whisper + Setlist)
        self.executor = ThreadPoolExecutor(max_workers=3)
        
        # Inizializziamo i manager
        self.setlist_bot = SetlistManager()
        self.lyrics_bot = LyricsRecognizer()
        
        # [MODIFICA 2: SPOTIFY MANAGER]
        self.spotify_bot = SpotifyManager()

        print("🎤 Audio Manager Pronto. Adaptive Mode: ON. Deep Boost: ON.")

    def update_target_artist(self, artist_name):
        """
        STRATEGIA 'TOTAL KNOWLEDGE':
        1. Scarica scaletta storica da Setlist.fm
        2. Scarica Hit + Ultimo Album da Spotify
        3. Unisce tutto in una super-lista di brani probabili
        """
        self.target_artist_bias = artist_name
        # Reset del semaforo: stiamo caricando nuovi dati, quindi non siamo pronti
        self.context_ready = False 
        
        if artist_name:
            def fetch_full_context():
                print(f"\n🎸 [Context] Avvio scansione completa per: {artist_name}")
                
                # 1. SETLIST.FM (Concerti passati)
                songs_setlist = self.setlist_bot.get_likely_songs(artist_name)
                
                # 2. SPOTIFY (Hit + Nuove uscite)
                songs_spotify = self.spotify_bot.get_artist_complete_data(artist_name)
                
                # 3. FUSIONE (Setlist + Spotify)
                # Usiamo un 'set' per rimuovere automaticamente i duplicati
                merged_songs = set(songs_setlist + songs_spotify)
                
                # Salviamo la Super-Lista nel bot delle scalette
                if merged_songs:
                    self.setlist_bot.cached_songs = list(merged_songs)
                    print(f"✅ [Context] White List pronta: {len(merged_songs)} brani unici caricati.")
                    print("-" * 40)
                else:
                    print("⚠️ [Context] Nessun brano trovato su nessuna piattaforma.")
                
                # [MODIFICA 3: SEMAFORO VERDE]
                # Diciamo all'esterno che abbiamo finito di scaricare i titoli
                self.context_ready = True

            # Eseguiamo in background per non bloccare l'app
            self.executor.submit(fetch_full_context)

    def _audio_callback(self, indata, frames, time, status):
        if status:
            if "overflow" not in str(status): # Ignora overflow minori
                print(f"⚠️ Audio Status: {status}")
        self.audio_buffer.append(indata.copy())

    def _preprocess_audio_chunk(self, full_audio_data):
        if full_audio_data.dtype != np.float32:
            data = full_audio_data.astype(np.float32)
        else:
            data = full_audio_data

        # Filtro passa-alto (Toglie ronzii sotto gli 80Hz)
        sos = signal.butter(10, 80, "hp", fs=self.sample_rate, output="sos")
        filtered = signal.sosfilt(sos, data, axis=0)

        max_val = np.max(np.abs(filtered))
        if max_val > 0:
            normalized = filtered / max_val * 0.95
        else:
            normalized = filtered

        return (normalized * 32767).astype(np.int16)

    # --- HELPER FUNCTIONS (MANTENUTE DAL TUO CODICE ORIGINALE) ---
    def _normalize_text(self, text):
        if not text: return ""
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        clean = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live|mixed|spanish|italian)\b.*", "", clean)
        clean = unicodedata.normalize("NFD", clean).encode("ascii", "ignore").decode("utf-8")
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)
        return clean.strip().lower()

    def _normalize_for_match(self, text):
        if not text: return ""
        clean = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("utf-8")
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)
        return clean.strip().lower()

    def _clean_title_for_display(self, text):
        if not text: return ""
        while True:
            cleaned = re.sub(r"\s*[\(\[].*?[\)\]]", "", text)
            if cleaned == text: break
            text = cleaned
        return text.strip("()[] ")

    def _is_mostly_latin(self, text):
        if not text: return False
        try:
            ascii_count = len([c for c in text if ord(c) < 128])
            return (ascii_count / len(text)) > 0.5
        except: return True

    def _get_artist_name(self, track_data):
        if "artist" in track_data: return track_data["artist"]
        if "artists" in track_data and track_data["artists"]: return track_data["artists"][0]["name"]
        return ""

    def _are_tracks_equivalent(self, t1, t2):
        art1 = self._normalize_text(self._get_artist_name(t1))
        art2 = self._normalize_text(self._get_artist_name(t2))

        if art1 != art2 and art1 not in art2 and art2 not in art1:
            return False

        tit1 = self._normalize_text(t1["title"])
        tit2 = self._normalize_text(t2["title"])

        similarity = SequenceMatcher(None, tit1, tit2).ratio()
        if similarity < 0.40: return False
        if similarity > 0.60: return True

        try:
            dur1 = int(t1.get("duration_ms", 0) or 0)
            dur2 = int(t2.get("duration_ms", 0) or 0)
        except (ValueError, TypeError):
            dur1, dur2 = 0, 0

        if dur1 > 30000 and dur2 > 30000:
            if abs(dur1 - dur2) < 1200: return True
        return False

    def _extract_best_cover(self, track_data):
        """
        Strategia Cover HD:
        1. Chiede a Spotify (Priorità Massima - Immagini 640x640)
        2. Fallback su ACRCloud (Se Spotify non trova nulla)
        """
        # [MODIFICA 4: TENTATIVO SPOTIFY HD]
        try:
            if self.spotify_bot:
                title = track_data.get("title")
                artist = self._get_artist_name(track_data)
                hd_cover = self.spotify_bot.get_hd_cover(title, artist)
                if hd_cover:
                    return hd_cover
        except Exception:
            pass

        # 2. FALLBACK STANDARD (Vecchio metodo ACRCloud)
        try:
            spotify = track_data.get("external_metadata", {}).get("spotify", {})
            if "album" in spotify and "images" in spotify["album"]:
                return spotify["album"]["images"][0].get("url")
            
            album = track_data.get("album", {})
            if "covers" in album and album["covers"]:
                return album["covers"][0].get("url")
        except: 
            pass
            
        return None

    def _process_window(self):
        # 1. ACQUISIZIONE LOCK (Non bloccante: se siamo in ritardo, saltiamo)
        if not self.upload_lock.acquire(blocking=False):
            print(f"⏳ Loop veloce: salto finestra (Overlap: {self.overlap_interval}s)")
            return

        try:
            # Controllo Buffer
            if not self.audio_buffer: return
            try:
                full_recording = np.concatenate(list(self.audio_buffer))
            except ValueError: return

            if len(full_recording) < self.sample_rate * (self.window_duration - 1):
                return

            # --- PREPARAZIONE DATI ---
            processed_audio = self._preprocess_audio_chunk(full_recording)
            
            # --- MODALITÀ RETE LENTA (Adaptive) ---
            if self.low_quality_mode:
                # Se la rete soffre, riduciamo il file a 8000Hz (leggerissimo)
                TARGET_RATE = 8000
                num_samples = int(len(processed_audio) * TARGET_RATE / self.sample_rate)
                final_audio = signal.resample(processed_audio, num_samples).astype(np.int16)
                write_rate = TARGET_RATE
                status_msg = f"📡 Analisi [LowQ - {self.overlap_interval}s]..."
            else:
                final_audio = processed_audio
                write_rate = self.sample_rate
                status_msg = f"📡 Analisi [HighQ - {self.overlap_interval}s]..."

            wav_buffer = io.BytesIO()
            wav.write(wav_buffer, write_rate, final_audio)
            wav_buffer.seek(0)

            # Audio per Whisper (Float32 Flat)
            raw_audio_for_whisper = full_recording.flatten().astype(np.float32)

            print(status_msg)

            # --- PARALLELISMO ---
            # 1. ACRCloud parte SEMPRE
            future_acr = self.executor.submit(self._call_acr_api, wav_buffer, self.target_artist_bias)
            
            # 2. Whisper parte SOLO se non siamo in modalità emergenza rete
            future_lyrics = None
            if not self.low_quality_mode:
                future_lyrics = self.executor.submit(
                    self.lyrics_bot.identify, 
                    raw_audio_for_whisper, 
                    self.sample_rate, 
                    self.target_artist_bias # Passiamo l'artista per la cache locale!
                )

            # Raccogliamo i risultati
            acr_result = future_acr.result() 
            lyrics_result = future_lyrics.result() if future_lyrics else None

            # --- LOGICA DI SCELTA (ARBITRO) ---
            final_track = None
            source_used = "none"

            # 1. Analisi ACRCloud
            if acr_result.get("status") == "multiple_results":
                best_acr = acr_result["tracks"][0]
                
                # Se è solido (>75%), vince subito
                # Nota: Il deep boost è già stato applicato in _call_acr_api
                if best_acr["score"] >= 75: 
                    final_track = best_acr
                    source_used = "acr"
                    print(f"🔊 [AUDIO WIN] Match Audio Solido: {best_acr['title']} ({best_acr['score']}%)")
                else:
                    # Incerto? Chiediamo a Whisper
                    if lyrics_result:
                        final_track = lyrics_result
                        source_used = "lyrics"
                        print(f"⚖️ [ARBITRO] Audio incerto ({best_acr['score']}%), vince il TESTO.")
                    else:
                        final_track = best_acr
                        source_used = "acr"
                        print(f"🔊 [AUDIO WIN] Match Audio Debole: {best_acr['title']}")
            
            # 2. Se ACR fallisce, usiamo Whisper
            elif lyrics_result:
                final_track = lyrics_result
                source_used = "lyrics"
                print("\n" + "="*50)
                print(f"🚀 [LYRICS WIN] BRANO RICONOSCIUTO DAL TESTO!")
                frase = final_track.get('metadata', {}).get('snippet', 'N/A')
                if 'snippet' in final_track: frase = final_track['snippet']
                print(f"    🗣️  Frase: \"{frase}\"")
                print("="*50 + "\n")

            # --- INVIO DATI E BOOST SETLIST ---
            if final_track:

                # >>> BOOST SETLIST <<<
                # Se la canzone è nella scaletta scaricata da Setlist.fm, è quasi certamente giusta!
                is_in_setlist = self.setlist_bot.check_is_likely(final_track['title'])
                if is_in_setlist and final_track.get('score', 0) < 100:
                    print(f"🌟 [SETLIST MATCH] '{final_track['title']}' è confermato dalla scaletta!")
                    final_track['score'] = 100 # Fiducia massima

                if source_used == "lyrics":
                    # Formattazione per Lyrics
                    track_data = {
                        "status": "success",
                        "title": final_track['title'],
                        "artist": final_track['artist'],
                        "album": final_track.get('album', 'Sconosciuto'),
                        "score": final_track.get('score', 90),
                        "type": "Lyrics Match",
                        "duration_ms": 0,
                        "external_metadata": {},
                        "contributors": {}
                    }
                    if self.result_callback:
                        self.result_callback(track_data, target_artist=self.target_artist_bias)

                else:
                    # Logica ACRCloud (Latin check, History Buffer, Stability)
                    if not self._is_mostly_latin(final_track["title"]):
                        print(f"🐉 Scartato brano non-Latin: {final_track['title']}")
                        return

                    display_title = self._clean_title_for_display(final_track["title"])
                    current_obj = {
                        "title": final_track["title"],
                        "artist": self._get_artist_name(final_track),
                        "duration_ms": final_track.get("duration_ms", 0),
                    }
                    
                    self.history_buffer.append(current_obj)
                    stability_count = 0
                    for historical_item in self.history_buffer:
                        if self._are_tracks_equivalent(current_obj, historical_item):
                            stability_count += 1

                    if stability_count >= 2:
                        print(f"🛡️ Conferma stabilità ({stability_count}/10): {display_title}")
                        if self.result_callback:
                            final_data = final_track.copy()
                            final_data["title"] = display_title
                            final_data["artist"] = self._get_artist_name(final_track)
                            self.result_callback(final_data, target_artist=self.target_artist_bias)

        except Exception as e:
            print(f"❌ Errore processamento window: {e}")
        finally:
            self.upload_lock.release()

    def _loop_logic(self):
        print("⏱️ Avvio ciclo di monitoraggio dinamico...")
        time.sleep(self.window_duration)
        while self.is_running:
            threading.Thread(target=self._process_window).start()
            # ADAPTIVE RATE: Dorme per un tempo variabile (6s se veloce, 10s se lento)
            time.sleep(self.overlap_interval)

    def start_continuous_recognition(self, callback_function, target_artist=None):
        if self.is_running: return False
        self.is_running = True
        self.result_callback = callback_function
        self.target_artist_bias = target_artist
        self.audio_buffer.clear()
        self.history_buffer.clear()
        self.low_quality_mode = False
        self.overlap_interval = 6 # Reset velocità

        self.stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1,
            blocksize=self.block_size, callback=self._audio_callback,
        )
        self.stream.start()
        self.monitor_thread = threading.Thread(target=self._loop_logic)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        return True

    def stop_continuous_recognition(self):
        self.is_running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
        print("🛑 Monitoraggio Fermato.")
        return True

    # --- CHIAMATA API COMPLETA (CON LOGICA ADATTIVA E AGGREGAZIONE) ---
    def _call_acr_api(self, audio_buffer, bias_artist=None):
        THRESHOLD_MUSIC = 72
        THRESHOLD_HUMMING = 72

        # 1. Preparazione Firma
        http_method = "POST"
        http_uri = "/v1/identify"
        data_type = "audio"
        signature_version = "1"
        timestamp = str(int(time.time()))
        string_to_sign = http_method + "\n" + http_uri + "\n" + self.access_key + "\n" + data_type + "\n" + signature_version + "\n" + timestamp
        sign = base64.b64encode(hmac.new(self.access_secret.encode("ascii"), string_to_sign.encode("ascii"), digestmod=hashlib.sha1).digest()).decode("ascii")

        buffer_content = audio_buffer.getvalue()
        files = {"sample": ("temp.wav", buffer_content, "audio/wav")}
        data = {
            "access_key": self.access_key,
            "sample_bytes": len(buffer_content),
            "timestamp": timestamp,
            "signature": sign,
            "data_type": data_type,
            "signature_version": signature_version,
        }

        start_time = time.time()

        try:
            # Timeout leggermente aumentato (12s) ma gestito dinamicamente
            response = self.session.post(f"https://{self.host}/v1/identify", files=files, data=data, timeout=12)
            elapsed = time.time() - start_time

            # --- LOGICA ADATTIVA (Nuova aggiunta) ---
            # Se l'upload è lento (>4.5s), attiviamo LowQuality e rallentiamo il loop
            if elapsed > 4.5:
                if not self.low_quality_mode:
                    print(f"🐌 Rete lenta ({elapsed:.1f}s) -> Attivo LowQ e Rallento a 10s.")
                    self.low_quality_mode = True
                    self.overlap_interval = 10 
            # Se l'upload è veloce (<2s), torniamo a HighQuality e acceleriamo
            elif elapsed < 2.0:
                if self.low_quality_mode:
                    print(f"🚀 Rete veloce ({elapsed:.1f}s) -> HighQ e Accelero a 6s.")
                    self.low_quality_mode = False
                    self.overlap_interval = 6
            # ----------------------------------------

            result = response.json()
            status_code = result.get("status", {}).get("code")

            if status_code == 0:
                metadata = result.get("metadata", {})
                all_found = []

                def norm(sc):
                    return int(float(sc) * 100) if float(sc) <= 1.0 else int(float(sc))

                # --- MANTENUTA LOGICA AGGREGAZIONE ---
                def aggregate_tracks(raw_list):
                    grouped = []
                    for t in raw_list:
                        t["artist_norm"] = self._normalize_text(self._get_artist_name(t))
                        t["title_norm"] = self._normalize_text(t.get("title"))
                        merged = False
                        for g in grouped:
                            if self._are_tracks_equivalent(t, g):
                                existing_score = norm(g.get("score", 0))
                                new_score = norm(t.get("score", 0))
                                g["score"] = max(existing_score, new_score) + 5
                                print(f"🔗 AGGREGAZIONE: '{t.get('title')}' -> '{g.get('title')}'")
                                merged = True
                                break
                        if not merged: grouped.append(t)
                    return grouped

                def process_section(track_list, threshold, type_label):
                    aggregated_list = aggregate_tracks(track_list)
                    results_count = len(aggregated_list)
                    
                    # Bonus base se c'è un solo risultato (meno confusione = più fiducia)
                    current_bonus_val = 40 if results_count == 1 else 20

                    for t in aggregated_list:
                        raw_score = norm(t.get("score", 0))
                        final_score = raw_score
                        title = t.get("title", "Sconosciuto")
                        artist_name = self._get_artist_name(t)
                        
                        applied_boost_type = "None"
                        boost_amount = 0

                        # === 1. SUPER BOOST SCALETTA (Priorità Massima) ===
                        # Se il titolo è nella White List (Setlist o Spotify), vince quasi sempre.
                        is_in_whitelist = self.setlist_bot.check_is_likely(title)
                        
                        if is_in_whitelist:
                            # AUMENTO DRASTICO: +65%. 
                            # Trasforma un match audio mediocre (40%) in una certezza (105%)
                            # Questo garantisce che superi qualsiasi altro brano con score alto (es. 75%)
                            boost_amount = 65 
                            final_score += boost_amount
                            applied_boost_type = "Whitelist/Setlist"
                        
                        # === 2. BOOST ARTISTA BIAS (Solo se non è già boostato dalla Whitelist) ===
                        elif bias_artist:
                            # Normalizzazione stringhe per confronto
                            bias_norm = self._normalize_for_match(bias_artist)
                            art_norm = self._normalize_for_match(artist_name)
                            
                            # Check rapido
                            is_artist_match = (bias_norm in art_norm) or (art_norm in bias_norm)
                            
                            # Check approfondito (token per token) se quello rapido fallisce
                            if not is_artist_match:
                                bias_tokens = set(bias_norm.split())
                                target_tokens = set(art_norm.split())
                                if bias_tokens.issubset(target_tokens): is_artist_match = True
                            
                            # Check nei metadati esterni (es. Spotify metadata dentro ACR)
                            if not is_artist_match and "external_metadata" in t:
                                ext_dump = json.dumps(t["external_metadata"]).lower()
                                if bias_norm in ext_dump: is_artist_match = True

                            if is_artist_match:
                                # Se l'artista è quello giusto, diamo un bel boost (+40%)
                                # Questo serve per far vincere i brani dell'artista target rispetto a cover sconosciute
                                boost_amount = 40 
                                final_score += boost_amount
                                applied_boost_type = "Artist Match"

                        # === 3. PENALITÀ GENERIC ID ===
                        clean_check = re.sub(r"[\(\[].*?[\)\]]", "", title)
                        clean_check = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|live|mixed|vip)\b.*", "", clean_check)
                        clean_check = re.sub(r"[^a-zA-Z0-9]", "", clean_check).lower().strip()
                        if re.match(r"^(id|track)\d*$", clean_check):
                            penalty = final_score * 0.30 
                            final_score -= penalty
                            print(f"📉 PENALITÀ GENERIC ID: '{title}' -> -30% (Score ridotto)")

                        # === LOG DI DEBUG ===
                        if boost_amount > 0:
                            print(f"🚀 [BOOST {applied_boost_type}] '{title}': {raw_score}% + {boost_amount}% = {final_score}%")

                        # === SOGLIA DI ACCETTAZIONE ===
                        if final_score >= threshold:
                            cover_url = self._extract_best_cover(t)
                            
                            all_found.append({
                                "status": "success", "type": type_label,
                                "title": title, "artist": artist_name,
                                "album": t.get("album", {}).get("name"),
                                "cover": cover_url,
                                "score": final_score, 
                                "duration_ms": t.get("duration_ms"),
                                "external_metadata": t.get("external_metadata", {}),
                                "contributors": t.get("contributors", {}),
                            })
                        else:
                            # print(f"📉 SCARTATO: '{title}' - Score: {final_score}%")
                            pass

                if "music" in metadata: process_section(metadata["music"], THRESHOLD_MUSIC, "Original")
                if "humming" in metadata: process_section(metadata["humming"], THRESHOLD_HUMMING, "Cover/Humming")

                if all_found:
                    all_found.sort(key=lambda x: x["score"], reverse=True)
                    print(f"✅ TROVATO MIGLIORE: {all_found[0]['title']} ({all_found[0]['score']}%)")
                    return {"status": "multiple_results", "tracks": all_found}
                
                print("⚠️ Nessun risultato sopra soglia.")
                return {"status": "not_found"}

            elif status_code == 1001:
                print("🚫 API: Nessuna corrispondenza (Code 1001)")
                return {"status": "not_found"}
            else:
                print(f"❌ API Error Code: {status_code}: {result.get('status', {}).get('msg')}")
                return {"status": "not_found"}

        except Exception as e:
            print(f"❌ Errore rete ACR: {e}")
            # In caso di crash rete, attiviamo subito la modalità sicura
            if not self.low_quality_mode:
                self.low_quality_mode = True
                self.overlap_interval = 10
            return {"status": "error"}