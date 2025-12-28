import requests
import os
import json
from difflib import SequenceMatcher

class SetlistManager:
    def __init__(self):
        self.api_key = os.getenv("SETLIST_FM_KEY")
        self.base_url = "https://api.setlist.fm/rest/1.0"
        self.headers = {
            "x-api-key": self.api_key,
            "Accept": "application/json"
        }
        self.cached_songs = []

    def get_likely_songs(self, artist_name):
        """
        1. Cerca l'artista e ottiene TUTTI gli omonimi.
        2. Prova a scaricare la scaletta per ognuno.
        3. Il primo che ha canzoni recenti vince.
        """
        if not self.api_key:
            print("⚠️ [Setlist] Nessuna API Key trovata nel file .env")
            return []

        print(f"📊 [Setlist] Cerco scalette per: '{artist_name}' (Scansione Smart)...")
        
        # 1. Ottieni la lista dei candidati (es. Salmo-Rapper, Salmo-Band, ecc.)
        candidates = self._search_artist_candidates(artist_name)
        
        if not candidates:
            print("⚠️ [Setlist] Nessun artista trovato con questo nome.")
            return []

        # 2. Prova i candidati uno per uno finché non trovi quello attivo
        for candidate in candidates:
            mbid = candidate['mbid']
            name_found = candidate['name']
            disambiguation = candidate.get('disambiguation', 'N/A')
            
            print(f"     🔍 Controllo candidato: {name_found} ({disambiguation})...")
            
            songs = self._fetch_last_setlists(mbid)
            
            if songs and len(songs) > 0:
                self.cached_songs = songs
                print(f"     ✅ Trovato artista attivo! Caricati {len(songs)} brani.")
                # print(f"        📝 Esempi: {', '.join(songs[:3])}...") 
                return songs
            else:
                print(f"        ❌ Nessuna scaletta recente. Passo al prossimo omonimo...")

        print("⚠️ [Setlist] Ho controllato tutti gli omonimi, ma nessuno ha scalette recenti.")
        return []

    def _search_artist_candidates(self, name):
        """Restituisce una lista di possibili artisti (MBID e Info)"""
        url = f"{self.base_url}/search/artists"
        params = {"artistName": name, "sort": "relevance"}
        try:
            res = requests.get(url, headers=self.headers, params=params)
            if res.status_code == 200:
                data = res.json()
                # Restituisce i primi 3 risultati per evitare loop infiniti
                return data.get("artist", [])[:3]
        except Exception as e:
            print(f"❌ Errore ricerca artista: {e}")
        return []

    def _fetch_last_setlists(self, mbid):
        url = f"{self.base_url}/artist/{mbid}/setlists"
        try:
            res = requests.get(url, headers=self.headers)
            if res.status_code == 200:
                data = res.json()
                unique_songs = set()
                
                setlists = data.get("setlist", [])
                if not setlists: return []

                # Controlla solo scalette che hanno canzoni
                valid_setlists_found = 0
                
                for concert in setlists:
                    sets = concert.get("sets", {}).get("set", [])
                    if not sets: continue # Salta concerti vuoti
                    
                    valid_setlists_found += 1
                    for set_section in sets:
                        for song in set_section.get("song", []):
                            if "name" in song:
                                unique_songs.add(song["name"].lower().strip())
                    
                    # Se abbiamo analizzato 3 concerti PIENI, ci fermiamo
                    if valid_setlists_found >= 3: break
                
                return list(unique_songs)
        except Exception as e:
            print(f"❌ Errore download setlist: {e}")
        return []

    def check_is_likely(self, title):
        if not self.cached_songs: return False
        title_clean = title.lower().strip()
        
        for likely in self.cached_songs:
            if title_clean in likely or likely in title_clean: return True
            if SequenceMatcher(None, title_clean, likely).ratio() > 0.85: return True
        return False