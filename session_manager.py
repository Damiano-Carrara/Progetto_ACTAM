from datetime import datetime

class SessionManager:
    def __init__(self):
        # Qui salveremo la lista dei brani della serata
        self.playlist = [] 
        print("📝 Session Manager Inizializzato")

    def add_song(self, song_data):
        """
        Riceve i dati da ACRCloud e decide se aggiungerli alla lista
        o scartarli (se è un duplicato o un errore).
        """
        
        # 1. Se l'API non ha trovato nulla o ha dato errore, ignoriamo
        if song_data['status'] != 'success':
            return {"added": False, "reason": "No match"}

        # 2. Prepariamo il pacchetto dati pulito per il borderò
        new_entry = {
            "id": len(self.playlist) + 1, # ID progressivo (1, 2, 3...)
            "title": song_data['title'],
            "artist": song_data['artist'],
            "album": song_data['album'],
            "timestamp": datetime.now().strftime("%H:%M:%S"), # Ora attuale
            "duration_ms": song_data['duration_ms'],
            "type": song_data.get('type', 'Original') # Se è cover o originale
        }

        # 3. LOGICA ANTI-DUPLICATO
        # Controlliamo se la lista non è vuota
        if len(self.playlist) > 0:
            last_song = self.playlist[-1] # L'ultimo brano inserito
            
            # Se Titolo e Artista sono identici all'ultimo brano...
            if (last_song['title'] == new_entry['title'] and 
                last_song['artist'] == new_entry['artist']):
                
                print(f"🔁 Duplicato ignorato: {new_entry['title']}")
                return {"added": False, "reason": "Duplicate", "song": last_song}

        # 4. Se siamo qui, è una canzone nuova! Aggiungiamola.
        self.playlist.append(new_entry)
        print(f"✅ Nuova canzone aggiunta: {new_entry['title']}")
        return {"added": True, "song": new_entry}

    def get_playlist(self):
        """Restituisce tutta la lista per il Frontend"""
        return self.playlist

    def delete_song(self, song_id):
        """Permette di cancellare un brano (tramite ID)"""
        # Filtra la lista tenendo solo i brani che NON hanno quell'ID
        self.playlist = [s for s in self.playlist if s['id'] != song_id]
        return True