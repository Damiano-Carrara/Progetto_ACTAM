import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
from dotenv import load_dotenv

load_dotenv()

class SpotifyManager:
    def __init__(self):
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        
        self.sp = None
        if client_id and client_secret:
            try:
                auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
                self.sp = spotipy.Spotify(auth_manager=auth_manager)
                print("✅ [Spotify] API Connessa.")
            except Exception as e:
                print(f"⚠️ [Spotify] Errore Auth: {e}")
        else:
            print("⚠️ [Spotify] Credenziali mancanti nel .env")

    def get_artist_complete_data(self, artist_name):
        """
        Scarica un pacchetto completo di canzoni probabili:
        - Top 10 Tracks (Le Hit assolute)
        - Tutte le tracce dell'ultimo Album (Le novità del tour)
        """
        if not self.sp: return []
        
        collected_songs = set() # Usiamo un set per evitare duplicati automatici
        print(f"🎧 [Spotify] Scarico Hit e Album per: {artist_name}...")

        try:
            # 1. Cerca l'artista
            results = self.sp.search(q=artist_name, type='artist', limit=1)
            items = results['artists']['items']
            if not items:
                print("     ❌ Artista non trovato su Spotify.")
                return []
            
            artist_id = items[0]['id']
            # print(f"     ✅ Trovato ID: {items[0]['name']}")

            # 2. Prendi le Top 10 Tracks (Le Hit)
            top_tracks = self.sp.artist_top_tracks(artist_id, country='IT')
            for track in top_tracks['tracks']:
                # Pulisce titoli tipo "Nome (feat. X)" -> "nome"
                clean_name = track['name'].split('(')[0].strip().lower()
                collected_songs.add(clean_name)
            
            # 3. Prendi l'ultimo Album (Le Novità del tour)
            albums = self.sp.artist_albums(artist_id, album_type='album', limit=1)
            if albums['items']:
                latest_album = albums['items'][0]
                # print(f"     💿 Ultimo Album: {latest_album['name']}")
                album_tracks = self.sp.album_tracks(latest_album['id'])
                for track in album_tracks['items']:
                    clean_name = track['name'].split('(')[0].strip().lower()
                    collected_songs.add(clean_name)

            count = len(collected_songs)
            print(f"     📥 [Spotify] Aggiunti {count} brani (Hit + New Album).")
            return list(collected_songs)

        except Exception as e:
            print(f"❌ Errore Spotify: {e}")
            return []

    def get_hd_cover(self, title, artist):
        """Cerca cover HD"""
        if not self.sp: return None
        query = f"track:{title} artist:{artist}"
        try:
            results = self.sp.search(q=query, type='track', limit=1)
            items = results['tracks']['items']
            if items and items[0]['album']['images']:
                return items[0]['album']['images'][0]['url']
        except: pass
        return None