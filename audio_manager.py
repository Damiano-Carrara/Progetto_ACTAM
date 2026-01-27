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

# --- IMPORT DEI MODULI INTERNI ---
from spotify_manager import SpotifyManager
from setlist_manager import SetlistManager
from lyrics_manager import LyricsManager 

load_dotenv()

class AudioManager:
    def __init__(self, callback_function=None):
        """
        Inizializza il gestore audio, i buffer e i bot ausiliari.
        """
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
        self.window_duration = 12  
        self.block_size = 4096
        
        self.overlap_interval = 6 

        self.audio_buffer = deque(
            maxlen=int((self.sample_rate * self.window_duration) / self.block_size) + 10
        )
        self.history_buffer = deque(maxlen=10)

        # --- 4. STATO E VARIABILI ---
        self.is_running = False
        self.stream = None
        self.monitor_thread = None
        self.result_callback = callback_function 
        self.target_artist_bias = None
        self.low_quality_mode = False
        self.upload_lock = threading.Lock()
        
        self.context_ready = False 

        self.predicted_next_song = None
        
        # Variabili per Scribe
        self.cycle_counter = 0 

        # --- 5. INIZIALIZZAZIONE BOT ---
        print("🤖 Inizializzazione Bot...")
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        self.setlist_bot = SetlistManager()
        self.spotify_bot = SpotifyManager()
        self.lyrics_bot = LyricsManager()

        print("🎤 Audio Manager Pronto. (ACRCloud + Scribe v2 Integrated).")

    def update_target_artist(self, artist_name):
        """
        Scarica il contesto completo e i TESTI per l'artista target.
        """
        self.target_artist_bias = artist_name
        self.context_ready = False 
        
        if artist_name:
            def fetch_full_context():
                print(f"\n🎸 [Context] Avvio scansione completa per: {artist_name}")
                
                # 1. SETLIST.FM
                songs_setlist = self.setlist_bot.get_likely_songs(artist_name)
                
                # 2. SPOTIFY
                songs_spotify = self.spotify_bot.get_artist_complete_data(artist_name)
                
                # 3. FUSIONE WHITE LIST
                merged_songs = set(songs_setlist + songs_spotify)
                if merged_songs:
                    self.setlist_bot.cached_songs = list(merged_songs)
                    print(f"✅ [Context] White List pronta: {len(merged_songs)} brani.")
                
                # 4. SCARICA TESTI PER CONFRONTO LOCALE
                self.lyrics_bot.update_artist_context(artist_name)
                
                self.context_ready = True

            self.executor.submit(fetch_full_context)

    def _audio_callback(self, indata, frames, time, status):
        """Callback di SoundDevice"""
        if status and "overflow" not in str(status):
            print(f"⚠️ Audio Status: {status}")
        self.audio_buffer.append(indata.copy())

    def _preprocess_audio_chunk(self, full_audio_data):
        """Normalizza e filtra l'audio"""
        if full_audio_data.dtype != np.float32:
            data = full_audio_data.astype(np.float32)
        else:
            data = full_audio_data

        sos = signal.butter(10, 80, "hp", fs=self.sample_rate, output="sos")
        filtered = signal.sosfilt(sos, data, axis=0)

        max_val = np.max(np.abs(filtered))
        if max_val > 0:
            normalized = filtered / max_val * 0.95
        else:
            normalized = filtered

        return (normalized * 32767).astype(np.int16)

    # --- HELPER FUNCTIONS ---
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
        tit1 = self._normalize_text(t1["title"])
        tit2 = self._normalize_text(t2["title"])
        similarity = SequenceMatcher(None, tit1, tit2).ratio()
        
        if similarity > 0.90: return True
        art1 = self._normalize_text(self._get_artist_name(t1))
        art2 = self._normalize_text(self._get_artist_name(t2))
        if similarity > 0.60:
            if art1 == art2 or art1 in art2 or art2 in art1: return True
        return False

    def _extract_best_cover(self, track_data):
        try:
            if self.spotify_bot:
                title = track_data.get("title")
                artist = self._get_artist_name(track_data)
                hd_cover = self.spotify_bot.get_hd_cover(title, artist)
                if hd_cover: return hd_cover
        except: pass
        try:
            spotify = track_data.get("external_metadata", {}).get("spotify", {})
            if "album" in spotify and "images" in spotify["album"]:
                return spotify["album"]["images"][0].get("url")
            album = track_data.get("album", {})
            if "covers" in album and album["covers"]:
                return album["covers"][0].get("url")
        except: pass
        return None

    def _process_window(self):
        if not self.upload_lock.acquire(blocking=False):
            print(f"⏳ Loop veloce: salto finestra (Overlap: {self.overlap_interval}s)")
            return

        try:
            if not self.audio_buffer: return
            try:
                full_recording = np.concatenate(list(self.audio_buffer))
            except ValueError: return

            if len(full_recording) < self.sample_rate * (self.window_duration - 1):
                return

            processed_audio = self._preprocess_audio_chunk(full_recording)
            
            if self.low_quality_mode:
                TARGET_RATE = 8000
                num_samples = int(len(processed_audio) * TARGET_RATE / self.sample_rate)
                final_audio = signal.resample(processed_audio, num_samples).astype(np.int16)
                write_rate = TARGET_RATE
            else:
                final_audio = processed_audio
                write_rate = self.sample_rate

            wav_buffer = io.BytesIO()
            wav.write(wav_buffer, write_rate, final_audio)
            wav_buffer.seek(0)

            # --- LOGICA PARALLELA ---
            self.cycle_counter += 1
            run_scribe = (self.target_artist_bias is not None) and (self.cycle_counter % 3 == 0)

            status_msg = f"📡 Analisi [ACR"
            if run_scribe: status_msg += " + SCRIBE"
            status_msg += f"] ({self.overlap_interval}s)..."
            print(status_msg)

            future_acr = self.executor.submit(self._call_acr_api, wav_buffer, self.target_artist_bias)
            future_scribe = None
            if run_scribe:
                scribe_buffer = io.BytesIO(wav_buffer.getvalue())
                future_scribe = self.executor.submit(self.lyrics_bot.transcribe_and_match, scribe_buffer)

            # Risultati
            acr_result = future_acr.result() 
            scribe_result = future_scribe.result() if future_scribe else None
            
            final_track = None
            is_fast_track = False 
            
            # Recupero miglior candidato ACR
            acr_best = None
            acr_score = 0
            is_acr_bias = False
            
            if acr_result.get("status") == "multiple_results":
                acr_best = acr_result["tracks"][0]
                acr_score = acr_best.get("score", 0)
                # Verifica se ACR ha trovato l'artista bias
                if self.target_artist_bias:
                    bias_norm = self._normalize_for_match(self.target_artist_bias)
                    found_art = self._normalize_for_match(self._get_artist_name(acr_best))
                    if bias_norm in found_art or found_art in bias_norm:
                        is_acr_bias = True

            scribe_score = scribe_result.get("score", 0) if scribe_result else 0

            # ========================================================
            # LOGICA DI ARBITRAGGIO PROTETTA
            # ========================================================

            # 1. FAST TRACK (Conferma Reciproca)
            if scribe_result and acr_best:
                if scribe_score > 75 and acr_score > 98:
                    if self._are_tracks_equivalent(scribe_result, acr_best):
                        print(f"⚡ [FAST TRACK] Match Assoluto! Scribe ({scribe_score}%) + ACR ({acr_score}%)")
                        final_track = scribe_result
                        final_track["external_metadata"] = acr_best.get("external_metadata")
                        final_track["cover"] = acr_best.get("cover")
                        is_fast_track = True

            # 2. VALUTAZIONE SCRIBE vs ACR
            if not final_track and scribe_result:
                
                # Caso A: Scribe è altissimo (>85%). Vince quasi sempre.
                if scribe_score > 85:
                     print(f"🥇 [SCRIBE WIN] Testo Dominante: {scribe_result['title']} ({scribe_score}%)")
                     final_track = scribe_result
                
                # Caso B: Scribe è buono (>65%), MA bisogna controllare ACR
                elif scribe_score > 65:
                    
                    # PROTEZIONE: Se ACR è forte (>80%) E Bias -> VINCE ACR (Non sovrascrivere!)
                    if acr_best and acr_score > 80 and is_acr_bias:
                         print(f"🛡️ [ACR PROTECTED] Scribe buono ({scribe_score}%) ma ACR solido sul Bias ({acr_score}%). Tengo ACR.")
                         final_track = acr_best
                         # (Non è fast track, passa per la stabilità)
                    
                    # Se invece ACR è debole o ha sbagliato artista -> VINCE SCRIBE
                    else:
                        print(f"🥇 [SCRIBE WIN] Scribe ({scribe_score}%) meglio di ACR incerto.")
                        final_track = scribe_result
                        if acr_best and self._are_tracks_equivalent(scribe_result, acr_best):
                            final_track["external_metadata"] = acr_best.get("external_metadata")
                            final_track["cover"] = acr_best.get("cover")

            # 3. ACR FALLBACK (Se Scribe non ha vinto o non c'era)
            if not final_track and acr_best:
                if not scribe_result or scribe_score <= 65:
                     # Log solo se non abbiamo già stampato sopra
                     print(f"🔊 [ACR WIN] Match Audio Standard: {acr_best['title']} ({acr_score}%)")
                     final_track = acr_best

            # --- INVIO DATI E STABILITÀ ---
            if final_track:
                if not self._is_mostly_latin(final_track["title"]):
                    return

                display_title = self._clean_title_for_display(final_track["title"])
                
                if is_fast_track:
                     if self.result_callback:
                        final_data = final_track.copy()
                        final_data["title"] = display_title
                        final_data["artist"] = self._get_artist_name(final_track)
                        if not final_data.get("cover"):
                             final_data["cover"] = self._extract_best_cover(final_data)
                        self.result_callback(final_data, target_artist=self.target_artist_bias)
                        self.history_buffer.clear()
                        return

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
                
                is_from_scribe = final_track.get("type") == "Lyrics Match"
                threshold = 1 if is_from_scribe else 2

                if stability_count >= threshold:
                    print(f"🛡️ Conferma ({stability_count}/{threshold}): {display_title}")
                    if self.result_callback:
                        final_data = final_track.copy()
                        final_data["title"] = display_title
                        final_data["artist"] = self._get_artist_name(final_track)
                        if not final_data.get("cover"):
                             final_data["cover"] = self._extract_best_cover(final_data)

                        self.result_callback(final_data, target_artist=self.target_artist_bias)
                        
                        clean_title_pred = self._clean_title_for_display(final_track['title'])
                        next_prediction = self.setlist_bot.predict_next(clean_title_pred)
                        if next_prediction:
                            self.predicted_next_song = next_prediction
                        else:
                            self.predicted_next_song = None
                            
        except Exception as e:
            print(f"❌ Errore processamento window: {e}")
        finally:
            self.upload_lock.release()

    def _loop_logic(self):
        print("⏱️ Avvio ciclo di monitoraggio dinamico...")
        time.sleep(self.window_duration)
        while self.is_running:
            threading.Thread(target=self._process_window).start()
            time.sleep(self.overlap_interval)

    def start_continuous_recognition(self, callback_function, target_artist=None):
        if self.is_running: return False
        self.is_running = True
        self.result_callback = callback_function
        self.target_artist_bias = target_artist
        self.audio_buffer.clear()
        self.history_buffer.clear()
        self.low_quality_mode = False
        self.overlap_interval = 6
        self.cycle_counter = 0

        self.stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1,
            blocksize=self.block_size, callback=self._audio_callback,
        )
        self.stream.start()
        self.monitor_thread = threading.Thread(target=self._loop_logic)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        if target_artist:
            self.update_target_artist(target_artist)
            
        return True

    def stop_continuous_recognition(self):
        self.is_running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
        print("🛑 Monitoraggio Fermato.")
        return True

    # --- CHIAMATA API ACRCLOUD (Invariata) ---
    def _call_acr_api(self, audio_buffer, bias_artist=None):
        THRESHOLD_MUSIC = 72
        THRESHOLD_HUMMING = 72

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
            response = self.session.post(f"https://{self.host}/v1/identify", files=files, data=data, timeout=12)
            elapsed = time.time() - start_time

            if elapsed > 4.5:
                if not self.low_quality_mode:
                    print(f"🐌 Rete lenta ({elapsed:.1f}s) -> Attivo LowQ e Rallento a 10s.")
                    self.low_quality_mode = True
                    self.overlap_interval = 10 
            elif elapsed < 2.0:
                if self.low_quality_mode:
                    print(f"🚀 Rete veloce ({elapsed:.1f}s) -> HighQ e Accelero a 6s.")
                    self.low_quality_mode = False
                    self.overlap_interval = 6

            result = response.json()
            status_code = result.get("status", {}).get("code")

            if status_code == 0:
                metadata = result.get("metadata", {})
                all_found = []

                def norm(sc):
                    return int(float(sc) * 100) if float(sc) <= 1.0 else int(float(sc))

                def aggregate_tracks(raw_list):
                    grouped = []
                    for t in raw_list:
                        merged = False
                        for g in grouped:
                            if self._are_tracks_equivalent(t, g):
                                existing_score = norm(g.get("score", 0))
                                new_score = norm(t.get("score", 0))
                                g["score"] = max(existing_score, new_score) + 5
                                merged = True
                                break
                        if not merged: grouped.append(t)
                    return grouped

                def process_section(track_list, threshold, type_label):
                    aggregated_list = aggregate_tracks(track_list)
                    
                    for t in aggregated_list:
                        raw_score = norm(t.get("score", 0))
                        final_score = raw_score
                        title = t.get("title", "Sconosciuto")
                        
                        artist_names_found = set()
                        main_artist = self._get_artist_name(t)
                        if main_artist: artist_names_found.add(main_artist)
                        
                        if "external_metadata" in t:
                            for provider in t["external_metadata"].values():
                                if isinstance(provider, dict):
                                    if "artists" in provider:
                                        for art in provider["artists"]:
                                            if "name" in art: artist_names_found.add(art["name"])
                                    if "channel_title" in provider:
                                        artist_names_found.add(provider["channel_title"])

                        display_artist = main_artist if main_artist else "Sconosciuto"
                        applied_boost_type = "None"
                        boost_amount = 0

                        # BOOSTS
                        is_in_whitelist = self.setlist_bot.check_is_likely(title)
                        
                        if is_in_whitelist:
                            boost_amount = 65 
                            final_score += boost_amount
                            applied_boost_type = "Whitelist/Setlist"
                        
                        elif bias_artist:
                            bias_norm = self._normalize_for_match(bias_artist)
                            is_artist_match = False
                            for found_art in artist_names_found:
                                art_norm = self._normalize_for_match(found_art)
                                if len(art_norm) < 2: continue 
                                if (bias_norm in art_norm) or (art_norm in bias_norm):
                                    is_artist_match = True
                                    break
                                bias_tokens = set(bias_norm.split())
                                target_tokens = set(art_norm.split())
                                if bias_tokens and target_tokens and bias_tokens.issubset(target_tokens):
                                    is_artist_match = True
                                    break
                            
                            if is_artist_match:
                                boost_amount = 50 
                                final_score += boost_amount
                                applied_boost_type = "Artist Match"

                        if self.predicted_next_song:
                            pred_ratio = SequenceMatcher(None, title.lower(), self.predicted_next_song.lower()).ratio()
                            if pred_ratio > 0.85:
                                boost_amount = 80 
                                final_score += boost_amount
                                applied_boost_type = f"PREDICTION ({self.predicted_next_song})"

                        clean_check = re.sub(r"[\(\[].*?[\)\]]", "", title)
                        clean_check = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|live|mixed|vip)\b.*", "", clean_check)
                        clean_check = re.sub(r"[^a-zA-Z0-9]", "", clean_check).lower().strip()
                        
                        if re.match(r"^(id|track)\d*$", clean_check):
                            penalty = final_score * 0.30 
                            final_score -= penalty

                        if boost_amount > 0:
                            print(f"🚀 [BOOST {applied_boost_type}] '{title}': {raw_score}% + {boost_amount}% = {final_score}%")

                        if final_score >= threshold:
                            cover_url = self._extract_best_cover(t)
                            all_found.append({
                                "status": "success", "type": type_label,
                                "title": title, 
                                "artist": display_artist,
                                "album": t.get("album", {}).get("name"),
                                "cover": cover_url,
                                "score": final_score, 
                                "duration_ms": t.get("duration_ms"),
                                "external_metadata": t.get("external_metadata", {}),
                                "contributors": t.get("contributors", {}),
                            })

                if "music" in metadata: process_section(metadata["music"], THRESHOLD_MUSIC, "Original")
                if "humming" in metadata: process_section(metadata["humming"], THRESHOLD_HUMMING, "Cover/Humming")

                if all_found:
                    all_found.sort(key=lambda x: x["score"], reverse=True)
                    return {"status": "multiple_results", "tracks": all_found}
                
                return {"status": "not_found"}

            elif status_code == 1001:
                return {"status": "not_found"}
            else:
                print(f"❌ API Error Code: {status_code}: {result.get('status', {}).get('msg')}")
                return {"status": "not_found"}

        except Exception as e:
            print(f"❌ Errore rete ACR: {e}")
            if not self.low_quality_mode:
                self.low_quality_mode = True
                self.overlap_interval = 10
            return {"status": "error"}

if __name__ == "__main__":
    print("🔧 Avvio test manuale AudioManager...")
    def dummy_callback(data, target_artist=None):
        print(f"📨 CALLBACK: {data['title']} - Score: {data['score']}")

    bot = AudioManager(callback_function=dummy_callback)
    bot.start_continuous_recognition(dummy_callback, target_artist="Vasco Rossi")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        bot.stop_continuous_recognition()