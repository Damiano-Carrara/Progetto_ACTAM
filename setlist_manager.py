import requests
import os
import json
import re
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
        # Salviamo sia l'insieme piatto (per la whitelist) sia le sequenze ordinate
        self.cached_songs = []       # Lista semplice per i controlli rapidi
        self.concert_sequences = []  # Lista di liste (ogni lista è un concerto ordinato)

    # Recupera la lista delle canzoni più probabili per un artista, basandosi sulle scalette recenti.
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

    # Predice la prossima canzone basandosi su cosa viene suonato di solito DOPO la canzone corrente nei concerti memorizzati.
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
                # (Usiamo ratio > 0.9 per essere sicuri di non rilevare falsi positivi)
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

    # Tiene conto dell'ordine delle canzoni
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
                sequences = []
                
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

    # Cerca i candidati per l'artista basandosi sul nome (con ricerca fuzzy) e restituisce i primi 3 risultati più rilevanti.
    def _search_artist_candidates(self, name):
        url = f"{self.base_url}/search/artists"
        params = {"artistName": name, "sort": "relevance"}
        try:
            res = requests.get(url, headers=self.headers, params=params)
            if res.status_code == 200:
                return res.json().get("artist", [])[:3]
        except: pass
        return []

    # Controlla se un titolo è "probabilmente" presente nelle scalette memorizzate, usando una logica più intelligente che tiene conto di parole comuni da ignorare e di fuzzy matching.
    def check_is_likely(self, title):
        if not self.cached_songs: return False
        
        # 1. Pulizia base (caratteri speciali)
        raw_clean_input = re.sub(r"[^a-zA-Z0-9\s]", "", title).lower().strip()
        
        # 2. Pulizia avanzata (rimozione "Live", "Remaster", ecc.)
        smart_clean_input = self._clean_noise_words(raw_clean_input)
        
        if not smart_clean_input: return False

        for likely in self.cached_songs:
            # Puliamo anche il titolo della scaletta per sicurezza
            raw_clean_likely = re.sub(r"[^a-zA-Z0-9\s]", "", likely).lower().strip()
            # Di solito nelle scalette non c'è "Live", ma per sicurezza lo rimuoviamo:
            clean_likely = self._clean_noise_words(raw_clean_likely) 

            # --- CASO 1: Match Esatto (Dopo la pulizia) ---
            if smart_clean_input == clean_likely:
                return True
                
            # --- CASO 2: Fuzzy Match (per piccoli errori di battitura) ---
            # Alziamo leggermente la soglia o usiamo ratio su stringhe pulite
            similarity = SequenceMatcher(None, smart_clean_input, clean_likely).ratio()
            
            # Soglia alta (0.90 o 0.95)
            if similarity > 0.92:
                return True
            
            # --- CASO 3: Gestione Titoli Corti (< 5 char) ---
            # I titoli corti non devono MAI usare fuzzy match lasco.
            # Devono essere identici (già coperto dal CASO 1) o parole isolate.
            if len(clean_likely) < 5:
                # Cerca parola intera esatta nel testo originale pulito
                pattern = r"\b" + re.escape(clean_likely) + r"\b"
                if re.search(pattern, raw_clean_input): 
                    # Verifica che non sia parte di una frase molto più lunga
                    return True

        return False
    
    # Metodo per rimuovere parole comuni che non influenzano l'identità della canzone, come "live", "remaster", ecc.
    def _clean_noise_words(self, text):
        """
        Rimuove parole comuni che non cambiano l'identità della canzone
        ma solo la versione (live, remaster, ecc.).
        """
        # Lista di parole da ignorare
        stop_words = [
            "live", "remaster", "remastered", "mix", "version", 
            "edit", "feat", "ft", "studio", "session", "acoustic", 
            "demo", "official", "video", "lyrics"
        ]
        
        # Crea pattern per rimuovere queste parole (es. " live " o " live" a fine stringa)
        clean_text = text
        for word in stop_words:
            # Rimuove la parola se è isolata (\b)
            pattern = r"\b" + re.escape(word) + r"\b"
            clean_text = re.sub(pattern, "", clean_text)
            
        # Rimuove spazi doppi creati dalla rimozione
        return re.sub(r"\s+", " ", clean_text).strip()