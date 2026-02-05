import os
import requests
import re
import lyricsgenius
import io
import unicodedata
import threading  # <--- IMPORTANTE: Usiamo il threading nativo
from difflib import SequenceMatcher
from dotenv import load_dotenv
from collections import Counter
from langdetect import detect, LangDetectException

from spotify_manager import SpotifyManager

load_dotenv()

class LyricsManager:
    def __init__(self):
        self.genius_token = os.getenv("GENIUS_ACCESS_TOKEN")
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        
        if self.genius_token:
            # CONFIGURAZIONE ANTI-BLOCCO
            self.genius = lyricsgenius.Genius(
                self.genius_token, 
                verbose=False,
                sleep_time=2.0,  # 2 secondi di pausa tra richieste
                retries=1,       
                timeout=15       # Timeout di 15s per evitare blocchi infiniti
            )
            self.genius.remove_section_headers = True 
        else:
            self.genius = None
            print("⚠️ [Lyrics] GENIUS_ACCESS_TOKEN mancante nel .env")

        self.spotify_bot = SpotifyManager()
        
        self.lyrics_cache = {}
        self.titles_map = {} 
        self.current_artist = None
        self.detected_language_code = None
        
        # NOTA: Abbiamo rimosso self.executor perché usiamo threading diretto

    def update_artist_context(self, artist_name):
        """
        Scarica titoli e testi in background.
        """
        if not artist_name or artist_name == self.current_artist:
            return
        
        self.current_artist = artist_name
        self.lyrics_cache = {}
        self.titles_map = {}
        self.detected_language_code = None 
        
        print(f"📖 [Lyrics] Analisi artista: {artist_name}...")
        
        # MODIFICA: Usiamo un Thread standard invece di Executor
        # Questo evita problemi di inizializzazione e blocchi
        t = threading.Thread(target=self._sync_lyrics_task, args=(artist_name,))
        t.daemon = True # Il thread si chiude se chiudi il programma
        t.start()

    def _sync_lyrics_task(self, artist_name):
        try:
            # 1. Recupero titoli da Spotify
            target_songs = self.spotify_bot.get_artist_complete_data(artist_name)
            
            if not target_songs:
                print(f"⚠️ [Lyrics] Nessun brano su Spotify. Provo fallback Genius.")
                self._fallback_genius_search(artist_name)
                return

            # RILEVAMENTO LINGUA
            self.detected_language_code = self._detect_dominant_language(target_songs)
            print(f"🌍 [Lingua] Impostata lingua dominante: {self.detected_language_code or 'AUTO'}")

            total = len(target_songs)
            print(f"    ↳ Scarico testi per {total} brani (Sequenziale)...")

            count = 0
            
            # --- CICLO FOR DIRETTO ---
            for i, song_title in enumerate(target_songs, 1):
                # Stampa di debug
                print(f"       [{i}/{total}] ⏳ Cerco: {song_title}...", end="\r") 
                
                try:
                    success = self._fetch_single_lyric(song_title, artist_name)
                    
                    if success:
                        count += 1
                        print(f"       [{i}/{total}] ✅ {song_title}           ") 
                    else:
                        print(f"       [{i}/{total}] ⏩ {song_title} (No testo)")
                
                except Exception as e:
                    print(f"       [{i}/{total}] ❌ Errore critico su '{song_title}': {e}")
            
            print(f"✅ [Lyrics] Cache pronta: {count} testi caricati.")

        except Exception as e:
            print(f"❌ [Lyrics] Errore Sync Generale: {e}")

    def _detect_dominant_language(self, titles):
        if not titles: return None
        detected_langs = []
        iso_map = {'it': 'ita', 'en': 'eng', 'es': 'spa', 'fr': 'fre', 'de': 'ger', 'pt': 'por'}

        for t in titles:
            try:
                clean = re.sub(r"[\(\[].*?[\)\]]", "", t).strip()
                if len(clean) > 3:
                    lang = detect(clean)
                    detected_langs.append(lang)
            except LangDetectException: pass

        if not detected_langs: return None
        most_common = Counter(detected_langs).most_common(1)
        if most_common:
            return iso_map.get(most_common[0][0])
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
        except Exception as e:
            print(f"⚠️ Err lyric '{title}': {e}")
            pass
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
                
                self.detected_language_code = self._detect_dominant_language(titles)
                print(f"🌍 [Lingua Fallback] Dominante: {self.detected_language_code or 'AUTO'}")
        except: pass

    # --- ELEVENLABS SCRIBE ---
    def transcribe_and_match(self, audio_buffer):
        if not self.elevenlabs_key: return None
        transcribed_text = self._call_scribe_api(audio_buffer, lang_code=self.detected_language_code)
        if not transcribed_text or len(transcribed_text) < 5: return None
        return self._find_best_match(transcribed_text)

    def _call_scribe_api(self, audio_buffer, lang_code=None):
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {"xi-api-key": self.elevenlabs_key}
        files = {"file": ("audio.wav", audio_buffer, "audio/wav")}
        data = {"model_id": "scribe_v1", "tag_audio_events": "false"}
        if lang_code: data["language_code"] = lang_code

        try:
            response = requests.post(url, headers=headers, files=files, data=data, timeout=10)
            if response.status_code == 200:
                return response.json().get("text", "").strip()
            else:
                print(f"⚠️ [Scribe] Error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"❌ [Scribe] Connection Fail: {e}")
        return None

    def _find_best_match(self, transcript):
        if not self.lyrics_cache: return None
        transcript_clean = transcript.lower().strip()
        if len(transcript_clean) < 15: return None

        for title_key, lyrics in self.lyrics_cache.items():
            if transcript_clean in lyrics:
                return self._package_result(title_key, 100)

        transcript_words = [w for w in transcript_clean.split() if len(w) > 3]
        if len(transcript_words) < 3: return None

        best_ratio = 0.0
        best_title_key = None

        for title_key, lyrics in self.lyrics_cache.items():
            hits = 0
            for word in transcript_words:
                if word in lyrics: hits += 1
            ratio = hits / len(transcript_words)
            if ratio > best_ratio:
                best_ratio = ratio
                best_title_key = title_key

        if best_title_key and best_ratio > 0.65:
            return self._package_result(best_title_key, int(best_ratio * 100))
        return None

    def _package_result(self, title_key, score):
        real_title = self.titles_map[title_key]
        print(f"🧩 [Lyrics MATCH] Identificato: '{real_title}' (Confidence: {score}%)")
        return {
            "status": "success", "title": real_title, "artist": self.current_artist,
            "score": score, "type": "Lyrics Match", "duration_ms": 0,
            "album": "Sconosciuto", "external_metadata": {}, "contributors": {}, "cover": None
        }

    def _normalize_text(self, text):
        if not text: return ""
        text = re.sub(r"[\(\[].*?[\)\]]", "", text)
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        text = re.sub(r"[^a-zA-Z0-9\s]", "", text)
        return text.strip().lower()