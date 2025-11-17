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
import threading
import io  # <--- 1. Importiamo il modulo per gestire i file in memoria

# Carica le variabili dal file .env
load_dotenv()

class AudioManager:
    def __init__(self):
        self.host = os.getenv('ACR_HOST')
        self.access_key = os.getenv('ACR_ACCESS_KEY')
        self.access_secret = os.getenv('ACR_ACCESS_SECRET')
        
        # self.filename = "temp_recording.wav" <--- NON SERVE PIÙ
        
        # --- STATO DI MONITORAGGIO ---
        self.is_monitoring = False
        self.monitoring_thread = None
        self.detected_songs = set()
        
        print("🎤 Audio Manager Pronto (Modalità RAM).")

    def record_audio(self, duration=15):
        """
        Registra l'audio dal microfono e lo salva in un buffer in MEMORIA RAM.
        Non crea nessun file su disco.
        """
        fs = 44100
        print(f"🔴 Registrazione in corso per {duration} secondi...")
        
        # Registrazione
        recording = sd.rec(int(duration * fs), samplerate=fs, channels=1)
        sd.wait()
        
        # --- MODIFICA RAM: Scrittura su buffer invece che su file ---
        wav_buffer = io.BytesIO()           # Crea un file virtuale in memoria
        wav.write(wav_buffer, fs, recording)
        wav_buffer.seek(0)                  # Riavvolge il "nastro" all'inizio per poterlo leggere
        
        print("✅ Registrazione completata (in memoria).")
        return wav_buffer  # Restituisce l'oggetto buffer, non una stringa filename
    
    def recognize_song(self):
        """
        Metodo wrapper sincrono per compatibilità con app.py.
        Registra -> Chiama API -> Restituisce il risultato migliore.
        """
        # 1. Registra in RAM (usa il default di 15s o quello che preferisci)
        audio_buffer = self.record_audio(duration=15)
        
        # 2. Chiama API interna
        api_result = self._call_acr_api(audio_buffer)
        
        # 3. IMPORTANTE: Chiudi il buffer per liberare la RAM
        audio_buffer.close()
        
        # 4. Adatta il risultato per app.py
        # La nuova _call_acr_api restituisce una lista di tracce ('multiple_results')
        # ma il tuo app.py si aspetta un singolo oggetto brano.
        
        if api_result.get('status') == 'multiple_results':
            # Prendiamo il primo risultato della lista (solitamente quello con score più alto)
            best_match = api_result['tracks'][0]
            return best_match
        
        # Se è 'not_found' o 'error', restituiamo il risultato così com'è
        return api_result

    def _call_acr_api(self, audio_buffer):
        """
        Chiama l'API usando il buffer audio in memoria.
        """
        
        # --- IMPOSTIAMO LA SOGLIA MINIMA DI SCORE ---
        MIN_SCORE_THRESHOLD = 65 
        
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

        # --- MODIFICA RAM: Calcolo dimensione e preparazione file ---
        # Otteniamo la dimensione del file direttamente dal buffer
        file_size = audio_buffer.getbuffer().nbytes 

        files = [
            # 'temp.wav' è un nome finto che diamo all'API per fargli capire che è un wav,
            # ma il contenuto vero viene letto da audio_buffer
            ('sample', ('temp.wav', audio_buffer, 'audio/wav'))
        ]
        
        data = {
            'access_key': self.access_key,
            'sample_bytes': file_size, # Usiamo la dimensione calcolata dal buffer
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
            
            # DEBUG (Opzionale)
            # print("--- RISPOSTA ACRCLOUD ---")
            # print(json.dumps(result, indent=2))
            
            status_code = result.get('status', {}).get('code')
            all_tracks_found = []

            if status_code == 0: # Successo!
                metadata = result.get('metadata', {})
                
                # 1. Cerca in 'music'
                if 'music' in metadata:
                    for track_data in metadata['music']:
                        current_score = track_data.get('score', 0)
                        if current_score >= MIN_SCORE_THRESHOLD:
                            artists_list = track_data.get('artists', [])
                            artist_name = artists_list[0]['name'] if artists_list else "Sconosciuto"
                            all_tracks_found.append({
                                "status": "success",
                                "type": "Original",
                                "title": track_data.get('title', 'Titolo Sconosciuto'),
                                "artist": artist_name,
                                "album": track_data.get('album', {}).get('name', 'Album Sconosciuto'),
                                "score": current_score,
                                "duration_ms": track_data.get('duration_ms', 0) # <--- RIGA AGGIUNTA QUI
                            })

                # 2. Cerca in 'humming'
                if 'humming' in metadata:
                    for track_data in metadata['humming']:
                        current_score = track_data.get('score', 0)
                        if current_score >= MIN_SCORE_THRESHOLD:
                            artists_list = track_data.get('artists', [])
                            artist_name = artists_list[0]['name'] if artists_list else "Sconosciuto"
                            all_tracks_found.append({
                                "status": "success",
                                "type": "Cover/Humming",
                                "title": track_data.get('title', 'Titolo Sconosciuto'),
                                "artist": artist_name,
                                "album": track_data.get('album', {}).get('name', 'Album Sconosciuto'),
                                "score": current_score,
                                "duration_ms": track_data.get('duration_ms', 0) # <--- RIGA AGGIUNTA QUI
                            })
                
                if not all_tracks_found:
                    return {"status": "not_found", "message": f"Nessun brano sopra soglia {MIN_SCORE_THRESHOLD}"}
                
                return {"status": "multiple_results", "tracks": all_tracks_found}

            elif status_code == 1001:
                return {"status": "not_found", "message": "Nessun risultato trovato"}
            else:
                error_msg = result.get('status', {}).get('msg', 'Errore sconosciuto')
                return {"status": "error", "message": f"Codice {status_code}: {error_msg}"}

        except Exception as e:
            print(f"❌ ERRORE: {e}")
            return {"status": "error", "message": str(e)}

    def _monitoring_loop(self, record_duration, cooldown):
        print("🎧 Avvio del loop di monitoraggio (modalità Mashup - RAM)...")
        while self.is_monitoring:
            # 1. Registra (Ottiene un buffer, non un path)
            audio_buffer = self.record_audio(duration=record_duration)
            
            # 2. Riconosci
            response = self._call_acr_api(audio_buffer)
            
            # 3. Salva i risultati
            if response.get('status') == 'multiple_results':
                tracks_list = response.get('tracks', [])
                
                if not tracks_list:
                     print(f"🔍 Nessun brano riconosciuto sopra la soglia.")
                
                for track in tracks_list:
                    track_identifier = f"{track.get('artist')} - {track.get('title')}"
                    current_score = track.get('score')
                    
                    if track_identifier not in self.detected_songs:
                        self.detected_songs.add(track_identifier)
                        print(f"🎶 BRANO RILEVATO (Score: {current_score}): {track_identifier}")
                    else:
                        print(f"... (brano già rilevato: {track_identifier})")
            
            else:
                print(f"🔍 Nessun brano riconosciuto ({response.get('message')}).")
            
            # Chiudiamo il buffer per liberare memoria RAM
            audio_buffer.close()

            # 4. Cooldown
            if self.is_monitoring:
                print(f"❄️ Cooldown di {cooldown} secondi...")
                time.sleep(cooldown)
        
        print("🛑 Loop di monitoraggio fermato.")

    def start_monitoring(self, duration=8, cooldown=5):
        if self.is_monitoring:
            return {"status": "error", "message": "Il monitoraggio è già attivo."}
            
        self.is_monitoring = True
        self.detected_songs = set()
        
        self.monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            args=(duration, cooldown)
        )
        self.monitoring_thread.daemon = True
        self.monitoring_thread.start()
        
        return {"status": "success", "message": "Monitoraggio avviato."}

    def stop_monitoring(self):
        if not self.is_monitoring:
            return {"status": "error", "message": "Il monitoraggio non era attivo."}
        
        self.is_monitoring = False
        
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5.0)
            
        print("✅ Monitoraggio fermato.")
        return {"status": "success", "songs": list(self.detected_songs)}

    def get_current_results(self):
        return {"status": "in_progress", "songs": list(self.detected_songs)}