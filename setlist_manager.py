import requests
import os
import json
from difflib import SequenceMatcher
from collections import Counter

class SetlistManager:
    def __init__(self):
        self.api_key = os.getenv("SETLIST_FM_KEY")
        self.base_url = "https://api.setlist.fm/rest/1.0"
        self.headers = {
            "x-api-key": self.api_key,
            "Accept": "application/json"
        }
        # Ora salviamo sia l'insieme piatto (per la whitelist) sia le sequenze ordinate
        self.cached_songs = []       # Lista semplice per i controlli rapidi
        self.concert_sequences = []  # Lista di liste (ogni lista è un concerto ordinato)

    def get_likely_songs(self, artist_name):
        """
        Scarica le scalette e prepara sia la cache piatta che le sequenze per la predizione.
        """
        if not self.api_key:
            print("⚠️ [Setlist] Nessuna API Key trovata nel file .env")
            return []

        print(f"📊 [Setlist] Cerco scalette e sequenze per: '{artist_name}'...")
        
        candidates = self._search_artist_candidates(artist_name)
        if not candidates:
            return []

        for candidate in candidates:
            mbid = candidate['mbid']
            name_found = candidate['name']
            
            print(f"     🔍 Analisi candidato: {name_found}...")
            
            # Scarica e salva le sequenze ordinate
            unique_songs, sequences = self._fetch_last_setlists_ordered(mbid)
            
            if unique_songs:
                self.cached_songs = list(unique_songs)
                self.concert_sequences = sequences
                print(f"     ✅ Trovato! Caricati {len(unique_songs)} brani e {len(sequences)} concerti completi.")
                return list(unique_songs)
            
        return []

    def predict_next(self, current_title):
        """
        Data la canzone corrente, guarda nello storico cosa viene suonato di solito DOPO.
        Restituisce il titolo più probabile o None.
        """
        if not self.concert_sequences or not current_title:
            return None
        
        current_clean = current_title.lower().strip()
        candidates = []

        # Scorre tutti i concerti memorizzati
        for concert in self.concert_sequences:
            for i, song in enumerate(concert):
                # Se trova la canzone corrente e NON è l'ultima del concerto
                # (Usiamo ratio > 0.9 per essere sicuri che sia proprio lei)
                if SequenceMatcher(None, current_clean, song.lower()).ratio() > 0.9:
                    if i + 1 < len(concert):
                        next_song = concert[i + 1]
                        candidates.append(next_song)

        if not candidates:
            return None

        # Trova la canzone più frequente tra i candidati successivi
        most_common = Counter(candidates).most_common(1)
        if most_common:
            prediction = most_common[0][0]
            confidence = most_common[0][1] # Quante volte appare
            print(f"🔮 [PREDICTION] Dopo '{current_title}' c'è spesso: '{prediction}' (Visto {confidence} volte)")
            return prediction
        
        return None

    def _fetch_last_setlists_ordered(self, mbid):
        """
        Versione avanzata che restituisce anche l'ordine delle canzoni.
        """
        url = f"{self.base_url}/artist/{mbid}/setlists"
        try:
            res = requests.get(url, headers=self.headers)
            if res.status_code == 200:
                data = res.json()
                unique_songs = set()
                sequences = [] # Lista di liste
                
                setlists = data.get("setlist", [])
                valid_found = 0
                
                for concert in setlists:
                    sets = concert.get("sets", {}).get("set", [])
                    if not sets: continue
                    
                    concert_song_list = []
                    
                    for set_section in sets:
                        for song in set_section.get("song", []):
                            if "name" in song:
                                s_name = song["name"].strip()
                                unique_songs.add(s_name.lower())
                                concert_song_list.append(s_name)
                    
                    if concert_song_list:
                        sequences.append(concert_song_list)
                        valid_found += 1
                    
                    if valid_found >= 5: break # Analizziamo gli ultimi 5 concerti
                
                return unique_songs, sequences
        except Exception as e:
            print(f"❌ Errore download setlist: {e}")
        return set(), []

    def _search_artist_candidates(self, name):
        # (Questo metodo rimane invariato rispetto a prima)
        url = f"{self.base_url}/search/artists"
        params = {"artistName": name, "sort": "relevance"}
        try:
            res = requests.get(url, headers=self.headers, params=params)
            if res.status_code == 200:
                return res.json().get("artist", [])[:3]
        except: pass
        return []

    def check_is_likely(self, title):
        # (Anche questo rimane uguale, serve per i boost semplici)
        if not self.cached_songs: return False
        title_clean = title.lower().strip()
        for likely in self.cached_songs:
            if title_clean in likely or likely in title_clean: return True
            if SequenceMatcher(None, title_clean, likely).ratio() > 0.85: return True
        return False