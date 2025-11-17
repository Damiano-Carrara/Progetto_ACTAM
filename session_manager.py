from datetime import datetime
from metadata_manager import MetadataManager

class SessionManager:
    def __init__(self):
        # Qui salveremo la lista dei brani della serata
        self.playlist = [] 
        self.meta_bot = MetadataManager()
        print("📝 Session Manager Inizializzato")

    def add_song(self, song_data):
        """
        Riceve i dati da ACRCloud e decide se aggiungerli alla lista
        o scartarli (se è un duplicato o un errore).
        """
        
        # 1. Se l'API non ha trovato nulla o ha dato errore, ignoriamo
        if song_data['status'] != 'success':
            return {"added": False, "reason": "No match"}
        
        if len(self.playlist) > 0:
            last_song = self.playlist[-1]
            if (last_song['title'] == song_data['title'] and 
                last_song['artist'] == song_data['artist']):
                return {"added": False, "reason": "Duplicate", "song": last_song}

        print("🔍 Cerco compositore su MusicBrainz...")
        composer_name = self.meta_bot.find_composer(song_data['title'], song_data['artist'])
        
        new_entry = {
            "id": len(self.playlist) + 1,
            "title": song_data['title'],
            "artist": song_data['artist'], # Questo è l'interprete (es. Whitney Houston)
            "composer": composer_name,     # <--- NUOVO CAMPO (es. Dolly Parton)
            "album": song_data['album'],
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "duration_ms": song_data.get('duration_ms', 0),
            "score": song_data.get('score', 0),
            "type": song_data.get('type', 'Original')
        }

        self.playlist.append(new_entry)
        return {"added": True, "song": new_entry}

    def get_playlist(self):
        """Restituisce tutta la lista per il Frontend"""
        return self.playlist

    def delete_song(self, song_id):
        """Permette di cancellare un brano (tramite ID)"""
        # Filtra la lista tenendo solo i brani che NON hanno quell'ID
        self.playlist = [s for s in self.playlist if s['id'] != song_id]
        return True