import os
import time
import hmac
import hashlib
import base64
import json
import requests
import sounddevice as sd
import scipy.io.wavfile as wav
from dotenv import load_dotenv

# Carica le variabili dal file .env
load_dotenv()

class AudioManager:
    def __init__(self):
        self.host = os.getenv('ACR_HOST')
        self.access_key = os.getenv('ACR_ACCESS_KEY')
        self.access_secret = os.getenv('ACR_ACCESS_SECRET')
        self.filename = "temp_recording.wav"
        print("🎤 Audio Manager Pronto.")

    def record_audio(self, duration=10):
        """Registra l'audio dal microfono per 'duration' secondi"""
        fs = 44100  # Frequenza di campionamento (standard CD)
        print(f"🔴 Registrazione in corso per {duration} secondi...")
        
        # Registrazione (blocca il codice finché non finisce)
        recording = sd.rec(int(duration * fs), samplerate=fs, channels=1)
        sd.wait()  # Attende la fine della registrazione
        
        # Salva il file temporaneo
        wav.write(self.filename, fs, recording)
        print("✅ Registrazione completata.")
        return self.filename

    def recognize_song(self):
        """Chiama l'API di ACRCloud"""
        
        # 1. Registra l'audio
        file_path = self.record_audio(duration=10)

        # 2. Prepara i dati per l'API
        http_method = "POST"
        http_uri = "/v1/identify"
        data_type = "audio"
        signature_version = "1"
        timestamp = str(int(time.time()))

        string_to_sign = (http_method + "\n" + 
                          http_uri + "\n" + 
                          self.access_key + "\n" + 
                          data_type + "\n" + 
                          signature_version + "\n" + 
                          timestamp)

        sign = base64.b64encode(
            hmac.new(self.access_secret.encode('ascii'), 
                     string_to_sign.encode('ascii'), 
                     digestmod=hashlib.sha1).digest()
        ).decode('ascii')

        # 3. Invia la richiesta
        files = [
            ('sample', ('test.wav', open(file_path, 'rb'), 'audio/wav'))
        ]
        data = {
            'access_key': self.access_key,
            'sample_bytes': os.path.getsize(file_path),
            'timestamp': timestamp,
            'signature': sign,
            'data_type': data_type,
            "signature_version": signature_version
        }

        print("📡 Invio ad ACRCloud in corso...")
        try:
            url = f"https://{self.host}/v1/identify"
            response = requests.post(url, files=files, data=data)
            result = response.json()
            
            status_code = result.get('status', {}).get('code')
            
            if status_code == 0: # Successo!
                metadata = result.get('metadata', {})
                
                # Logica intelligente: Cerca prima Music, poi Humming
                if 'music' in metadata:
                    track_data = metadata['music'][0]
                    recognition_type = "Original"
                elif 'humming' in metadata:
                    track_data = metadata['humming'][0]
                    recognition_type = "Cover/Humming"
                else:
                    return {"status": "not_found", "message": "Nessun brano identificato nei metadati"}

                # Estrazione dati sicura (gestisce chiavi mancanti)
                artists_list = track_data.get('artists', [])
                artist_name = artists_list[0]['name'] if artists_list else "Sconosciuto"
                
                return {
                    "status": "success",
                    "type": recognition_type,
                    "title": track_data.get('title', 'Titolo Sconosciuto'),
                    "artist": artist_name,
                    "album": track_data.get('album', {}).get('name', 'Album Sconosciuto'),
                    "duration_ms": track_data.get('duration_ms', 0),
                    "score": track_data.get('score', 0) # Utile per capire l'affidabilità
                }

            elif status_code == 1001:
                return {"status": "not_found", "message": "Nessun risultato trovato"}
            else:
                error_msg = result.get('status', {}).get('msg', 'Errore sconosciuto')
                return {"status": "error", "message": f"Codice {status_code}: {error_msg}"}

        except Exception as e:
            print(f"❌ ERRORE: {e}")
            return {"status": "error", "message": str(e)}