import os
import time
import hmac
import hashlib
import base64
import json
import requests
import sounddevice as sd
import scipy.io.wavfile as wav
from scipy import signal
import numpy as np
from dotenv import load_dotenv
import threading
import io
import re
import unicodedata
from collections import deque
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor

# Import bot managers
from spotify_manager import SpotifyManager
from setlist_manager import SetlistManager
from lyrics_manager import LyricsManager

load_dotenv()

class AudioManager:
    def __init__(self, callback_function=None):
        """
        Inizializza il gestore audio ibrido (ACRCloud + Scribe).
        """
        # --- 1. CONFIGURAZIONE CREDENZIALI ---
        self.host = os.getenv("ACRCLOUD_HOST") or os.getenv("ACR_HOST")
        self.access_key = os.getenv("ACRCLOUD_ACCESS_KEY") or os.getenv("ACR_ACCESS_KEY")
        self.access_secret = os.getenv("ACRCLOUD_SECRET_KEY") or os.getenv("ACR_ACCESS_SECRET")
        
        # --- 2. CONFIGURAZIONE SESSIONE HTTP ---
        self.session = requests.Session()
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # --- 3. CONFIGURAZIONE STREAMING AUDIO ---
        self.sample_rate = 44100
        self.window_duration = 12  # Secondi di audio da inviare
        self.block_size = 4096
        
        # Velocità di invio dinamica: 6s, scala a 10s se rete lenta, torna a 6s se veloce
        self.overlap_interval = 6 

        self.audio_buffer = deque(
            maxlen=int((self.sample_rate * self.window_duration) / self.block_size) + 10
        )
        self.history_buffer = deque(maxlen=10)

        # --- 4. STATO E VARIABILI ---
        self.is_running = False
        self.stream = None
        self.monitor_thread = None
        self.result_callback = callback_function 
        self.target_artist_bias = None
        self.low_quality_mode = False
        self.upload_lock = threading.Lock()
        
        self.context_ready = False 
        self.predicted_next_song = None
        self.cycle_counter = 0

        # --- 5. INIZIALIZZAZIONE BOT ---
        print("🤖 Inizializzazione Bot...")
        self.executor = ThreadPoolExecutor(max_workers=4) # 4 workers per gestire ACR + Scribe
        
        self.setlist_bot = SetlistManager()
        self.spotify_bot = SpotifyManager()
        self.lyrics_bot = LyricsManager()

        print("🎤 Audio Manager Pronto. Modalità: Ibrida (ACRCloud + Scribe).")

    def update_target_artist(self, artist_name):
        """
        Scarica il contesto completo: Setlist.fm + Spotify + Genius.
        """
        # Se è lo stesso artista e abbiamo già dati pronti, evitiamo di rifare tutto
        # Normalizziamo le stringhe per sicurezza
        curr_artist_norm = (self.target_artist_bias or "").strip().lower()
        new_artist_norm = (artist_name or "").strip().lower()

        # Se l'artista richiesto è lo stesso che abbiamo già in memoria...
        if new_artist_norm and new_artist_norm == curr_artist_norm:
            # ...e se abbiamo effettivamente dei dati caricati (context_ready o cache popolata)
            if self.context_ready or len(self.setlist_bot.cached_songs) > 0:
                # Saltiamo il processo di download e preparazione, mantenendo il contesto già pronto
                print(f"✅ [Context] Dati per '{artist_name}' già in memoria (da Prefetch). Skip download.")
                return

        # Aggiornamento immediato Bias e Reset stato
        self.target_artist_bias = artist_name
        self.context_ready = False 
        self.predicted_next_song = None
        
        # Pulizia cache precedente (importante per evitare contaminazioni tra artisti)
        self.setlist_bot.cached_songs = []
        self.setlist_bot.concert_sequences = []
        print(f"🧹 [Context] Cache precedente svuotata.")

        if artist_name:
            def fetch_full_context():
                print(f"\n🎸 [Context] Avvio scansione completa per: {artist_name}")
                
                # 1. SETLIST.FM (download scaletta concerti più recenti e frequenti)
                songs_setlist = self.setlist_bot.get_likely_songs(artist_name)
                
                # 2. SPOTIFY (download brani più popolari e recenti)
                songs_spotify = self.spotify_bot.get_artist_complete_data(artist_name)
                
                # 3. FUSIONE LISTE
                merged_songs = set(songs_setlist + songs_spotify)
                
                if merged_songs:
                    self.setlist_bot.cached_songs = list(merged_songs)
                    print(f"✅ [Context] White List audio pronta: {len(merged_songs)} brani.")
                else:
                    print("⚠️ [Context] Nessun brano trovato per Audio Fingerprint.")
                
                # 4. GENIUS / SCRIBE (Download testi dei brani per utilizzo in Scribe)
                self.lyrics_bot.update_artist_context(artist_name)
                
                self.context_ready = True

            self.executor.submit(fetch_full_context)
        else:
            print("⚪ [Context] Nessun artista target. Modalità generica attiva.")

    # Callback del flusso audio: acquisisce i dati e li mette in un buffer per l'elaborazione
    def _audio_callback(self, indata, frames, time, status):
        if status and "overflow" not in str(status):
            print(f"⚠️ Audio Status: {status}")
        self.audio_buffer.append(indata.copy())

    # Preprocessamento audio: filtro passa-alto, normalizzazione e conversione a 16-bit PCM
    def _preprocess_audio_chunk(self, full_audio_data):
        if full_audio_data.dtype != np.float32:
            data = full_audio_data.astype(np.float32)
        else:
            data = full_audio_data

        # Filtro passa-alto (80Hz)
        sos = signal.butter(10, 80, "hp", fs=self.sample_rate, output="sos")
        filtered = signal.sosfilt(sos, data, axis=0)

        max_val = np.max(np.abs(filtered))
        if max_val > 0:
            normalized = filtered / max_val * 0.95
        else:
            normalized = filtered

        return (normalized * 32767).astype(np.int16)

    # Metodo principale di processamento: gestisce la logica di invio ad ACRCloud e Scribe, arbitraggio e callback
    def _process_window(self):
        # Acquisizione Lock (evita sovrapposizioni)
        if not self.upload_lock.acquire(blocking=False):
            return

        try:
            if not self.audio_buffer: return
            try:
                full_recording = np.concatenate(list(self.audio_buffer))
            except ValueError: return

            if len(full_recording) < self.sample_rate * (self.window_duration - 1):
                return

            processed_audio = self._preprocess_audio_chunk(full_recording)
            
            # Gestione Low Quality (Rete lenta): riduzione a 8kHz e bitrate più basso
            if self.low_quality_mode:
                TARGET_RATE = 8000
                num_samples = int(len(processed_audio) * TARGET_RATE / self.sample_rate)
                final_audio = signal.resample(processed_audio, num_samples).astype(np.int16)
                write_rate = TARGET_RATE
            else:
                final_audio = processed_audio
                write_rate = self.sample_rate

            wav_buffer = io.BytesIO()
            wav.write(wav_buffer, write_rate, final_audio)
            wav_buffer.seek(0)
            
            # Incremento contatore cicli per gestione Scribe ogni 3 cicli
            self.cycle_counter += 1
            # Esegui Scribe solo se c'è un artista target E siamo ogni 3 cicli
            run_scribe = (self.target_artist_bias is not None) and (self.cycle_counter % 3 == 0)

            status_msg = f"📡 Analisi [ACR"
            if run_scribe: status_msg += " + SCRIBE"
            status_msg += f"] ({self.overlap_interval}s)..."
            print(status_msg)

            # 1. Lancia ACRCloud (Sempre)
            future_acr = self.executor.submit(self._call_acr_api, wav_buffer, self.target_artist_bias)
            
            # 2. Lancia Scribe (ogni 3 cicli))
            future_scribe = None
            if run_scribe:
                scribe_buffer = io.BytesIO(wav_buffer.getvalue())
                future_scribe = self.executor.submit(self.lyrics_bot.transcribe_and_match, scribe_buffer)

            # Raccolta Risultati
            acr_result = future_acr.result() 
            scribe_result = future_scribe.result() if future_scribe else None
            
            final_track = None
            is_fast_track = False 
            
            # Parsing ACR
            acr_best = None
            acr_score = 0
            if acr_result.get("status") == "multiple_results":
                acr_best = acr_result["tracks"][0]
                acr_score = acr_best.get("score", 0)

            scribe_score = scribe_result.get("score", 0) if scribe_result else 0

            # DECISIONE FINALE: ARBITRAGGIO TRA ACR E SCRIBE

            # A. FAST TRACK (Conferma Reciproca Assoluta)
            if scribe_result and acr_best:
                if scribe_score > 75 and acr_score > 98:
                    if self._are_tracks_equivalent(scribe_result, acr_best):
                        print(f"⚡ [FAST TRACK] Match Assoluto! Scribe ({scribe_score}%) + ACR ({acr_score}%)")
                        final_track = scribe_result
                        final_track["external_metadata"] = acr_best.get("external_metadata")
                        final_track["cover"] = acr_best.get("cover")
                        is_fast_track = True

            # B. STANDARD (Scribe affidabile o ACR come backup)
            if not final_track:
                # Caso 1: Scribe è molto affidabile (>65%). VINCE LUI.
                if scribe_result and scribe_score > 65:
                    print(f"🥇 [SCRIBE WIN] Analisi Testuale ({scribe_score}%) ha priorità.")
                    final_track = scribe_result
                    # Arricchimento dati da ACR se disponibile
                    if acr_best and self._are_tracks_equivalent(scribe_result, acr_best):
                        final_track["external_metadata"] = acr_best.get("external_metadata")
                        final_track["cover"] = acr_best.get("cover")

                # Caso 2: Scribe assente, usiamo ACRCloud classico
                elif acr_best:
                    print(f"🔊 [ACR WIN] Audio Fingerprint: {acr_best['title']} ({acr_score}%)")
                    final_track = acr_best

            # --- INVIO DATI E STABILITÀ ---
            if final_track:
                # Filtro Latin (I brani con titoli non Latin rsono spesso falsi positivi, meglio scartarli per stabilità)
                if not self._is_mostly_latin(final_track["title"]):
                    print(f"🐉 Scartato brano non-Latin: {final_track['title']}")
                    return

                display_title = self._clean_title_for_display(final_track["title"])
                
                # CASO FAST TRACK: INVIO IMMEDIATO SENZA CONTROLLO STABILITÀ (conferma reciproca molto forte)
                if is_fast_track:
                      if self.result_callback:
                        final_data = final_track.copy()
                        final_data["title"] = display_title
                        final_data["artist"] = self._get_artist_name(final_track)
                        self.result_callback(final_data, target_artist=self.target_artist_bias)
                        self.history_buffer.clear() # Reset stabilità
                        
                        # Veggente (prevede il prossimo brano basato su scaletta e contesto)
                        self._update_prediction(display_title)
                        return

                # CASO NORMALE: CONTROLLO DI STABILITÀ (Ho bisognp di un'ulteriore conferma per evitare falsi positivi)
                current_obj = {
                    "title": final_track["title"],
                    "artist": self._get_artist_name(final_track),
                    "duration_ms": final_track.get("duration_ms", 0),
                }
                
                self.history_buffer.append(current_obj)
                
                stability_count = 0
                for historical_item in self.history_buffer:
                    if self._are_tracks_equivalent(current_obj, historical_item):
                        stability_count += 1
                
                # Soglia standard di stabilità (2 conferme nelle ultime 10 rilevazioni)
                threshold = 2

                if stability_count >= threshold:
                    print(f"🛡️ Conferma stabilità ({stability_count}/{threshold}): {display_title}")
                    if self.result_callback:
                        final_data = final_track.copy()
                        final_data["title"] = display_title
                        final_data["artist"] = self._get_artist_name(final_track)
                        
                        if not final_data.get("cover"):
                            final_data["cover"] = self._extract_best_cover(final_data)

                        self.result_callback(final_data, target_artist=self.target_artist_bias)
                        
                        # Veggente (aggiorno predizione)
                        self._update_prediction(display_title)
                        
        except Exception as e:
            print(f"❌ Errore processamento window: {e}")
        finally:
            self.upload_lock.release()

    # LOGICA VEGGENTE (PREDIZIONE PROSSIMO BRANO IN BASE A SCALETTA E CONTESTO)
    def _update_prediction(self, current_title):
        """Helper per aggiornare il Veggente"""
        clean_title_pred = self._clean_title_for_display(current_title)
        next_prediction = self.setlist_bot.predict_next(clean_title_pred)
        if next_prediction:
            self.predicted_next_song = next_prediction
            print(f"🔮 [VEGGENTE] Riconosciuto '{current_title}'. Mi aspetto '{next_prediction}' tra poco!")
        else:
            self.predicted_next_song = None

    # Logica del ciclo di monitoraggio: ogni X secondi (con dinamica di rete) processa una finestra di audio e lancia l'analisi
    def _loop_logic(self):
        print("⏱️ Avvio ciclo di monitoraggio dinamico...")
        time.sleep(self.window_duration)
        while self.is_running:
            threading.Thread(target=self._process_window).start()
            time.sleep(self.overlap_interval)

    # Avvio del monitoraggio
    def start_continuous_recognition(self, callback_function, target_artist=None):
        if self.is_running: return False
        self.is_running = True
        self.result_callback = callback_function
        self.target_artist_bias = target_artist
        self.audio_buffer.clear()
        self.history_buffer.clear()
        self.low_quality_mode = False
        self.overlap_interval = 6
        self.cycle_counter = 0

        self.stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1,
            blocksize=self.block_size, callback=self._audio_callback,
        )
        self.stream.start()
        self.monitor_thread = threading.Thread(target=self._loop_logic)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        return True

    # Metodo per fermare il monitoraggio continuo e liberare risorse
    def stop_continuous_recognition(self):
        self.is_running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
        print("🛑 Monitoraggio Fermato.")
        return True

    # Funzioni di supporto per pulizia e confronto titoli
    # La normalizzazione per confronto è più aggressiva, rimuove praticamente tutto tranne lettere e numeri, per massimizzare la stabilità del confronto
    def _normalize_text(self, text):
        if not text: return ""
        platform_patterns = r"(?i)\b(amazon\s+music|apple\s+music|spotify|deezer|youtube|vevo)\b.*"
        text = re.sub(platform_patterns, "", text)
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        clean = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live|mixed|spanish|italian)\b.*", "", clean)
        clean = unicodedata.normalize("NFD", clean).encode("ascii", "ignore").decode("utf-8")
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)
        return clean.strip().lower()

    # Versione più leggera, per confronto parziale
    def _normalize_for_match(self, text):
        if not text: return ""
        clean = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("utf-8")
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)
        return clean.strip().lower()

    # La pulizia per display rimuove le parole chiave di rumore più comuni e qualsiasi cosa tra parentesi che contiene parole chiave di rumore, ma cerca di mantenere il titolo il più leggibile possibile per l'utente
    def _clean_title_for_display(self, text):
        if not text: return ""
        junk_keywords = [
            "live", "remix", "edit", "club", "mix", "extended", "version", 
            "remaster", "re-master", "feat", "ft.", "karaoke", "instrumental", 
            "acoustic", "demo", "session", "registrazione", "mono", "stereo",
            "amazon music", "amazon original", "apple music", "spotify singles", 
            "spotify", "deezer", "youtube", "vevo", "presents", "exclusive"
        ]
        def clean_parens(match):
            content = match.group(1).lower()
            if any(k in content for k in junk_keywords): return "" 
            return match.group(0)

        text = re.sub(r"\s*[\(\[](.*?)[\)\]]", clean_parens, text)
        parts = text.split(" - ")
        if len(parts) > 1:
            last_part = parts[-1].lower()
            if any(k in last_part for k in junk_keywords):
                text = " - ".join(parts[:-1])
        return text.strip()

    # Rimozione brani non latin
    def _is_mostly_latin(self, text):
        if not text: return False
        try:
            ascii_count = len([c for c in text if ord(c) < 128])
            return (ascii_count / len(text)) > 0.5
        except: return True

    # Estrazione nome artista da dati ACRCloud (gestisce sia formato "artist" che "artists" con lista)
    def _get_artist_name(self, track_data):
        if "artist" in track_data: return track_data["artist"]
        if "artists" in track_data and track_data["artists"]: return track_data["artists"][0]["name"]
        return ""

    #Confronto tra due tracce per stabilità: confronto titolo con normalizzazione aggressiva, e confronto artista con normalizzazione più leggera e controllo di inclusione (per gestire casi di featuring o formati diversi)
    def _are_tracks_equivalent(self, t1, t2):
        tit1 = self._normalize_text(t1["title"])
        tit2 = self._normalize_text(t2["title"])
        similarity = SequenceMatcher(None, tit1, tit2).ratio()
        if similarity > 0.90: return True
        
        art1 = self._normalize_text(self._get_artist_name(t1))
        art2 = self._normalize_text(self._get_artist_name(t2))
        if similarity > 0.60:
            if art1 == art2 or art1 in art2 or art2 in art1: return True
        return False

    # Estrazione miglior cover disponibile: prima cerco su Spotify (se bot attivo), poi su ACRCloud (album), infine su eventuale campo "covers" generico
    def _extract_best_cover(self, track_data):
        try:
            if self.spotify_bot:
                title = track_data.get("title")
                artist = self._get_artist_name(track_data)
                hd_cover = self.spotify_bot.get_hd_cover(title, artist)
                if hd_cover: return hd_cover
        except: pass
        try:
            spotify = track_data.get("external_metadata", {}).get("spotify", {})
            if "album" in spotify and "images" in spotify["album"]:
                return spotify["album"]["images"][0].get("url")
            album = track_data.get("album", {})
            if "covers" in album and album["covers"]:
                return album["covers"][0].get("url")
        except: pass
        return None

    # Chiamata all'API ACRCloud con gestione dinamica della qualità in base alla latenza di rete, e logica di boost per bias artistico, scaletta e predizione
    def _call_acr_api(self, audio_buffer, bias_artist=None):
        THRESHOLD_MUSIC = 72
        THRESHOLD_HUMMING = 72

        http_method = "POST"
        http_uri = "/v1/identify"
        data_type = "audio"
        signature_version = "1"
        timestamp = str(int(time.time()))
        string_to_sign = http_method + "\n" + http_uri + "\n" + self.access_key + "\n" + data_type + "\n" + signature_version + "\n" + timestamp
        sign = base64.b64encode(hmac.new(self.access_secret.encode("ascii"), string_to_sign.encode("ascii"), digestmod=hashlib.sha1).digest()).decode("ascii")

        buffer_content = audio_buffer.getvalue()
        files = {"sample": ("temp.wav", buffer_content, "audio/wav")}
        data = {
            "access_key": self.access_key,
            "sample_bytes": len(buffer_content),
            "timestamp": timestamp,
            "signature": sign,
            "data_type": data_type,
            "signature_version": signature_version,
        }

        start_time = time.time()
        try:
            response = self.session.post(f"https://{self.host}/v1/identify", files=files, data=data, timeout=12)
            elapsed = time.time() - start_time

            # Adattamento dinamico alla qualità in base alla latenza di rete
            if elapsed > 4.5:
                if not self.low_quality_mode:
                    print(f"🐌 Rete lenta ({elapsed:.1f}s) -> Attivo LowQ e Rallento a 10s.")
                    self.low_quality_mode = True
                    self.overlap_interval = 10 
            elif elapsed < 2.0:
                if self.low_quality_mode:
                    print(f"🚀 Rete veloce ({elapsed:.1f}s) -> HighQ e Accelero a 6s.")
                    self.low_quality_mode = False
                    self.overlap_interval = 6

            result = response.json()
            status_code = result.get("status", {}).get("code")

            if status_code == 0:
                metadata = result.get("metadata", {})
                all_found = []

                def norm(sc): return int(float(sc) * 100) if float(sc) <= 1.0 else int(float(sc))
                
                # Logica di aggregazione: se più tracce sono molto simili tra loro (es. stesso titolo e artista con piccole variazioni), le considero la stessa traccia e prendo quella con il punteggio più alto, aggiungendo un piccolo boost per evitare di perdere risultati validi a causa di variazioni minori
                def aggregate_tracks(raw_list):
                    grouped = []
                    for t in raw_list:
                        merged = False
                        for g in grouped:
                            if self._are_tracks_equivalent(t, g):
                                existing_score = norm(g.get("score", 0))
                                new_score = norm(t.get("score", 0))
                                g["score"] = max(existing_score, new_score) + 5
                                merged = True; break
                        if not merged: grouped.append(t)
                    return grouped

                # Logica di processamento per sezione (musica e humming): applico aggregazione, normalizzazione punteggio, boost per bias artistico, scaletta e predizione, e filtro finale per soglia
                def process_section(track_list, threshold, type_label):
                    aggregated_list = aggregate_tracks(track_list)
                    for t in aggregated_list:
                        raw_score = norm(t.get("score", 0))
                        final_score = raw_score
                        title = t.get("title", "Sconosciuto")
                        
                        artist_names_found = set()
                        main_artist = self._get_artist_name(t)
                        if main_artist: artist_names_found.add(main_artist)
                        if "external_metadata" in t:
                             for provider in t["external_metadata"].values():
                                if isinstance(provider, dict):
                                    if "artists" in provider:
                                        for art in provider["artists"]:
                                            if "name" in art: artist_names_found.add(art["name"])
                                    if "channel_title" in provider: artist_names_found.add(provider["channel_title"])

                        display_artist = main_artist if main_artist else "Sconosciuto"
                        applied_boost_type = "None"
                        boost_amount = 0

                        # === 1. SUPER BOOST SCALETTA/WHITELIST ===
                        is_in_whitelist = self.setlist_bot.check_is_likely(title)
                        if is_in_whitelist:
                            boost_amount = 65 
                            final_score += boost_amount
                            applied_boost_type = "Whitelist/Setlist"
                        
                        # === 2. BOOST ARTISTA BIAS ===
                        elif bias_artist:
                            bias_norm = self._normalize_for_match(bias_artist)
                            is_artist_match = False
                            for found_art in artist_names_found:
                                art_norm = self._normalize_for_match(found_art)
                                if len(art_norm) < 2: continue
                                if (bias_norm in art_norm) or (art_norm in bias_norm):
                                    is_artist_match = True; break
                                bias_tokens = set(bias_norm.split())
                                target_tokens = set(art_norm.split())
                                if bias_tokens and target_tokens and bias_tokens.issubset(target_tokens):
                                    is_artist_match = True; break
                            
                            if is_artist_match:
                                boost_amount = 50 
                                final_score += boost_amount
                                applied_boost_type = "Artist Match"

                        # === 3. BOOST PREDIZIONE ===
                        if self.predicted_next_song:
                             if SequenceMatcher(None, title.lower(), self.predicted_next_song.lower()).ratio() > 0.85:
                                 boost_amount = 80 
                                 final_score += boost_amount
                                 applied_boost_type = f"PREDICTION ({self.predicted_next_song})"

                        # 4. Penalità ID o titoli generici (evitare falsi positivi)
                        clean_check = re.sub(r"[\(\[].*?[\)\]]", "", title)
                        clean_check = re.sub(r"(?i)\b(feat\.|ft\.|remix|edit|version|live|mixed|vip)\b.*", "", clean_check)
                        clean_check = re.sub(r"[^a-zA-Z0-9]", "", clean_check).lower().strip()
                        if re.match(r"^(id|track)\d*$", clean_check):
                            final_score -= (final_score * 0.30)

                        if boost_amount > 0:
                            print(f"🚀 [BOOST {applied_boost_type}] '{title}': {raw_score}% + {boost_amount}% = {final_score}%")

                        # Filtro finale per soglia
                        if final_score >= threshold:
                            cover_url = self._extract_best_cover(t)
                            all_found.append({
                                "status": "success", "type": type_label,
                                "title": title, "artist": display_artist,
                                "album": t.get("album", {}).get("name"),
                                "cover": cover_url, "score": final_score, 
                                "duration_ms": t.get("duration_ms"),
                                "external_metadata": t.get("external_metadata", {}),
                                "contributors": t.get("contributors", {}),
                            })

                if "music" in metadata: process_section(metadata["music"], THRESHOLD_MUSIC, "Original")
                if "humming" in metadata: process_section(metadata["humming"], THRESHOLD_HUMMING, "Cover/Humming")

                if all_found:
                    all_found.sort(key=lambda x: x["score"], reverse=True)
                    print(f"✅ TROVATO MIGLIORE: {all_found[0]['title']} ({all_found[0]['score']}%)")
                    return {"status": "multiple_results", "tracks": all_found}
                print("⚠️ Nessun risultato sopra soglia.")
                return {"status": "not_found"}

            elif status_code == 1001:
                return {"status": "not_found"}
            else:
                return {"status": "not_found"}
        except Exception as e:
            print(f"❌ Errore rete ACR: {e}")
            if not self.low_quality_mode:
                self.low_quality_mode = True
                self.overlap_interval = 10
            return {"status": "error"}

# TEST MANUALE
if __name__ == "__main__":
    print("🔧 Avvio test manuale AudioManager...")
    def dummy_callback(data, target_artist=None):
        print(f"📨 CALLBACK RICEVUTA: {data['title']} - {data['artist']} (Score: {data['score']})")

    bot = AudioManager(callback_function=dummy_callback)
    bot.start_continuous_recognition(dummy_callback, target_artist="Linkin Park")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        bot.stop_continuous_recognition()
        print("Test terminato.")