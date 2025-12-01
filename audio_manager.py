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
from collections import deque, Counter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry 

load_dotenv()

class AudioManager:
    def __init__(self):
        self.host = os.getenv('ACR_HOST')
        self.access_key = os.getenv('ACR_ACCESS_KEY')
        self.access_secret = os.getenv('ACR_ACCESS_SECRET')

        # --- CONFIGURAZIONE SESSIONE HTTP ---
        self.session = requests.Session()
        # NESSUN RETRY: Se fallisce, fallisce subito per passare a LowQ
        retry_strategy = Retry(
            total=0,
            backoff_factor=0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # --- CONFIGURAZIONE STREAMING ---
        self.sample_rate = 44100
        self.window_duration = 12 
        self.overlap_interval = 6 
        self.block_size = 4096
        self.audio_buffer = deque(maxlen=int((self.sample_rate * self.window_duration) / self.block_size) + 5)
        self.history_buffer = deque(maxlen=10) 
        
        self.is_running = False
        self.stream = None
        self.monitor_thread = None
        self.result_callback = None 
        self.target_artist_bias = None

        # --- GESTIONE QUALITÀ DINAMICA ---
        self.low_quality_mode = False 
        self.upload_lock = threading.Lock() 

        print(f"🎤 Audio Manager Pronto. Timeout: 10s | Super-Bias: ATTIVO (+30pt)")

    def _audio_callback(self, indata, frames, time, status):
        if status:
            print(f"⚠️ Audio Status: {status}")
        self.audio_buffer.append(indata.copy())

    def _preprocess_audio_chunk(self, full_audio_data):
        if full_audio_data.dtype != np.float32:
            data = full_audio_data.astype(np.float32)
        else:
            data = full_audio_data

        sos = signal.butter(10, 80, 'hp', fs=self.sample_rate, output='sos')
        filtered = signal.sosfilt(sos, data, axis=0)

        max_val = np.max(np.abs(filtered))
        if max_val > 0:
            normalized = filtered / max_val * 0.95
        else:
            normalized = filtered

        return (normalized * 32767).astype(np.int16)

    def _normalize_text(self, text):
        if not text: return ""
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        clean = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live|mixed)\b.*", "", clean)
        # Pulizia aggressiva per raggruppare i duplicati
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)
        return clean.strip().lower()

    def _clean_title_for_display(self, text):
        if not text: return ""
        while True:
            cleaned = re.sub(r"\s*[\(\[].*?[\)\]]", "", text)
            if cleaned == text:
                break
            text = cleaned
        text = text.strip("()[] ")
        return text.strip()

    def _is_mostly_latin(self, text):
        if not text: return False
        try:
            ascii_count = len([c for c in text if ord(c) < 128])
            return (ascii_count / len(text)) > 0.8
        except:
            return True

    def _process_window(self):
        # 1. CONTROLLO ANTI-INGORGO
        if not self.upload_lock.acquire(blocking=False):
            print("⏳ Rete lenta: Salto finestra.")
            return

        try:
            if not self.audio_buffer: return

            try:
                full_recording = np.concatenate(list(self.audio_buffer))
            except ValueError: return 

            if len(full_recording) < self.sample_rate * (self.window_duration - 1): return 

            processed_audio = self._preprocess_audio_chunk(full_recording)
            
            # --- 2. LOGICA QUALITÀ ADATTIVA ---
            if self.low_quality_mode:
                TARGET_RATE = 8000
                num_samples = int(len(processed_audio) * TARGET_RATE / self.sample_rate)
                final_audio = signal.resample(processed_audio, num_samples).astype(np.int16)
                write_rate = TARGET_RATE
                status_msg = f"📡 Analisi [LowQ - 8kHz]..."
            else:
                final_audio = processed_audio
                write_rate = self.sample_rate
                status_msg = f"📡 Analisi [HighQ - 44kHz]..."

            wav_buffer = io.BytesIO()
            wav.write(wav_buffer, write_rate, final_audio)
            wav_buffer.seek(0)

            print(status_msg)
            
            api_result = self._call_acr_api(wav_buffer, bias_artist=self.target_artist_bias)
            
            normalized_identifier = None
            best_track_data = None

            if api_result.get('status') == 'multiple_results':
                tracks = api_result['tracks']
                best_track = tracks[0]

                found_better = False
                if self.target_artist_bias:
                    for track in tracks:
                        if (self.target_artist_bias.lower() in track['artist'].lower() 
                            and self._is_mostly_latin(track['title'])):
                            best_track = track
                            found_better = True
                            break
                if not found_better:
                    for track in tracks:
                        score_diff = tracks[0]['score'] - track['score']
                        if self._is_mostly_latin(track['title']) and score_diff < 10:
                            best_track = track
                            break
                
                best_track['title'] = self._clean_title_for_display(best_track['title'])
                clean_id_title = self._normalize_text(best_track['title'])
                clean_id_artist = self._normalize_text(best_track['artist'])
                
                normalized_identifier = f"{clean_id_title} - {clean_id_artist}"
                best_track_data = best_track
            else:
                normalized_identifier = "silence_or_unknown"

            self.history_buffer.append(normalized_identifier)

            if best_track_data:
                # --- LOGICA STABILITÀ ---
                count_exact = self.history_buffer.count(normalized_identifier)
                count_title_only = len([x for x in self.history_buffer if x.startswith(clean_id_title + " -")])

                if count_exact >= 2 or count_title_only >= 2:
                    method = "Esatta" if count_exact >= 2 else "Titolo"
                    print(f"🛡️ Conferma stabilità ({method}): {best_track_data['title']} (Artist: {best_track_data['artist']})")
                    
                    if self.result_callback:
                        self.result_callback(best_track_data, target_artist=self.target_artist_bias)
        
        finally:
            self.upload_lock.release()

    def _loop_logic(self):
        print("⏱️ Avvio ciclo di monitoraggio...")
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

        self.stream = sd.InputStream(samplerate=self.sample_rate, channels=1, blocksize=self.block_size, callback=self._audio_callback)
        self.stream.start()

        self.monitor_thread = threading.Thread(target=self._loop_logic)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        return True

    def stop_continuous_recognition(self):
        self.is_running = False
        if self.stream:
            self.stream.stop(); self.stream.close()
        print("🛑 Monitoraggio Fermato.")
        return True

    def _call_acr_api(self, audio_buffer, bias_artist=None):
        THRESHOLD_MUSIC = 70
        THRESHOLD_HUMMING = 70 
        
        http_method = "POST"; http_uri = "/v1/identify"; data_type = "audio"; signature_version = "1"
        timestamp = str(int(time.time()))
        string_to_sign = (http_method + "\n" + http_uri + "\n" + self.access_key + "\n" + data_type + "\n" + signature_version + "\n" + timestamp)
        sign = base64.b64encode(hmac.new(self.access_secret.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()).decode('ascii')
        buffer_content = audio_buffer.getvalue()
        files = {'sample': ('temp.wav', buffer_content, 'audio/wav')}
        data = {'access_key': self.access_key, 'sample_bytes': len(buffer_content), 'timestamp': timestamp, 'signature': sign, 'data_type': data_type, "signature_version": signature_version}

        start_time = time.time()
        
        try:
            # Timeout 10s
            response = self.session.post(f"https://{self.host}/v1/identify", files=files, data=data, timeout=10)
            elapsed = time.time() - start_time
            
            if elapsed > 4.0:
                if not self.low_quality_mode:
                    print(f"⚠️ Upload lento ({elapsed:.1f}s) -> Attivo LowQ.")
                    self.low_quality_mode = True
            elif elapsed < 1.5:
                if self.low_quality_mode:
                    print(f"🚀 Upload veloce ({elapsed:.1f}s) -> Torno a HighQ.")
                    self.low_quality_mode = False

            result = response.json()
            status_code = result.get('status', {}).get('code')
            
            if status_code == 0:
                metadata = result.get('metadata', {})
                all_found = []
                def norm(sc): return int(sc * 100) if sc <= 1.0 else int(sc)

                # --- LOGICA DI ELABORAZIONE ---
                def process_section(track_list, threshold, type_label):
                    # Calcola il Bonus Dinamico
                    results_count = len(track_list)
                    # MODIFICA 1: Alzato da 15 a 20 il bonus per risultati multipli
                    current_bonus_val = 50 if results_count == 1 else 25

                    for t in track_list:
                        raw_score = norm(t.get('score', 0))
                        final_score = raw_score
                        title = t.get('title', 'Sconosciuto')
                        artists = t.get('artists', [])
                        artist_name = artists[0]['name'] if artists else "Unknown"

                        if bias_artist:
                             is_in_artist = bias_artist.lower() in artist_name.lower()
                             is_in_title = bias_artist.lower() in title.lower()
                             
                             if is_in_artist or is_in_title:
                                # Applica il bonus
                                final_score += current_bonus_val
                                
                                # MODIFICA 2: Log differenziati
                                if final_score >= threshold and raw_score < threshold:
                                    # CASO DECISIVO: Il brano è stato salvato grazie al bias
                                    print(f"🚀 BOOST DECISIVO (+{current_bonus_val}): '{title}' salvato! ({raw_score}% -> {final_score}%)")
                                else:
                                    # CASO GENERICO: Il boost è stato applicato (ma era già buono o è rimasto scarso)
                                    print(f"✨ Boost applicato (+{current_bonus_val}): '{title}' ({raw_score}% -> {final_score}%)")

                        if final_score >= threshold:
                            all_found.append({
                                "status": "success", "type": type_label,
                                "title": title, "artist": artist_name,
                                "album": t.get('album', {}).get('name'), 
                                "score": final_score, 
                                "duration_ms": t.get('duration_ms'), 
                                "isrc": t.get('external_ids', {}).get('isrc'),
                                "upc": t.get('external_metadata', {}).get('upc')
                            })
                        else:
                            # Stampa lo scarto solo se non è stato "silenziosamente" boostato
                            print(f"📉 SCARTATO: '{title}' - Artista: '{artist_name}' - Score: {final_score}%")

                if 'music' in metadata:
                    process_section(metadata['music'], THRESHOLD_MUSIC, "Original")
                if 'humming' in metadata:
                    process_section(metadata['humming'], THRESHOLD_HUMMING, "Cover/Humming")

                if all_found: 
                    all_found.sort(key=lambda x: x['score'], reverse=True)
                    print(f"✅ TROVATO: {all_found[0]['title']} - {all_found[0]['artist']} (Score: {all_found[0]['score']}%)")
                    return {"status": "multiple_results", "tracks": all_found}
                
                print("⚠️ Nessun risultato ha superato la soglia.")
                return {"status": "not_found"}

            elif status_code == 1001:
                print("🚫 API: Nessuna corrispondenza (Code 1001)")
                return {"status": "not_found"}
            else:
                print(f"❌ API Error Code: {status_code}: {result.get('status', {}).get('msg')}")
                return {"status": "not_found"}
                
        except Exception as e:
            print(f"❌ Errore rete (Timeout/SSL).")
            if not self.low_quality_mode:
                print("⚠️ Attivo modalità RISPARMIO DATI (8kHz) per recuperare.")
                self.low_quality_mode = True
            return {"status": "error"}