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
    
    def get_most_popular_version(self, title, current_artist):
        """
        Cerca su Spotify se esiste una versione molto più famosa del brano rilevato.
        Restituisce una tupla (nuovo_artista, nuova_cover, popolarità) o None.
        """
        if not self.sp: return None
        
        import re
        from difflib import SequenceMatcher

        # Funzione helper interna per pulire i titoli
        def clean_spotify_title(t):
            # Rimuove parentesi tonde/quadre e contenuto
            t = re.sub(r"[\(\[].*?[\)\]]", "", t)
            # Rimuove trattini seguiti da parole chiave comuni nei titoli Spotify
            t = re.sub(r"(?i)\s-\s.*(remaster|mix|edit|version|live|single).*", "", t)
            return t.strip().lower()

        clean_search_title = clean_spotify_title(title)
        if len(clean_search_title) < 2: return None

        try:
            # 1. Cerchiamo la versione MIGLIORE/PIÙ FAMOSA in assoluto
            results = self.sp.search(q=f"track:{clean_search_title}", type='track', limit=5)
            tracks = results['tracks']['items']
            
            if not tracks: return None

            best_match = tracks[0]
            best_artist = best_match['artists'][0]['name']
            best_popularity = best_match['popularity'] # Popolarità Brano (0-100)
            
            # 2. Recuperiamo la popolarità della versione CORRENTE (Rilevata)
            current_popularity = 0
            comparison_mode = "Artist vs Track" # Default fallback
            
            try:
                # TENTATIVO A: Cerchiamo esattamente la traccia dell'artista rilevato (Track vs Track)
                # Usiamo il titolo pulito per massimizzare le chance di trovarla
                query_curr = f"track:{clean_search_title} artist:{current_artist}"
                curr_track_res = self.sp.search(q=query_curr, type='track', limit=1)
                
                if curr_track_res['tracks']['items']:
                    # Trovata! Usiamo la popolarità specifica di questa registrazione
                    current_popularity = curr_track_res['tracks']['items'][0]['popularity']
                    comparison_mode = "Track vs Track"
                else:
                    # TENTATIVO B: Fallback sulla popolarità dell'ARTISTA
                    # Se la traccia specifica non esiste o ha titolo diverso, usiamo la fama dell'artista
                    curr_art_res = self.sp.search(q=f"artist:{current_artist}", type='artist', limit=1)
                    if curr_art_res['artists']['items']:
                        current_popularity = curr_art_res['artists']['items'][0]['popularity']
            except: 
                pass

            print(f"     📊 [Pop Check] {comparison_mode}: '{current_artist}' ({current_popularity}) vs Best: '{best_artist}' ({best_popularity})")

            # 3. Calcolo Somiglianza Titoli
            # Puliamo ANCHE il titolo trovato su Spotify prima del confronto
            best_match_clean_title = clean_spotify_title(best_match['name'])
            ratio = SequenceMatcher(None, clean_search_title, best_match_clean_title).ratio()

            # 4. Calcolo Differenza Popolarità
            pop_diff = best_popularity - current_popularity

            # LOGICA DI SOSTITUZIONE:
            # - Il titolo deve essere simile (> 0.6)
            # - L'artista deve essere diverso
            # - La differenza di popolarità deve essere >= 20 OPPURE la nuova è una super hit (> 80)
            if ratio > 0.6 and best_artist.lower() != current_artist.lower():
                if (pop_diff >= 20) or (best_popularity > 80):
                    hd_cover = None
                    if best_match['album']['images']:
                        hd_cover = best_match['album']['images'][0]['url']
                    return best_artist, hd_cover, best_popularity

        except Exception as e:
            print(f"⚠️ Errore check popolarità: {e}")
        
        return None