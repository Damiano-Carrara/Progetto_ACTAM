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
import threading # Importiamo il threading

# Carica le variabili dal file .env
load_dotenv()

class AudioManager:
    def __init__(self):
        self.host = os.getenv('ACR_HOST')
        self.access_key = os.getenv('ACR_ACCESS_KEY')
        self.access_secret = os.getenv('ACR_ACCESS_SECRET')
        self.filename = "temp_recording.wav"
        
        # --- STATO DI MONITORAGGIO ---
        self.is_monitoring = False
        self.monitoring_thread = None
        # Usiamo un SET per salvare i brani (gestisce i duplicati automaticamente)
        self.detected_songs = set()
        
        print("🎤 Audio Manager Pronto.")

    def record_audio(self, duration=15):
        """Registra l'audio dal microfono per 'duration' secondi"""
        fs = 44100
        print(f"🔴 Registrazione in corso per {duration} secondi...")
        
        recording = sd.rec(int(duration * fs), samplerate=fs, channels=1)
        sd.wait()
        
        wav.write(self.filename, fs, recording)
        print("✅ Registrazione completata.")
        return self.filename

    def _call_acr_api(self, file_path):
        """
        Funzione interna che chiama l'API di ACRCloud con un file audio.
        MODIFICATA: Restituisce una LISTA di tutti i brani sopra la soglia.
        """
        
        # --- IMPOSTIAMO LA SOGLIA MINIMA DI SCORE ---
        MIN_SCORE_THRESHOLD = 65 
        
        # ... (tutta la logica di 'http_method', 'string_to_sign', 'files', 'data' rimane invariata) ...
        
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

        files = [
            ('sample', (os.path.basename(file_path), open(file_path, 'rb'), 'audio/wav'))
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
            
            # --- ECCO LE RIGHE DI DEBUG CHE HO AGGIUNTO ---
            # Stampiamo l'intera risposta JSON per l'analisi
            print("--- RISPOSTA COMPLETA DA ACRCLOUD (DEBUG) ---")
            print(json.dumps(result, indent=2))
            print("---------------------------------------------")
            # --- FINE MODIFICA DI DEBUG ---
            
            status_code = result.get('status', {}).get('code')
            
            # --- NUOVA LOGICA PER RISULTATI MULTIPLI ---
            all_tracks_found = []

            if status_code == 0: # Successo!
                metadata = result.get('metadata', {})
                
                # 1. Cerca in 'music' (fingerprint)
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
                                "score": current_score
                            })

                # 2. Cerca in 'humming' (melodia)
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
                                "score": current_score
                            })
                
                # Se non abbiamo trovato nulla SOPRA SOGLIA
                if not all_tracks_found:
                    return {"status": "not_found", "message": f"Nessun brano sopra soglia {MIN_SCORE_THRESHOLD}"}
                
                # Restituisce una LISTA di brani validi
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
        """
        Il loop che gira nel thread.
        MODIFICATO: Gestisce una lista di risultati per i mashup.
        """
        print("🎧 Avvio del loop di monitoraggio (modalità Mashup)...")
        while self.is_monitoring:
            # 1. Registra
            file_path = self.record_audio(duration=record_duration)
            
            # 2. Riconosci (ora 'response' contiene una lista di brani)
            response = self._call_acr_api(file_path)
            
            # 3. Salva (Nuova logica di iterazione)
            if response.get('status') == 'multiple_results':
                tracks_list = response.get('tracks', [])
                
                if not tracks_list:
                     print(f"🔍 Nessun brano riconosciuto sopra la soglia in questo campione.")
                
                # Itera su TUTTI i brani che hanno superato la soglia
                for track in tracks_list:
                    track_identifier = f"{track.get('artist')} - {track.get('title')}"
                    current_score = track.get('score')
                    
                    # Aggiungiamo solo se è nuovo
                    if track_identifier not in self.detected_songs:
                        self.detected_songs.add(track_identifier)
                        print(f"🎶 BRANO RILEVATO (Score: {current_score}): {track_identifier}")
                    else:
                        print(f"... (brano già rilevato: {track_identifier})")
            
            else:
                # Errore o Codice 1001 (Non trovato)
                print(f"🔍 Nessun brano riconosciuto in questo campione ({response.get('message')}).")
            
            # 4. Cooldown (se stiamo ancora monitorando)
            if self.is_monitoring:
                print(f"❄️ Cooldown di {cooldown} secondi...")
                time.sleep(cooldown)
        
        print("🛑 Loop di monitoraggio fermato.")

    def start_monitoring(self, duration=8, cooldown=5):
        """Avvia il monitoraggio in un thread separato."""
        if self.is_monitoring:
            return {"status": "error", "message": "Il monitoraggio è già attivo."}
            
        self.is_monitoring = True
        self.detected_songs = set() # Resetta l'elenco
        
        # Avviamo il thread
        self.monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            args=(duration, cooldown)
        )
        self.monitoring_thread.daemon = True # Il thread muore se muore l'app
        self.monitoring_thread.start()
        
        return {"status": "success", "message": "Monitoraggio avviato."}

    def stop_monitoring(self):
        """Ferma il monitoraggio e restituisce i risultati."""
        if not self.is_monitoring:
            return {"status": "error", "message": "Il monitoraggio non era attivo."}
        
        self.is_monitoring = False
        
        # Aspettiamo che il thread finisca (max 5 secondi)
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5.0)
            
        print("✅ Monitoraggio fermato. Risultati finali:")
        print(self.detected_songs)
        
        # Restituiamo i risultati come lista
        return {"status": "success", "songs": list(self.detected_songs)}

    def get_current_results(self):
        """Restituisce i risultati correnti senza fermare il monitoraggio."""
        return {"status": "in_progress", "songs": list(self.detected_songs)}