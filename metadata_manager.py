import musicbrainzngs
import time
import re
import requests
import json
from difflib import SequenceMatcher
import lyricsgenius
import os
from spotify_manager import SpotifyManager  # <--- NUOVO IMPORT

class MetadataManager:
    def __init__(self):
        # Configurazione MusicBrainz
        musicbrainzngs.set_useragent("SIAE_Project_Univ", "0.5", "tuamail@esempio.com")
        
        self.itunes_url = "https://itunes.apple.com/search"
        self.deezer_search_url = "https://api.deezer.com/search"
        
        # Configurazione Genius
        self.genius_token = os.getenv("GENIUS_ACCESS_TOKEN")
        self.genius = None 
        
        # Inizializzazione Spotify
        self.spotify_bot = SpotifyManager()

        print("📚 Metadata Manager (iTunes + Spotify HD + Genius + MB) Pronto.")

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
        Cerca metadati avanzati (Compositore e Cover HD).
        Sequenza: Spotify (Cover) -> iTunes (Comp+Cover) -> ACR -> MB -> Genius -> Deezer
        """
        clean_title = self._clean_title(title)
        search_title = clean_title if len(clean_title) > 2 else title
        
        print(f"\n🔎 [META] Cerco Dettagli per: '{search_title}' (Art: '{detected_artist}')")

        final_composer = "Sconosciuto"
        final_cover = None
        
        artists_to_try = []
        if setlist_artist: artists_to_try.append(setlist_artist)
        if detected_artist and detected_artist != setlist_artist: artists_to_try.append(detected_artist)

        # ---------------------------------------------------------
        # 1. SPOTIFY (COVER HD - PRIORITÀ ASSOLUTA)
        # ---------------------------------------------------------
        # Usiamo Spotify per la cover perché ha la qualità migliore (640x640)
        # Purtroppo Spotify NON fornisce i compositori via API.
        if self.spotify_bot:
            try:
                # Proviamo col primo artista della lista (solitamente il più corretto)
                hd_cover = self.spotify_bot.get_hd_cover(search_title, artists_to_try[0])
                if hd_cover:
                    final_cover = hd_cover
                    # print("     🎨 [Spotify] Cover HD trovata.")
            except: pass

        # ---------------------------------------------------------
        # 2. ITUNES (COMPOSITORE + FALLBACK COVER)
        # ---------------------------------------------------------
        # iTunes è ottimo per i compositori ("Written By").
        print("🍏 [Apple] Provo iTunes (Store IT)...")
        for artist in artists_to_try:
            comp, cover = self._search_itunes(search_title, artist)
            
            # Se Spotify ha fallito, prendiamo la cover di iTunes
            if cover and not final_cover:
                final_cover = cover
            
            if comp:
                final_composer = f"{comp} (Apple)"
                print(f"     ✅ Compositore trovato su iTunes: {comp}")
                break # Trovato compositore, usciamo dal loop artisti

        # ---------------------------------------------------------
        # 3. ACRCLOUD NATIVE (FALLBACK)
        # ---------------------------------------------------------
        if final_composer == "Sconosciuto" and raw_acr_meta and "contributors" in raw_acr_meta:
            composers_list = raw_acr_meta["contributors"].get("composers", [])
            if composers_list:
                final_composer = ", ".join(composers_list)
                print(f"   💎 ACRCloud Native Match: {final_composer}")

        # ---------------------------------------------------------
        # 4. MUSICBRAINZ (PRECISIONE STORICA)
        # ---------------------------------------------------------
        if final_composer == "Sconosciuto":
            # A) Via ISRC
            if isrc:
                res = self._search_mb_by_isrc(isrc)
                if res: final_composer = res

            # B) Via Testo
            if final_composer == "Sconosciuto":
                for artist in artists_to_try:
                    res = self._strategy_musicbrainz(search_title, artist)
                    if res: 
                        final_composer = res
                        break

        # ---------------------------------------------------------
        # 5. GENIUS (ULTIMA SPIAGGIA POTENTE)
        # ---------------------------------------------------------
        if final_composer == "Sconosciuto":
            print("🧠 [Genius] Avvio ricerca approfondita crediti...")
            for artist in artists_to_try:
                found_genius = self._search_genius_composers(search_title, artist)
                if found_genius:
                    final_composer = f"{found_genius} (Genius)"
                    break

        # ---------------------------------------------------------
        # 6. DEEZER (DISPERATO)
        # ---------------------------------------------------------
        if final_cover is None or final_composer == "Sconosciuto":
            # print("🎵 [Deezer] Tentativo finale...")
            for artist in artists_to_try:
                comp, cover = self._search_deezer(search_title, artist)
                if cover and not final_cover: final_cover = cover
                if comp and final_composer == "Sconosciuto": final_composer = f"{comp} (Deezer)"
                if final_cover and final_composer != "Sconosciuto": break

        return final_composer, final_cover

    # ---------------------------------------------------------
    # MOTORI DI RICERCA
    # ---------------------------------------------------------

    def _search_genius_composers(self, title, artist):
        """Cerca Autori e Produttori su Genius con logica 'Fuzzy'"""
        try:
            if not self.genius_token:
                print("     ❌ [Genius] Token mancante (.env).")
                return None
                
            if self.genius is None:
                self.genius = lyricsgenius.Genius(self.genius_token)
                self.genius.verbose = False 
            
            # Pulizia titolo per Genius (toglie featuring e parentesi)
            clean_t = title.split("(")[0].strip()
            
            # 1. Ricerca Esatta (Titolo + Artista)
            song = self.genius.search_song(clean_t, artist)
            
            # 2. Fallback: Cerca solo Titolo (se l'artista su Genius ha un nome diverso)
            if not song:
                # print(f"     ⚠️ Genius: Ricerca esatta fallita. Provo solo '{clean_t}'...")
                # Cerca top 5 risultati solo per titolo
                search_res = self.genius.search_songs(clean_t, per_page=5)
                if search_res and 'hits' in search_res:
                    for hit in search_res['hits']:
                        hit_artist = hit['result']['primary_artist']['name']
                        # Se l'artista trovato contiene quello che cerchiamo (o viceversa)
                        if self._clean_string(artist) in self._clean_string(hit_artist):
                            # Trovato match indiretto! Scarichiamo i dettagli
                            song = self.genius.song(hit['result']['id'])
                            # print(f"     ✅ Genius: Match recuperato ({hit_artist})")
                            break
            
            if not song:
                return None

            # Estrazione Dati
            res = song.to_dict()
            writers = res.get('writer_artists', [])
            producers = res.get('producer_artists', [])
            
            names = set()
            for w in writers: names.add(w['name'])
            # Opzionale: aggiungi produttori se non ci sono scrittori
            if not names:
                for p in producers: names.add(p['name'])
            
            if names:
                return ", ".join(list(names))

        except Exception as e:
            print(f"     ⚠️ Errore Genius: {e}")
        
        return None

    def _search_itunes(self, title, artist):
        try:
            simple_artist = re.sub(r"(?i)\b(feat\.|ft\.|&|the)\b.*", "", artist).strip()
            params = {
                "term": f"{title} {simple_artist}",
                "media": "music",
                "entity": "song",
                "limit": 5,
                "country": "IT",
            }
            resp = requests.get(self.itunes_url, params=params, timeout=5)
            results = resp.json().get("results", []) if resp.status_code == 200 else []

            # Fallback solo titolo
            if not results:
                params["term"] = title
                resp = requests.get(self.itunes_url, params=params, timeout=5)
                results = resp.json().get("results", []) if resp.status_code == 200 else []

            target_norm = self._clean_string(artist)
            
            for res in results:
                track_name = res.get("trackName", "")
                artist_name = res.get("artistName", "")
                
                # Check Titolo
                if SequenceMatcher(None, title.lower(), track_name.lower()).ratio() < 0.6: 
                    continue
                
                # Check Artista
                found_art_clean = self._clean_string(artist_name)
                if target_norm in found_art_clean or found_art_clean in target_norm:
                    cover = res.get('artworkUrl100', '').replace('100x100', '600x600')
                    composer = res.get('composerName')
                    if cover or composer:
                        return composer, cover
        except: pass
        return None, None

    def _search_deezer(self, title, artist):
        try:
            query = f"{title} {artist}"
            params = {"q": query, "limit": 3}
            resp = requests.get(self.deezer_search_url, params=params, timeout=4)
            if resp.status_code != 200: return None, None
            
            data = resp.json()
            target_norm = self._clean_string(artist)
            title_norm = self._clean_string(title)

            for res in data.get("data", []):
                found_title = self._clean_string(res.get("title", ""))
                if SequenceMatcher(None, title_norm, found_title).ratio() < 0.6: continue
                
                found_artist = self._clean_string(res.get("artist", {}).get("name", ""))
                if target_norm not in found_artist and found_artist not in target_norm: continue

                cover = res.get('album', {}).get('cover_medium', None)
                composer = None
                
                # Deep scan per compositori
                try:
                    track_resp = requests.get(f"https://api.deezer.com/track/{res['id']}", timeout=3)
                    if track_resp.status_code == 200:
                        contributors = track_resp.json().get("contributors", [])
                        comps_list = []
                        for p in contributors:
                            if p.get("role") in ["Composer", "Writer", "Author"]:
                                comps_list.append(p.get("name"))
                        if comps_list:
                            composer = ", ".join(list(set(comps_list)))
                except: pass
                
                if cover or composer:
                    return composer, cover
        except: pass
        return None, None

    def _strategy_musicbrainz(self, title, artist):
        try:
            # 1. Cerca Recording
            query = f'recording:"{title}" AND artist:"{artist}"'
            res = musicbrainzngs.search_recordings(query=query, limit=3)
            if res.get("recording-list"):
                for r in res["recording-list"]:
                    c = self._get_comp(r["id"])
                    if c: return c
            
            # 2. Cerca Work
            time.sleep(0.5) 
            query_w = f'work:"{title}" AND artist:"{artist}"'
            res_w = musicbrainzngs.search_works(query=query_w, limit=3)
            if res_w.get("work-list"):
                return self._extract_comp(res_w["work-list"][0])
        except: pass
        return None

    def _search_mb_by_isrc(self, isrc):
        try:
            res = musicbrainzngs.get_recordings_by_isrc(isrc, includes=["work-rels", "artist-rels"])
            if res.get("isrc", {}).get("recording-list"):
                return self._extract_comp(res["isrc"]["recording-list"][0])
        except: return None

    def _get_comp(self, rid):
        try:
            time.sleep(0.5)
            rec = musicbrainzngs.get_recording_by_id(rid, includes=["work-rels", "artist-rels"])
            return self._extract_comp(rec["recording"])
        except: return None

    def _extract_comp(self, data):
        comps = set()
        if "artist-relation-list" in data:
            for r in data["artist-relation-list"]:
                if r["type"] in ["composer", "writer"]:
                    comps.add(r["artist"]["name"])
        
        if not comps and "work-relation-list" in data:
            try:
                wid = data["work-relation-list"][0]["work"]["id"]
                w = musicbrainzngs.get_work_by_id(wid, includes=["artist-rels"])["work"]
                if "artist-relation-list" in w:
                    for r in w["artist-relation-list"]:
                        if r["type"] in ["composer", "writer", "lyricist"]:
                            comps.add(r["artist"]["name"])
            except: pass
            
        return ", ".join(comps) if comps else None