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
from collections import deque

load_dotenv()

class AudioManager:
    def __init__(self):
        self.host = os.getenv('ACR_HOST')
        self.access_key = os.getenv('ACR_ACCESS_KEY')
        self.access_secret = os.getenv('ACR_ACCESS_SECRET')
        
        # --- CONFIGURAZIONE STREAMING ---
        self.sample_rate = 44100
        self.window_duration = 20  # Lunghezza finestra analisi (20s)
        self.overlap_interval = 13 # Ogni quanto analizzare (13s)
        
        # Buffer Circolare: contiene sempre gli ultimi 20s di audio
        # Calcoliamo la dimensione massima del buffer in "blocchi"
        self.block_size = 4096
        self.audio_buffer = deque(maxlen=int((self.sample_rate * self.window_duration) / self.block_size) + 5)
        
        self.is_running = False
        self.stream = None
        self.monitor_thread = None
        
        # Callback per inviare i risultati al SessionManager
        self.result_callback = None 
        self.target_artist_bias = None

        print("🎤 Audio Manager Pronto (Modalità Streaming Continuo).")

    def _audio_callback(self, indata, frames, time, status):
        """Questa funzione viene chiamata dalla scheda audio automaticamente"""
        if status:
            print(f"⚠️ Audio Status: {status}")
        # Aggiungiamo il blocco audio al buffer circolare
        self.audio_buffer.append(indata.copy())

    def _preprocess_audio_chunk(self, full_audio_data):
        """Applica DSP all'intero blocco di 20s prima dell'invio"""
        if full_audio_data.dtype != np.float32:
            data = full_audio_data.astype(np.float32)
        else:
            data = full_audio_data

        # Filtro Passa-Alto 80Hz
        sos = signal.butter(10, 80, 'hp', fs=self.sample_rate, output='sos')
        filtered = signal.sosfilt(sos, data, axis=0)

        # Normalizzazione
        max_val = np.max(np.abs(filtered))
        if max_val > 0:
            normalized = filtered / max_val * 0.9
        else:
            normalized = filtered

        return (normalized * 32767).astype(np.int16)

    def _process_window(self):
        """Prende i dati dal buffer, crea un WAV e chiama ACRCloud"""
        if not self.audio_buffer:
            return

        # 1. Uniamo i blocchi del buffer in un unico array numpy
        try:
            full_recording = np.concatenate(list(self.audio_buffer))
        except ValueError:
            return # Buffer vuoto o errore

        # Se abbiamo meno audio del previsto (es. inizio sessione), procediamo comunque se > 5 sec
        if len(full_recording) < self.sample_rate * 5:
            return 

        # 2. DSP
        processed_audio = self._preprocess_audio_chunk(full_recording)

        # 3. Creazione WAV in memoria
        wav_buffer = io.BytesIO()
        wav.write(wav_buffer, self.sample_rate, processed_audio)
        wav_buffer.seek(0)

        # 4. Chiamata API (Sincrona, ma gira in un thread)
        print(f"📡 Analisi Finestra ({len(processed_audio)/self.sample_rate:.1f}s)...")
        api_result = self._call_acr_api(wav_buffer)
        
        # 5. INVIO RISULTATO AL CALLBACK (SessionManager)
        if self.result_callback:
            match = api_result
            if api_result.get('status') == 'multiple_results':
                match = api_result['tracks'][0]
                # Logica Bias rapida
                if self.target_artist_bias:
                    for track in api_result['tracks']:
                        if self.target_artist_bias.lower() in track['artist'].lower():
                            match = track
                            break
            
            # Passiamo il risultato a SessionManager.add_song
            self.result_callback(match, target_artist=self.target_artist_bias)

    def _loop_logic(self):
        """Il ciclo principale che scatta ogni 13 secondi"""
        print("⏱️ Avvio ciclo di monitoraggio...")
        
        # Attendiamo il riempimento iniziale del buffer (20s)
        time.sleep(self.window_duration) 

        while self.is_running:
            # Avviamo l'analisi in un thread separato per non bloccare il timer
            # (Anche se qui il timer è lo sleep, separare aiuta se l'API è lenta)
            threading.Thread(target=self._process_window).start()
            
            # Aspettiamo l'intervallo di sovrapposizione (13s)
            time.sleep(self.overlap_interval)

    def start_continuous_recognition(self, callback_function, target_artist=None):
        if self.is_running:
            return False
        
        self.is_running = True
        self.result_callback = callback_function # Funzione da chiamare quando troviamo qualcosa
        self.target_artist_bias = target_artist
        self.audio_buffer.clear()

        # 1. Apriamo lo stream audio (Non bloccante)
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            blocksize=self.block_size,
            callback=self._audio_callback
        )
        self.stream.start()

        # 2. Avviamo il thread timer che gestisce l'invio ogni 13s
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

    # --- API ACRCLOUD (Invariata, salvo piccole pulizie) ---
    def _call_acr_api(self, audio_buffer):
        MIN_SCORE_THRESHOLD = 65 
        http_method = "POST"; http_uri = "/v1/identify"; data_type = "audio"; signature_version = "1"
        timestamp = str(int(time.time()))
        string_to_sign = (http_method + "\n" + http_uri + "\n" + self.access_key + "\n" + data_type + "\n" + signature_version + "\n" + timestamp)
        sign = base64.b64encode(hmac.new(self.access_secret.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()).decode('ascii')
        buffer_content = audio_buffer.getvalue()
        files = {'sample': ('temp.wav', buffer_content, 'audio/wav')}
        data = {'access_key': self.access_key, 'sample_bytes': len(buffer_content), 'timestamp': timestamp, 'signature': sign, 'data_type': data_type, "signature_version": signature_version}

        try:
            response = requests.post(f"https://{self.host}/v1/identify", files=files, data=data, timeout=10)
            result = response.json()
            status_code = result.get('status', {}).get('code')
            
            if status_code == 0:
                metadata = result.get('metadata', {})
                all_found = []
                def norm(sc): return int(sc * 100) if sc <= 1.0 else int(sc)

                for section in ['music', 'humming']:
                    if section in metadata:
                        for t in metadata[section]:
                            sc = norm(t.get('score', 0))
                            if sc >= MIN_SCORE_THRESHOLD:
                                artists = t.get('artists', [])
                                all_found.append({
                                    "status": "success", "type": "Original" if section=='music' else "Cover",
                                    "title": t.get('title'), "artist": artists[0]['name'] if artists else "Unknown",
                                    "album": t.get('album', {}).get('name'), "score": sc,
                                    "duration_ms": t.get('duration_ms'), "isrc": t.get('external_ids', {}).get('isrc'),
                                    "upc": t.get('external_metadata', {}).get('upc')
                                })
                if all_found: return {"status": "multiple_results", "tracks": all_found}
                return {"status": "not_found"}
            return {"status": "not_found"} # Code 1001 etc
        except Exception as e:
            print(f"Error API: {e}")
            return {"status": "error"}