from datetime import datetime
from metadata_manager import MetadataManager

class SessionManager:
    def __init__(self):
        self.playlist = [] 
        self.meta_bot = MetadataManager()
        self._next_id = 1 # ⭐ Nuovo contatore progressivo
        print("📝 Session Manager Inizializzato")

    def add_song(self, song_data):
        """
        Riceve i dati da ACRCloud e decide se aggiungerli alla lista
        o scartarli (se è un duplicato o un errore).
        """
        
        # 1. Se l'API non ha trovato nulla o ha dato errore, ignoriamo
        if song_data['status'] != 'success':
            return {"added": False, "reason": "No match"}
        
        # Controllo duplicati consecutivi
        if len(self.playlist) > 0:
            last_song = self.playlist[-1]
            if (last_song['title'] == song_data['title'] and 
                last_song['artist'] == song_data['artist']):
                return {"added": False, "reason": "Duplicate", "song": last_song}

        print("🔍 Cerco compositore su MusicBrainz...")
        
        # Estraiamo i nuovi dati ISRC e UPC (se ci sono)
        isrc = song_data.get('isrc')
        upc = song_data.get('upc')
        
        # Passiamo tutto al MetadataManager
        composer_name = self.meta_bot.find_composer(
            title=song_data['title'], 
            artist=song_data['artist'],
            isrc=isrc,
            upc=upc
        )
        
        new_entry = {
            "id": self._next_id, # Usa il contatore progressivo (ora esiste!)
            "title": song_data['title'],
            "artist": song_data['artist'], 
            "composer": composer_name,     
            "album": song_data.get('album', 'Sconosciuto'),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "duration_ms": song_data.get('duration_ms', 0),
            "score": song_data.get('score', 0),
            "type": song_data.get('type', 'Original'),
            "isrc": isrc, # Salviamo anche questi per completezza
            "upc": upc
        }

        # Incrementa il contatore per il prossimo brano
        self._next_id += 1

        self.playlist.append(new_entry)
        return {"added": True, "song": new_entry}

    def get_playlist(self):
        """Restituisce tutta la lista per il Frontend"""
        return self.playlist

    def delete_song(self, song_id):
        """Permette di cancellare un brano (tramite ID)"""
        try:
            song_id = int(song_id)
        except ValueError:
            return False

        original_len = len(self.playlist)
        self.playlist = [s for s in self.playlist if s['id'] != song_id]
        
        return len(self.playlist) < original_len