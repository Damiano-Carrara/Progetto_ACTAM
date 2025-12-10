import musicbrainzngs
import time
import re
import requests
import json
from difflib import SequenceMatcher

class MetadataManager:
    def __init__(self):
        musicbrainzngs.set_useragent("SIAE_Project_Univ", "0.5", "tuamail@esempio.com")
        self.itunes_url = "https://itunes.apple.com/search"
        self.deezer_search_url = "https://api.deezer.com/search"
        print("📚 Metadata Manager (IT Store Forced) Pronto.")

    def _clean_string(self, text):
        if not text: return ""
        return re.sub(r"[^a-zA-Z0-9\s]", "", text).lower().strip()

    def _clean_title(self, title):
        clean = re.sub(r"[\(\[].*?[\)\]]", "", title)
        patterns = [r"-\s*live", r"live\s*at", r"remaster", r"version", r"edit"]
        for p in patterns:
            clean = re.sub(p, "", clean, flags=re.IGNORECASE)
        return clean.strip()

    def find_composer(self, title, detected_artist, isrc=None, upc=None, setlist_artist=None, raw_acr_meta=None):
        clean_title = self._clean_title(title)
        search_title = clean_title if len(clean_title) > 2 else title
        
        print(f"\n🔎 [META] Cerco Compositore: '{search_title}' (Art: '{detected_artist}')")

        if raw_acr_meta and 'contributors' in raw_acr_meta:
            composers_list = raw_acr_meta['contributors'].get('composers', [])
            if composers_list:
                res_str = ", ".join(composers_list)
                print(f"   💎 ACRCloud Native Match: {res_str}")
                return res_str

        artists_to_try = []
        if setlist_artist: artists_to_try.append(setlist_artist)
        if detected_artist and detected_artist != setlist_artist: artists_to_try.append(detected_artist)

        # 1. MUSICBRAINZ (ISRC)
        if isrc:
            res = self._search_mb_by_isrc(isrc)
            if res: return res

        # 2. MUSICBRAINZ (Testo)
        for artist in artists_to_try:
            res = self._strategy_musicbrainz(search_title, artist)
            if res: return res

        # 3. ITUNES (DEBUGGATO & LOCALIZZATO)
        print("🍏 [Apple] Provo iTunes (Store IT)...")
        for artist in artists_to_try:
            res = self._search_itunes(search_title, artist)
            if res: return f"{res} (Apple)"

        # 4. DEEZER
        print("🎵 [Deezer] Provo Deezer...")
        for artist in artists_to_try:
            res = self._search_deezer(search_title, artist)
            if res: return f"{res} (Deezer)"

        # 5. SPOTIFY RAW (Fallback)
        if raw_acr_meta and 'spotify' in raw_acr_meta:
            print("🟢 [Spotify Raw] Analizzo metadati grezzi...")
            try:
                spotify_data = raw_acr_meta['spotify'] # <--- Accesso diretto alla chiave 'spotify'
                spotify_artists = spotify_data.get('artists', [])
                names = [a.get('name') for a in spotify_artists if 'name' in a]
                
                filtered_names = []
                target_norm = self._clean_string(detected_artist)
                
                for n in names:
                    if self._clean_string(n) not in target_norm:
                        filtered_names.append(n)
                
                if filtered_names:
                    res_str = ", ".join(filtered_names)
                    print(f"   ✅ Spotify Raw Contributors: {res_str}")
                    return f"{res_str} (Spotify Raw)"
            except: pass

        return "Sconosciuto"

    # ---------------------------------------------------------
    # ITUNES (Logica Potenziata)
    # ---------------------------------------------------------
    def _search_itunes(self, title, artist):
        try:
            # Pulizia leggera per la query
            simple_artist = re.sub(r"(?i)\b(feat\.|ft\.|&|the)\b.*", "", artist).strip()
            
            # --- TENTATIVO 1: Query Specifica ---
            params = {
                'term': f"{title} {simple_artist}", 
                'media': 'music', 
                'entity': 'song', 
                'limit': 10,
                'country': 'IT' # <--- FONDAMENTALE
            }
            
            # DEBUG URL
            # print(f"   ► URL iTunes: {self.itunes_url}?term={params['term']}&country=IT")
            
            resp = requests.get(self.itunes_url, params=params, timeout=5)
            results = resp.json().get('results', []) if resp.status_code == 200 else []

            # --- TENTATIVO 2: Solo Titolo (Se 1 fallisce) ---
            if not results:
                print(f"   -> Nessun risultato specifico. Provo solo titolo: '{title}'")
                params['term'] = title
                resp = requests.get(self.itunes_url, params=params, timeout=5)
                results = resp.json().get('results', []) if resp.status_code == 200 else []

            target_norm = self._clean_string(artist)
            
            for i, res in enumerate(results):
                track_name = res.get('trackName', '')
                artist_name = res.get('artistName', '')
                
                # Check Titolo (Fuzzy > 60%)
                if SequenceMatcher(None, title.lower(), track_name.lower()).ratio() < 0.6:
                    # print(f"     X Scartato Titolo: {track_name}")
                    continue
                
                # Check Artista (Flessibile)
                found_art_clean = self._clean_string(artist_name)
                
                # Se l'artista combacia (Lazza in Lazza / Lazza in Lazza & Sfera)
                if target_norm in found_art_clean or found_art_clean in target_norm:
                    if 'composerName' in res:
                        comp = res['composerName']
                        print(f"   ✅ iTunes Match: {comp}")
                        return comp
                    else:
                        print(f"     ⚠️ Trovato brano '{track_name}' ma campo composer vuoto.")
                else:
                    # print(f"     X Scartato Artista: {artist_name} (Cercavo: {artist})")
                    pass
                    
        except Exception as e:
            print(f"   ⚠️ Errore iTunes: {e}")
        return None

    # ---------------------------------------------------------
    # DEEZER
    # ---------------------------------------------------------
    def _search_deezer(self, title, artist):
        try:
            query = f'{title} {artist}'
            params = {'q': query, 'limit': 3}
            
            resp = requests.get(self.deezer_search_url, params=params, timeout=5)
            if resp.status_code != 200: return None
            data = resp.json()
            
            target_norm = self._clean_string(artist)
            title_norm = self._clean_string(title)

            for res in data.get('data', []):
                found_title = self._clean_string(res.get('title', ''))
                if SequenceMatcher(None, title_norm, found_title).ratio() < 0.6: continue
                
                found_artist = self._clean_string(res.get('artist', {}).get('name', ''))
                if target_norm not in found_artist and found_artist not in target_norm: continue

                track_resp = requests.get(f"https://api.deezer.com/track/{res['id']}", timeout=5)
                if track_resp.status_code == 200:
                    contributors = track_resp.json().get('contributors', [])
                    composers = []
                    for p in contributors:
                        if p.get('role') in ['Composer', 'Writer', 'Author']:
                            composers.append(p.get('name'))
                    
                    if composers:
                        return ", ".join(list(set(composers)))
        except: pass
        return None

    # ---------------------------------------------------------
    # MUSICBRAINZ UTILS
    # ---------------------------------------------------------
    def _strategy_musicbrainz(self, title, artist):
        try:
            query = f'recording:"{title}" AND artist:"{artist}"'
            res = musicbrainzngs.search_recordings(query=query, limit=3)
            if res.get('recording-list'):
                for r in res['recording-list']:
                    c = self._get_comp(r['id'])
                    if c: return c
            
            time.sleep(0.5)
            query_w = f'work:"{title}" AND artist:"{artist}"'
            res_w = musicbrainzngs.search_works(query=query_w, limit=3)
            if res_w.get('work-list'):
                return self._extract_comp(res_w['work-list'][0])
        except: pass
        return None

    def _search_mb_by_isrc(self, isrc):
        try:
            res = musicbrainzngs.get_recordings_by_isrc(isrc, includes=['work-rels', 'artist-rels'])
            if res.get('isrc', {}).get('recording-list'):
                return self._extract_comp(res['isrc']['recording-list'][0])
        except: return None

    def _get_comp(self, rid):
        try:
            time.sleep(0.5)
            rec = musicbrainzngs.get_recording_by_id(rid, includes=['work-rels', 'artist-rels'])
            return self._extract_comp(rec['recording'])
        except: return None

    def _extract_comp(self, data):
        comps = set()
        if 'artist-relation-list' in data:
            for r in data['artist-relation-list']:
                if r['type'] in ['composer', 'writer']: comps.add(r['artist']['name'])
        if not comps and 'work-relation-list' in data:
            try:
                wid = data['work-relation-list'][0]['work']['id']
                w = musicbrainzngs.get_work_by_id(wid, includes=['artist-rels'])['work']
                if 'artist-relation-list' in w:
                    for r in w['artist-relation-list']:
                        if r['type'] in ['composer', 'writer', 'lyricist']: comps.add(r['artist']['name'])
            except: pass
        return ", ".join(comps) if comps else None