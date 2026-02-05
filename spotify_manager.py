import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
import re
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
        """
        Cerca cover HD pulendo il titolo da sporcizia (Live, Remaster, ecc.)
        """
        if not self.sp: return None
        
        # === FIX: PULIZIA TITOLO ===
        # Rimuove tutto ciò che è tra parentesi e le diciture tecniche
        clean_title = re.sub(r"[\(\[].*?[\)\]]", "", title)
        clean_title = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|live|remastered|remaster)\b.*", "", clean_title)
        clean_title = re.sub(r"\s-\s.*", "", clean_title) # Toglie code tipo " - 2011 Mix"
        clean_title = clean_title.strip()
        # ===========================

        # Se la pulizia ha svuotato troppo la stringa, usa l'originale per sicurezza
        search_title = clean_title if len(clean_title) > 1 else title

        query = f"track:{search_title} artist:{artist}"
        try:
            results = self.sp.search(q=query, type='track', limit=1)
            items = results['tracks']['items']
            if items and items[0]['album']['images']:
                return items[0]['album']['images'][0]['url']
        except Exception as e: 
            print(f"⚠️ Errore Cover HD: {e}")
        
        return None
    
    def get_most_popular_version(self, title, current_artist):
        """
        Cerca su Spotify se esiste una versione molto più famosa del brano rilevato.
        Restituisce una tupla (nuovo_artista, nuova_cover, popolarità) o None.
        """
        if not self.sp: return None
        
        import re
        from difflib import SequenceMatcher

        # Funzione helper interna per pulire i titoli per il confronto
        def clean_spotify_title(t):
            # Rimuove parentesi e contenuto
            t = re.sub(r"[\(\[].*?[\)\]]", "", t)
            # Rimuove trattini seguiti da qualsiasi cosa (es. " - Remaster 2012")
            t = re.sub(r"\s-\s.*", "", t)
            return t.strip().lower()

        clean_search_title = clean_spotify_title(title)
        if len(clean_search_title) < 2: return None

        try:
            # 1. Cerchiamo la versione MIGLIORE/PIÙ FAMOSA in assoluto
            # Aumentiamo il limit a 10 per essere sicuri di pescare l'originale se è un po' giù
            results = self.sp.search(q=f"track:{clean_search_title}", type='track', limit=10)
            tracks = results['tracks']['items']
            
            if not tracks: return None

            # === [MODIFICA: FILTRO RIGOROSO SUL TITOLO] ===
            # Prima di guardare la popolarità, scartiamo i titoli che non c'entrano niente.
            # Es. Cerco "Rock and Roll" -> Scarto "Rock and Roll All Nite" (KISS)
            
            valid_tracks = []
            for t in tracks:
                found_clean = clean_spotify_title(t['name'])
                # Ratio > 0.85 significa che i titoli devono essere quasi identici
                if SequenceMatcher(None, clean_search_title, found_clean).ratio() > 0.85:
                    valid_tracks.append(t)
            
            if not valid_tracks:
                return None

            # Ora prendiamo il più popolare solo tra quelli VALIDI
            best_match = max(valid_tracks, key=lambda x: x['popularity'])
            # ===============================================
            
            best_artist = best_match['artists'][0]['name']
            best_popularity = best_match['popularity']
            
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

            if current_popularity >= 70:
                print(f"     🛡️ [Smart Fix] Il brano è già una Hit ({current_popularity}). Nessuna sostituzione.")
                return None

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
    
    def search_specific_version(self, title, target_artist):
        """
        Cerca se esiste una versione specifica del brano fatta dall'artista target.
        Gestisce i suffissi 'Remastered', 'Live', ecc.
        """
        if not self.sp: return None
        
        import re
        from difflib import SequenceMatcher

        # 1. Pulizia titolo cercato (quello che arriva da ACRCloud)
        # Rimuove parentesi e diciture comuni
        clean_search = re.sub(r"[\(\[].*?[\)\]]", "", title)
        clean_search = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|live)\b.*", "", clean_search).strip().lower()
        
        # Query: cerchiamo titolo e artista
        query = f"track:{clean_search} artist:{target_artist}"
        
        try:
            # Alziamo il limit a 5 per evitare che il primo risultato sia una "Karaoke Version"
            results = self.sp.search(q=query, type='track', limit=5)
            items = results['tracks']['items']
            
            if not items: return None

            for track in items:
                # 2. Pulizia titolo TROVATO su Spotify (Cruciale per i Beatles!)
                found_name = track['name']
                
                # Rimuove tutto ciò che è tra parentesi
                found_clean = re.sub(r"[\(\[].*?[\)\]]", "", found_name)
                # Rimuove trattini seguiti da 'Remaster', 'Live', '2009', ecc.
                # Es: "Twist and Shout - Remastered 2009" -> "Twist and Shout"
                found_clean = re.sub(r"\s-\s.*", "", found_clean) 
                found_clean = found_clean.strip().lower()

                # 3. Confronto di Somiglianza
                similarity = SequenceMatcher(None, clean_search, found_clean).ratio()
                
                # Soglia: Se il titolo pulito è identico o molto simile (>0.85)
                # Oppure se uno è contenuto interamente nell'altro
                is_match = False
                if similarity > 0.85:
                    is_match = True
                elif (clean_search in found_clean) or (found_clean in clean_search):
                    # Controllo lunghezza per evitare match parziali stupidi (es "One" in "One Vision")
                    if abs(len(clean_search) - len(found_clean)) < 5:
                        is_match = True
                
                if is_match:
                    # Abbiamo trovato la versione del Target Artist!
                    canonical_artist = track['artists'][0]['name']
                    cover = None
                    if track['album']['images']:
                        cover = track['album']['images'][0]['url']
                    
                    return canonical_artist, cover
                    
        except Exception as e:
            print(f"⚠️ Errore ricerca specifica Spotify: {e}")
            
        return None