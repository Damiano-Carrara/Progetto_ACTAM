import os
import requests
import re
import lyricsgenius
import io
import unicodedata
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from collections import Counter
# NUOVO IMPORT
from langdetect import detect, LangDetectException

from spotify_manager import SpotifyManager

load_dotenv()

class LyricsManager:
    def __init__(self):
        self.genius_token = os.getenv("GENIUS_ACCESS_TOKEN")
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        
        if self.genius_token:
            self.genius = lyricsgenius.Genius(self.genius_token, verbose=False)
            self.genius.remove_section_headers = True 
        else:
            self.genius = None
            print("⚠️ [Lyrics] GENIUS_ACCESS_TOKEN mancante nel .env")

        self.spotify_bot = SpotifyManager()
        
        self.lyrics_cache = {}
        self.titles_map = {} 
        self.current_artist = None
        
        # NUOVO: Variabile per la lingua rilevata
        self.detected_language_code = None 
        
        self.executor = ThreadPoolExecutor(max_workers=3)

    def update_artist_context(self, artist_name):
        """
        Scarica titoli e testi, e decide la lingua dominante.
        """
        if not artist_name or artist_name == self.current_artist:
            return
        
        self.current_artist = artist_name
        self.lyrics_cache = {}
        self.titles_map = {}
        self.detected_language_code = None # Reset lingua
        
        print(f"📖 [Lyrics] Analisi artista: {artist_name}...")
        self.executor.submit(self._sync_lyrics_task, artist_name)

    def _sync_lyrics_task(self, artist_name):
        try:
            # 1. Recupero titoli da Spotify
            target_songs = self.spotify_bot.get_artist_complete_data(artist_name)
            
            if not target_songs:
                print(f"⚠️ [Lyrics] Nessun brano su Spotify. Provo fallback Genius.")
                self._fallback_genius_search(artist_name)
                return

            # === NUOVO: RILEVAMENTO LINGUA DAI TITOLI ===
            self.detected_language_code = self._detect_dominant_language(target_songs)
            print(f"🌍 [Lingua] Impostata lingua dominante: {self.detected_language_code or 'AUTO'}")
            # ============================================

            print(f"    ↳ Scarico testi per {len(target_songs)} brani...")

            futures = []
            for song_title in target_songs:
                futures.append(self.executor.submit(self._fetch_single_lyric, song_title, artist_name))
            
            count = 0
            for future in as_completed(futures):
                if future.result():
                    count += 1
            
            print(f"✅ [Lyrics] Cache pronta: {count} testi caricati.")

        except Exception as e:
            print(f"❌ [Lyrics] Errore Sync: {e}")

    def _detect_dominant_language(self, titles):
        """
        Analizza i titoli e restituisce il codice lingua a 3 lettere per Scribe.
        """
        if not titles: return None
        
        detected_langs = []
        
        # Mappa da codice ISO-2 (langdetect) a ISO-3 (ElevenLabs)
        iso_map = {
            'it': 'ita',
            'en': 'eng',
            'es': 'spa',
            'fr': 'fre',
            'de': 'ger',
            'pt': 'por'
        }

        for t in titles:
            try:
                # Pulizia titolo per evitare che "Remix" o "Live" falsino il risultato
                clean = re.sub(r"[\(\[].*?[\)\]]", "", t).strip()
                if len(clean) > 3: # Ignora titoli troppo brevi
                    lang = detect(clean)
                    detected_langs.append(lang)
            except LangDetectException:
                pass

        if not detected_langs: return None

        # Trova la lingua più comune
        most_common = Counter(detected_langs).most_common(1)
        if most_common:
            primary_lang = most_common[0][0]
            # Se la lingua è supportata nella mappa, restituisce il codice a 3 lettere
            # Altrimenti None (che significa AUTO per Scribe)
            return iso_map.get(primary_lang)
            
        return None

    def _fetch_single_lyric(self, title, artist):
        if not self.genius: return False
        try:
            clean_search_title = re.sub(r"\(.*?\)", "", title).strip()
            song = self.genius.search_song(clean_search_title, artist)
            if song:
                norm_key = self._normalize_text(song.title)
                self.lyrics_cache[norm_key] = song.lyrics.lower()
                self.titles_map[norm_key] = song.title
                return True
        except: pass
        return False

    def _fallback_genius_search(self, artist_name):
        try:
            artist = self.genius.search_artist(artist_name, max_songs=10, sort="popularity")
            titles = []
            if artist:
                for song in artist.songs:
                    titles.append(song.title)
                    norm_key = self._normalize_text(song.title)
                    self.lyrics_cache[norm_key] = song.lyrics.lower()
                    self.titles_map[norm_key] = song.title
                
                # Anche qui proviamo a rilevare la lingua
                self.detected_language_code = self._detect_dominant_language(titles)
                print(f"🌍 [Lingua Fallback] Dominante: {self.detected_language_code or 'AUTO'}")
        except: pass

    # --- ELEVENLABS SCRIBE ---

    def transcribe_and_match(self, audio_buffer):
        if not self.elevenlabs_key: return None

        # Passiamo la lingua rilevata
        transcribed_text = self._call_scribe_api(audio_buffer, lang_code=self.detected_language_code)
        
        if not transcribed_text or len(transcribed_text) < 5:
            return None

        return self._find_best_match(transcribed_text)

    def _call_scribe_api(self, audio_buffer, lang_code=None):
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {"xi-api-key": self.elevenlabs_key}
        files = {"file": ("audio.wav", audio_buffer, "audio/wav")}
        
        data = {
            "model_id": "scribe_v1", 
            "tag_audio_events": "false"
        }
        
        # SE abbiamo rilevato una lingua sicura, la imponiamo.
        # Altrimenti non mandiamo il parametro e Scribe va in Auto-Detect.
        if lang_code:
            data["language_code"] = lang_code

        try:
            response = requests.post(url, headers=headers, files=files, data=data, timeout=10)
            if response.status_code == 200:
                text = response.json().get("text", "").strip()
                return text
            else:
                print(f"⚠️ [Scribe] Error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"❌ [Scribe] Connection Fail: {e}")
        return None

    def _find_best_match(self, transcript):
        if not self.lyrics_cache: return None

        transcript_clean = transcript.lower().strip()
        
        # === FIX 1: Ignora frasi troppo brevi ===
        # Se Scribe sente solo "Yeah", "Music", "Oh baby", ignoriamo.
        # Richiediamo almeno 15 caratteri o 4 parole.
        if len(transcript_clean) < 15:
            # print(f"⚠️ [Lyrics] Trascrizione ignorata (troppo breve): '{transcript_clean}'")
            return None
        # ========================================

        best_ratio = 0.0
        best_title_key = None

        # 1. Ricerca esatta (Solo se la frase è lunga e significativa)
        for title_key, lyrics in self.lyrics_cache.items():
            if transcript_clean in lyrics:
                return self._package_result(title_key, 100)

        # 2. Ricerca per parole chiave (Fuzzy)
        # Filtriamo parole comuni o troppo corte per evitare falsi match su "the", "and", "you"
        transcript_words = [w for w in transcript_clean.split() if len(w) > 3]
        
        # === FIX 2: Numero minimo di parole significative ===
        if len(transcript_words) < 3: 
            return None
        # ====================================================

        for title_key, lyrics in self.lyrics_cache.items():
            hits = 0
            for word in transcript_words:
                # Cerca la parola esatta (con bordi) per evitare che "cat" matchi "cation"
                # O semplicemente controlla l'inclusione se vuoi essere più permissivo
                if word in lyrics:
                    hits += 1
            
            ratio = hits / len(transcript_words)
            if ratio > best_ratio:
                best_ratio = ratio
                best_title_key = title_key

        # Alziamo la soglia minima al 65% per sicurezza
        if best_title_key and best_ratio > 0.65:
            return self._package_result(best_title_key, int(best_ratio * 100))
            
        return None

    def _package_result(self, title_key, score):
        real_title = self.titles_map[title_key]
        print(f"🧩 [Lyrics MATCH] Identificato: '{real_title}' (Confidence: {score}%)")
        return {
            "status": "success",
            "title": real_title,
            "artist": self.current_artist,
            "score": score,
            "type": "Lyrics Match",
            "duration_ms": 0,          # Scribe non sa la durata
            "album": "Sconosciuto",    # Placeholder esplicito
            "external_metadata": {},   # Chiave vuota ma presente
            "contributors": {},        # Chiave vuota ma presente
            "cover": None              # Chiave vuota ma presente
        }

    def _normalize_text(self, text):
        if not text: return ""
        text = re.sub(r"[\(\[].*?[\)\]]", "", text)
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        text = re.sub(r"[^a-zA-Z0-9\s]", "", text)
        return text.strip().lower()