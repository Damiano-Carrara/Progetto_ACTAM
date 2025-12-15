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
        print("📚 Metadata Manager (Composer + Cover Mode) Pronto.")

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
        """
        Restituisce una TUPLA: (nome_compositore, url_copertina)
        """
        clean_title = self._clean_title(title)
        search_title = clean_title if len(clean_title) > 2 else title
        
        print(f"\n🔎 [META] Ricerca Dati: '{search_title}' (Art: '{detected_artist}')")

        final_composer = "Sconosciuto"
        final_cover = None

        # 0. ACRCLOUD NATIVE (Ottimo per Compositore)
        if raw_acr_meta and 'contributors' in raw_acr_meta:
            composers_list = raw_acr_meta['contributors'].get('composers', [])
            if composers_list:
                final_composer = ", ".join(composers_list)
                print(f"   💎 ACRCloud Native Composer: {final_composer}")

        # Se ACRCloud (passato da audio_manager) aveva già una cover, potremmo averla qui,
        # ma per sicurezza cerchiamo la versione HD su iTunes/Deezer.

        artists_to_try = []
        if setlist_artist: artists_to_try.append(setlist_artist)
        if detected_artist and detected_artist != setlist_artist: artists_to_try.append(detected_artist)

        # 1. ITUNES (Priorità Cover HD + Compositore)
        # Cerchiamo su iTunes anche se abbiamo già il compositore, per trovare la Cover HD
        if final_cover is None or final_composer == "Sconosciuto":
            print("🍏 [Apple] Provo iTunes (Store IT)...")
            for artist in artists_to_try:
                # Nota: _search_itunes ora restituisce (comp, cover)
                found_comp, found_cover = self._search_itunes(search_title, artist)
                
                if found_cover and not final_cover:
                    final_cover = found_cover
                    print(f"     📸 Cover trovata su iTunes!")
                
                if found_comp and final_composer == "Sconosciuto":
                    final_composer = f"{found_comp} (Apple)"
                
                # Se abbiamo entrambi, possiamo uscire dal loop degli artisti
                if final_cover and final_composer != "Sconosciuto":
                    break

        # 2. DEEZER (Fallback)
        if final_cover is None or final_composer == "Sconosciuto":
            print("🎵 [Deezer] Provo Deezer...")
            for artist in artists_to_try:
                found_comp, found_cover = self._search_deezer(search_title, artist)
                
                if found_cover and not final_cover:
                    final_cover = found_cover
                    print(f"     📸 Cover trovata su Deezer!")
                
                if found_comp and final_composer == "Sconosciuto":
                    final_composer = f"{found_comp} (Deezer)"

                if final_cover and final_composer != "Sconosciuto":
                    break

        # 3. MUSICBRAINZ (Solo Compositore - ISRC)
        # MusicBrainz è lento, lo usiamo solo se manca il compositore
        if final_composer == "Sconosciuto" and isrc:
            res = self._search_mb_by_isrc(isrc)
            if res: final_composer = res

        # 4. MUSICBRAINZ (Solo Compositore - Testo)
        if final_composer == "Sconosciuto":
            for artist in artists_to_try:
                res = self._strategy_musicbrainz(search_title, artist)
                if res: 
                    final_composer = res
                    break

        # 5. SPOTIFY RAW (Fallback solo dati testuali)
        if final_composer == "Sconosciuto" and raw_acr_meta and 'spotify' in raw_acr_meta:
            try:
                spotify_data = raw_acr_meta['spotify']
                spotify_artists = spotify_data.get('artists', [])
                names = [a.get('name') for a in spotify_artists if 'name' in a]
                
                filtered_names = []
                target_norm = self._clean_string(detected_artist)
                for n in names:
                    if self._clean_string(n) not in target_norm:
                        filtered_names.append(n)
                
                if filtered_names:
                    final_composer = f"{', '.join(filtered_names)} (Spotify Raw)"
            except: pass

        return final_composer, final_cover

    # ---------------------------------------------------------
    # ITUNES (Logica Ibrida: Rilassata per Cover, Strict per Comp)
    # ---------------------------------------------------------
    def _search_itunes(self, title, artist):
        try:
            simple_artist = re.sub(r"(?i)\b(feat\.|ft\.|&|the)\b.*", "", artist).strip()
            params = {
                'term': f"{title} {simple_artist}", 
                'media': 'music', 'entity': 'song', 'limit': 10, 'country': 'IT'
            }
            
            resp = requests.get(self.itunes_url, params=params, timeout=5)
            results = resp.json().get('results', []) if resp.status_code == 200 else []

            if not results:
                params['term'] = title
                resp = requests.get(self.itunes_url, params=params, timeout=5)
                results = resp.json().get('results', []) if resp.status_code == 200 else []

            target_norm = self._clean_string(artist)
            
            for res in results:
                track_name = res.get('trackName', '')
                artist_name = res.get('artistName', '')
                
                # Check Titolo
                if SequenceMatcher(None, title.lower(), track_name.lower()).ratio() < 0.6: continue
                
                found_art_clean = self._clean_string(artist_name)
                
                # Check Artista
                if target_norm in found_art_clean or found_art_clean in target_norm:
                    # Trovato! Estraiamo dati.
                    # TRUCCO HD: Sostituisci 100x100 con 600x600 nell'URL
                    cover = res.get('artworkUrl100', '').replace('100x100', '600x600')
                    composer = res.get('composerName', None) # Può essere None
                    
                    if not cover: cover = None # Pulizia
                    
                    return composer, cover
                    
        except Exception as e:
            print(f"   ⚠️ Errore iTunes: {e}")
        return None, None

    # ---------------------------------------------------------
    # DEEZER (Ritorna Tuple)
    # ---------------------------------------------------------
    def _search_deezer(self, title, artist):
        try:
            query = f'{title} {artist}'
            params = {'q': query, 'limit': 3}
            
            resp = requests.get(self.deezer_search_url, params=params, timeout=5)
            if resp.status_code != 200: return None, None
            data = resp.json()
            
            target_norm = self._clean_string(artist)
            title_norm = self._clean_string(title)

            for res in data.get('data', []):
                found_title = self._clean_string(res.get('title', ''))
                if SequenceMatcher(None, title_norm, found_title).ratio() < 0.6: continue
                
                found_artist = self._clean_string(res.get('artist', {}).get('name', ''))
                if target_norm not in found_artist and found_artist not in target_norm: continue

                # Cover immediata
                cover = res.get('album', {}).get('cover_medium', None)
                composer = None

                # Deep search per compositore
                try:
                    track_resp = requests.get(f"https://api.deezer.com/track/{res['id']}", timeout=5)
                    if track_resp.status_code == 200:
                        contributors = track_resp.json().get('contributors', [])
                        comps = []
                        for p in contributors:
                            if p.get('role') in ['Composer', 'Writer', 'Author']:
                                comps.append(p.get('name'))
                        if comps:
                            composer = ", ".join(list(set(comps)))
                except: pass

                return composer, cover
        except: pass
        return None, None

    # ---------------------------------------------------------
    # MUSICBRAINZ (Rimane invariato, ritorna stringa)
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