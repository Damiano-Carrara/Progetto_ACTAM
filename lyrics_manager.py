import os
import requests
import re
import lyricsgenius
import io
import unicodedata
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from collections import Counter
from langdetect import detect, LangDetectException
from spotify_manager import SpotifyManager

load_dotenv()

class LyricsManager:
    def __init__(self):
        self.genius_token = os.getenv("GENIUS_ACCESS_TOKEN")
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")

         # Rotazione tra user agents per evitare blocchi IP da Genius.
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        ]
        
        if self.genius_token:
            # 1. CONFIGURAZIONE "CAMUFFATA"
            self.genius = lyricsgenius.Genius(
                self.genius_token, 
                verbose=False,
                skip_non_songs=True,
                excluded_terms=["(Remix)", "(Live)", "(Instrumental)", "(Mix)"], # Filtro versioni alternative
                remove_section_headers=True,
                retries=2,
                timeout=10,
                sleep_time=0.1
            )
            
            # SELEZIONE RANDOM DELL'AGENTE
            chosen_agent = random.choice(self.user_agents)
            print(f"🕵️ [Stealth] User-Agent attivo: {chosen_agent[:30]}...")
            
            self.genius._session.headers.update({
                "User-Agent": chosen_agent
            })
        else:
            self.genius = None

        self.spotify_bot = SpotifyManager()
        self.lyrics_cache = {}
        self.titles_map = {} 
        self.current_artist = None
        self.detected_language_code = None
        
        # 2. Limitazione a 2 thread per evitare di sovraccaricare Genius e ridurre il rischio di ban IP.
        self.executor = ThreadPoolExecutor(max_workers=2)

    # Costruzione contesto artista bias
    def update_artist_context(self, artist_name):
        if not artist_name or artist_name == self.current_artist:
            return
        
        self.current_artist = artist_name
        self.lyrics_cache = {}
        self.titles_map = {}
        self.detected_language_code = None 
        
        print(f"📖 [Lyrics] Analisi artista: {artist_name}...")
        self.executor.submit(self._async_lyrics_flow_smart, artist_name)

    # Download testi asincrono
    def _async_lyrics_flow_smart(self, artist_name):
        start_time = time.time()
        try:
            print(f"    ⏳ [00s] Contatto Spotify...")
            all_songs = self.spotify_bot.get_artist_complete_data(artist_name)
            
            # 3. FILTRO INTELLIGENTE PRE-GENIUS
            # Rimuoviamo duplicati o versioni strumentali PRIMA di chiamare Genius
            target_songs = []
            seen_titles = set()
            for song in all_songs[:50]: # Analizziamo 50 canzoni
                clean = song.lower().split(' - ')[0] # Prendi solo il titolo base
                if clean not in seen_titles and "instrumental" not in clean and "karaoke" not in clean:
                    target_songs.append(song)
                    seen_titles.add(clean)
            
            # Limitiamo a 30 brani "buoni" (lunghezza tipica di un live)
            target_songs = target_songs[:30]
            
            spotify_time = time.time() - start_time
            total = len(target_songs)
            print(f"    🚀 [Genius] Download SMART (2 thread) per {total} brani...")

            future_to_song = {
                self.executor.submit(self._fetch_single_lyric_smart, song, artist_name): song 
                for song in target_songs
            }
            
            count = 0
            for i, future in enumerate(as_completed(future_to_song), 1):
                song_title = future_to_song[future]
                try:
                    success = future.result()
                    if success: count += 1
                    if i % 5 == 0: print(f"       [{i}/{total}] ...processing...") # Log indica il progresso a gruppi di 5
                except Exception: pass
            
            total_time = time.time() - start_time
            print(f"🏁 [Lyrics] FINITO in {total_time:.1f}s. Cache: {count}/{total} testi.")

        except Exception as e:
            print(f"❌ [Lyrics] Errore Flow: {e}")

    # Versione SEQUENZIALE più lenta ma più "umana" per fallback o artisti con molti brani.
    def _sync_lyrics_flow(self, artist_name):
        start_time = time.time()
        try:
            print(f"    ⏳ [00s] Contatto Spotify...")
            all_songs = self.spotify_bot.get_artist_complete_data(artist_name)
            
            spotify_time = time.time() - start_time
            print(f"    ✅ [{spotify_time:.1f}s] Spotify: Trovati {len(all_songs)} brani.")

            if not all_songs:
                print(f"⚠️ [Lyrics] Nessun brano su Spotify. Provo fallback Genius.")
                self._fallback_genius_search(artist_name)
                return

            limit = 40
            target_songs = all_songs[:limit] if len(all_songs) > limit else all_songs

            self.detected_language_code = self._detect_dominant_language(target_songs)
            
            total = len(target_songs)
            print(f"    🐌 [Genius] Avvio download SAFE (Sequenziale) per {total} brani...")

            count = 0
            
            # LOOP SEQUENZIALE
            for i, song_title in enumerate(target_songs, 1):
                try:
                    success = self._fetch_single_lyric_safe(song_title, artist_name)
                    elapsed = time.time() - start_time - spotify_time
                    
                    if success:
                        count += 1
                        print(f"       [{i}/{total}] ✅ {song_title}")
                    else:
                        print(f"       [{i}/{total}] ⏩ {song_title} (No testo)")
                    
                    # SLEEP DINAMICO: Aspetta tra 2 e 5 secondi tra una chiamata e l'altra (per evitare ban IP)
                    sleep_duration = random.uniform(2.0, 5.0)
                    time.sleep(sleep_duration)

                except Exception as e:
                    print(f"       [{i}/{total}] ❌ {song_title} - {e}")
            
            total_time = time.time() - start_time
            print(f"🏁 [Lyrics] FINITO in {total_time:.1f}s. Cache: {count}/{total} testi.")

        except Exception as e:
            print(f"❌ [Lyrics] Errore Flow: {e}")

    # Download del singolo testo con approccio "smart" (multithreaded e con filtro pre-Genius)
    def _fetch_single_lyric_smart(self, title, artist):
        if not self.genius: return False
        
        # 4. PAUSA CASUALE "UMANA"
        time.sleep(random.uniform(1.0, 3.5)) 
        
        try:
            clean_search_title = re.sub(r"\(.*?\)", "", title).strip()
            song = self.genius.search_song(clean_search_title, artist)
            if song:
                norm_key = self._normalize_text(song.title)
                self.lyrics_cache[norm_key] = song.lyrics.lower()
                self.titles_map[norm_key] = song.title
                return True
        except Exception:
            pass
        return False
    
    # Download del singolo testo con approccio "safe" (sequenziale e con sleep più lungo)
    def _fetch_single_lyric_safe(self, title, artist):
        if not self.genius: return False
        try:
            clean_search_title = re.sub(r"\(.*?\)", "", title).strip()
            song = self.genius.search_song(clean_search_title, artist)
            if song:
                norm_key = self._normalize_text(song.title)
                self.lyrics_cache[norm_key] = song.lyrics.lower()
                self.titles_map[norm_key] = song.title
                return True
        except Exception:
            pass
        return False
    
    # Metodo per rilevare la lingua dominante dei titoli delle canzoni (per migliorare la trascrizione con ElevenLabs Scribe)
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

    # Metodo di fallback per cercare testi direttamente da Genius usando l'API dell'artista (utile se Spotify non restituisce risultati o per artisti con molti brani)
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
        except: pass

    # --- ELEVENLABS SCRIBE ---
    # Metodo principale per trascrivere l'audio e cercare la miglior corrispondenza nei testi scaricati
    def transcribe_and_match(self, audio_buffer):
        if not self.elevenlabs_key: return None
        transcribed_text = self._call_scribe_api(audio_buffer, lang_code=self.detected_language_code)
        if not transcribed_text or len(transcribed_text) < 5: return None
        return self._find_best_match(transcribed_text)

    # Chiamata API Scribe
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

    # Ricerca miglior corrispondenza tra la trascrizione e i testi scaricati
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

    # Metodo per formattare il risultato finale con le informazioni del brano trovato
    def _package_result(self, title_key, score):
        real_title = self.titles_map[title_key]
        print(f"🧩 [Lyrics MATCH] Identificato: '{real_title}' (Confidence: {score}%)")
        return {
            "status": "success", "title": real_title, "artist": self.current_artist,
            "score": score, "type": "Lyrics Match", "duration_ms": 0,
            "album": "Sconosciuto", "external_metadata": {}, "contributors": {}, "cover": None
        }

    # Normalizzazione titoli
    def _normalize_text(self, text):
        if not text: return ""
        text = re.sub(r"[\(\[].*?[\)\]]", "", text)
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        text = re.sub(r"[^a-zA-Z0-9\s]", "", text)
        return text.strip().lower()