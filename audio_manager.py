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

load_dotenv()

class AudioManager:
    def __init__(self):
        self.host = os.getenv('ACR_HOST')
        self.access_key = os.getenv('ACR_ACCESS_KEY')
        self.access_secret = os.getenv('ACR_ACCESS_SECRET')
        
        # --- CONFIGURAZIONE STREAMING ---
        self.sample_rate = 44100
        
        # Finestra 12s / Overlap 6s
        # Ottimo bilanciamento per catturare brani live senza sovraccaricare la rete
        self.window_duration = 12 
        self.overlap_interval = 6 
        
        self.block_size = 4096
        self.audio_buffer = deque(maxlen=int((self.sample_rate * self.window_duration) / self.block_size) + 5)
        
        # --- SISTEMA DI STABILITÀ ---
        # 10 slot * 6 sec = 60 secondi di memoria storica.
        self.history_buffer = deque(maxlen=10) 
        
        self.is_running = False
        self.stream = None
        self.monitor_thread = None
        self.result_callback = None 
        self.target_artist_bias = None

        print(f"🎤 Audio Manager Pronto. Timeout API: 20s | Pulizia Titoli: Attiva (Doppio livello)")

    def _audio_callback(self, indata, frames, time, status):
        if status:
            print(f"⚠️ Audio Status: {status}")
        self.audio_buffer.append(indata.copy())

    def _preprocess_audio_chunk(self, full_audio_data):
        if full_audio_data.dtype != np.float32:
            data = full_audio_data.astype(np.float32)
        else:
            data = full_audio_data

        # Filtro Passa-Alto 80Hz (Essenziale per i live)
        sos = signal.butter(10, 80, 'hp', fs=self.sample_rate, output='sos')
        filtered = signal.sosfilt(sos, data, axis=0)

        # Normalizzazione
        max_val = np.max(np.abs(filtered))
        if max_val > 0:
            normalized = filtered / max_val * 0.95
        else:
            normalized = filtered

        return (normalized * 32767).astype(np.int16)

    def _normalize_text(self, text):
        """
        Livello 1: Pulizia per il CONFRONTO nello storico.
        Rende tutto minuscolo e toglie ogni variazione per capire se è lo stesso brano.
        """
        if not text: return ""
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        clean = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live|mixed)\b.*", "", clean)
        return clean.strip().lower()

    def _clean_title_for_display(self, text):
        """
        Livello 2: Pulizia per il SALVATAGGIO in scaletta.
        Mantiene le Maiuscole originali, ma taglia via le parentesi indesiderate.
        Es: "Roxanne (Live At Tokyo)" -> "Roxanne"
        """
        if not text: return ""
        # Rimuove contenuto tra parentesi tonde o quadre
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        return clean.strip()

    def _is_mostly_latin(self, text):
        """Filtro anti-giapponese/caratteri speciali"""
        if not text: return False
        try:
            ascii_count = len([c for c in text if ord(c) < 128])
            return (ascii_count / len(text)) > 0.8
        except:
            return True

    def _process_window(self):
        if not self.audio_buffer: return

        try:
            full_recording = np.concatenate(list(self.audio_buffer))
        except ValueError: return 

        if len(full_recording) < self.sample_rate * (self.window_duration - 1): return 

        processed_audio = self._preprocess_audio_chunk(full_recording)
        wav_buffer = io.BytesIO()
        wav.write(wav_buffer, self.sample_rate, processed_audio)
        wav_buffer.seek(0)

        print(f"📡 Analisi Finestra ({self.window_duration}s)...")
        api_result = self._call_acr_api(wav_buffer)
        
        normalized_identifier = None
        best_track_data = None

        if api_result.get('status') == 'multiple_results':
            tracks = api_result['tracks']
            best_track = tracks[0]

            # --- SELEZIONE INTELLIGENTE (Bias + Latino) ---
            found_better = False
            
            # 1. Priorità Bias
            if self.target_artist_bias:
                for track in tracks:
                    if (self.target_artist_bias.lower() in track['artist'].lower() 
                        and self._is_mostly_latin(track['title'])):
                        best_track = track
                        found_better = True
                        break
            
            # 2. Priorità Lingua (Latino vs Kanji)
            if not found_better:
                for track in tracks:
                    score_diff = tracks[0]['score'] - track['score']
                    if self._is_mostly_latin(track['title']) and score_diff < 10:
                        best_track = track
                        break
            
            # --- APPLICAZIONE PULIZIA ---
            
            # A) Pulizia "Estetica" per il salvataggio finale
            # Sovrascriviamo il titolo nell'oggetto che passeremo al SessionManager
            best_track['title'] = self._clean_title_for_display(best_track['title'])

            # B) Pulizia "Logica" per lo storico (confronto)
            # Usiamo la versione minuscola e strippata per l'ID univoco
            clean_id_title = self._normalize_text(best_track['title']) # Nota: qui usiamo il titolo già pulito esteticamente
            clean_id_artist = self._normalize_text(best_track['artist'])
            
            normalized_identifier = f"{clean_id_title} - {clean_id_artist}"
            best_track_data = best_track
        else:
            normalized_identifier = "silence_or_unknown"

        # Aggiungiamo allo storico l'ID normalizzato
        self.history_buffer.append(normalized_identifier)

        if not best_track_data:
            return

        # Verifichiamo quante volte appare nello storico
        count = self.history_buffer.count(normalized_identifier)
        
        # Conferma se presente almeno 2 volte su 10
        if count >= 2:
            print(f"🛡️ Conferma stabilità ({count}/10): {best_track_data['title']}")
            if self.result_callback:
                # Qui passiamo 'best_track_data' che ha già il titolo pulito al punto (A)
                self.result_callback(best_track_data, target_artist=self.target_artist_bias)
        else:
            print(f"⏳ In attesa di conferma ({count}/10)... {normalized_identifier}")


    def _loop_logic(self):
        print("⏱️ Avvio ciclo di monitoraggio...")
        time.sleep(self.window_duration) 
        while self.is_running:
            # Usiamo i thread: questo evita che un timeout API blocchi il ciclo
            threading.Thread(target=self._process_window).start()
            time.sleep(self.overlap_interval)

    def start_continuous_recognition(self, callback_function, target_artist=None):
        if self.is_running: return False
        self.is_running = True
        self.result_callback = callback_function
        self.target_artist_bias = target_artist
        self.audio_buffer.clear()
        self.history_buffer.clear() 

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

    def _call_acr_api(self, audio_buffer):
        THRESHOLD_MUSIC = 70
        THRESHOLD_HUMMING = 80 
        
        http_method = "POST"; http_uri = "/v1/identify"; data_type = "audio"; signature_version = "1"
        timestamp = str(int(time.time()))
        string_to_sign = (http_method + "\n" + http_uri + "\n" + self.access_key + "\n" + data_type + "\n" + signature_version + "\n" + timestamp)
        sign = base64.b64encode(hmac.new(self.access_secret.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()).decode('ascii')
        buffer_content = audio_buffer.getvalue()
        files = {'sample': ('temp.wav', buffer_content, 'audio/wav')}
        data = {'access_key': self.access_key, 'sample_bytes': len(buffer_content), 'timestamp': timestamp, 'signature': sign, 'data_type': data_type, "signature_version": signature_version}

        try:
            # Timeout a 20s per gestire connessioni lente senza fallire
            response = requests.post(f"https://{self.host}/v1/identify", files=files, data=data, timeout=20) 
            result = response.json()
            status_code = result.get('status', {}).get('code')
            
            if status_code == 0:
                metadata = result.get('metadata', {})
                all_found = []
                def norm(sc): return int(sc * 100) if sc <= 1.0 else int(sc)

                if 'music' in metadata:
                    for t in metadata['music']:
                        sc = norm(t.get('score', 0))
                        if sc >= THRESHOLD_MUSIC:
                            artists = t.get('artists', [])
                            all_found.append({
                                "status": "success", "type": "Original",
                                "title": t.get('title'), "artist": artists[0]['name'] if artists else "Unknown",
                                "album": t.get('album', {}).get('name'), "score": sc,
                                "duration_ms": t.get('duration_ms'), "isrc": t.get('external_ids', {}).get('isrc'),
                                "upc": t.get('external_metadata', {}).get('upc')
                            })

                if 'humming' in metadata:
                    for t in metadata['humming']:
                        sc = norm(t.get('score', 0))
                        if sc >= THRESHOLD_HUMMING:
                            artists = t.get('artists', [])
                            all_found.append({
                                "status": "success", "type": "Cover/Humming",
                                "title": t.get('title'), "artist": artists[0]['name'] if artists else "Unknown",
                                "album": t.get('album', {}).get('name'), "score": sc,
                                "duration_ms": t.get('duration_ms'), "isrc": t.get('external_ids', {}).get('isrc'),
                                "upc": t.get('external_metadata', {}).get('upc')
                            })

                if all_found: 
                    all_found.sort(key=lambda x: x['score'], reverse=True)
                    return {"status": "multiple_results", "tracks": all_found}
                return {"status": "not_found"}
            return {"status": "not_found"}
        except Exception as e:
            print(f"Error API: {e}")
            return {"status": "error"}