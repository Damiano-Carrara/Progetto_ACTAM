import time

class AudioManager:
    def __init__(self):
        print("Audio Manager Inizializzato")

    def recognize_song(self):
        # TODO: Qui in futuro metterai il codice per registrare e chiamare ACRCloud
        
        # Simuliamo un'attesa di 2 secondi (come se stesse registrando)
        time.sleep(2)
        
        # Ritorniamo un risultato finto per testare il frontend
        return {
            "status": "success",
            "title": "Bohemian Rhapsody",
            "artist": "Queen",
            "duration": "5:55"
        }