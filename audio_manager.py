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
from collections import deque, Counter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from difflib import SequenceMatcher

load_dotenv()


class AudioManager:
    def __init__(self):
        self.host = os.getenv("ACR_HOST")
        self.access_key = os.getenv("ACR_ACCESS_KEY")
        self.access_secret = os.getenv("ACR_ACCESS_SECRET")

        # --- CONFIGURAZIONE SESSIONE HTTP ---
        self.session = requests.Session()
        retry_strategy = Retry(
            total=0,
            backoff_factor=0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # --- CONFIGURAZIONE STREAMING ---
        self.sample_rate = 44100
        self.window_duration = 12
        self.overlap_interval = 6
        self.block_size = 4096
        self.audio_buffer = deque(
            maxlen=int((self.sample_rate * self.window_duration) / self.block_size) + 5
        )
        self.history_buffer = deque(maxlen=10)

        self.is_running = False
        self.stream = None
        self.monitor_thread = None
        self.result_callback = None
        self.target_artist_bias = None

        # --- GESTIONE QUALITÀ DINAMICA ---
        self.low_quality_mode = False
        self.upload_lock = threading.Lock()

        print("🎤 Audio Manager Pronto. Timeout: 10s | Super-Bias: ATTIVO (+40/50pt)")

    def _audio_callback(self, indata, frames, time, status):
        if status:
            print(f"⚠️ Audio Status: {status}")
        self.audio_buffer.append(indata.copy())

    def _preprocess_audio_chunk(self, full_audio_data):
        if full_audio_data.dtype != np.float32:
            data = full_audio_data.astype(np.float32)
        else:
            data = full_audio_data

        sos = signal.butter(10, 80, "hp", fs=self.sample_rate, output="sos")
        filtered = signal.sosfilt(sos, data, axis=0)

        max_val = np.max(np.abs(filtered))
        if max_val > 0:
            normalized = filtered / max_val * 0.95
        else:
            normalized = filtered

        return (normalized * 32767).astype(np.int16)

    def _normalize_text(self, text):
        """Pulisce e rimuove accenti (AGGRESSIVO - Per Deduplica)"""
        if not text:
            return ""

        # Rimuove parentesi e featuring per normalizzare il titolo base
        clean = re.sub(r"[\(\[].*?[\)\]]", "", text)
        clean = re.sub(
            r"(?i)\b(feat\.|ft\.|remix|edit|version|karaoke|live|mixed|spanish|italian)\b.*",
            "",
            clean,
        )

        clean = (
            unicodedata.normalize("NFD", clean).encode("ascii", "ignore").decode("utf-8")
        )
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)
        return clean.strip().lower()

    def _normalize_for_match(self, text):
        """Pulisce accenti ma MANTIENE i featuring (GENTILE - Per Bias Matching)"""
        if not text:
            return ""

        # Qui NON rimuoviamo "feat.", "live", ecc. perché contengono l'artista che cerchiamo!
        clean = (
            unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("utf-8")
        )
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)  # Rimuove solo simboli strani (!, ?, -)
        return clean.strip().lower()

    def _clean_title_for_display(self, text):
        if not text:
            return ""

        while True:
            cleaned = re.sub(r"\s*[\(\[].*?[\)\]]", "", text)
            if cleaned == text:
                break
            text = cleaned

        text = text.strip("()[] ")
        return text.strip()

    def _is_mostly_latin(self, text):
        if not text:
            return False
        try:
            ascii_count = len([c for c in text if ord(c) < 128])
            return (ascii_count / len(text)) > 0.5
        except:
            return True

    def _get_artist_name(self, track_data):
        if "artist" in track_data:
            return track_data["artist"]
        if "artists" in track_data and track_data["artists"]:
            return track_data["artists"][0]["name"]
        return ""

    def _are_tracks_equivalent(self, t1, t2):
        # Usa la normalizzazione AGGRESSIVA (ignora i feat per capire se è lo stesso brano)
        art1 = self._normalize_text(self._get_artist_name(t1))
        art2 = self._normalize_text(self._get_artist_name(t2))

        if art1 != art2 and art1 not in art2 and art2 not in art1:
            return False

        tit1 = self._normalize_text(t1["title"])
        tit2 = self._normalize_text(t2["title"])

        similarity = SequenceMatcher(None, tit1, tit2).ratio()

        if similarity < 0.40:
            return False

        if similarity > 0.60:
            return True

        try:
            dur1 = int(t1.get("duration_ms", 0) or 0)
            dur2 = int(t2.get("duration_ms", 0) or 0)
        except (ValueError, TypeError):
            dur1, dur2 = 0, 0

        if dur1 > 30000 and dur2 > 30000:
            diff = abs(dur1 - dur2)
            if diff < 1200:
                return True

        return False

    def _extract_best_cover(self, track_data):
        """Estrae la migliore copertina disponibile (Spotify > Deezer > Generic)"""
        try:
            # 1. Prova Spotify (spesso HD)
            spotify = track_data.get("external_metadata", {}).get("spotify", {})
            if "album" in spotify and "images" in spotify["album"]:
                images = spotify["album"]["images"]
                if images:
                    return images[0].get("url") # Solitamente la prima è la più grande

            # 2. Prova Generic ACRCloud Cover
            album = track_data.get("album", {})
            if "covers" in album and album["covers"]:
                return album["covers"][0].get("url")
                
        except Exception as e:
            print(f"⚠️ Errore estrazione cover: {e}")
        
        return None

    def _process_window(self):
        if not self.upload_lock.acquire(blocking=False):
            print("⏳ Rete lenta: Salto finestra.")
            return

        try:
            if not self.audio_buffer:
                return

            try:
                full_recording = np.concatenate(list(self.audio_buffer))
            except ValueError:
                return

            if len(full_recording) < self.sample_rate * (self.window_duration - 1):
                return

            processed_audio = self._preprocess_audio_chunk(full_recording)

            if self.low_quality_mode:
                TARGET_RATE = 8000
                num_samples = int(len(processed_audio) * TARGET_RATE / self.sample_rate)
                final_audio = signal.resample(processed_audio, num_samples).astype(np.int16)
                write_rate = TARGET_RATE
                status_msg = "📡 Analisi [LowQ - 8kHz]..."
            else:
                final_audio = processed_audio
                write_rate = self.sample_rate
                status_msg = "📡 Analisi [HighQ - 44kHz]..."

            wav_buffer = io.BytesIO()
            wav.write(wav_buffer, write_rate, final_audio)
            wav_buffer.seek(0)

            print(status_msg)

            api_result = self._call_acr_api(wav_buffer, bias_artist=self.target_artist_bias)

            best_track_data = None
            current_obj = None

            if api_result.get("status") == "multiple_results":
                tracks = api_result["tracks"]

                bias_winner = None
                if self.target_artist_bias:
                    for t in tracks:
                        # Usa normalizzazione GENTILE per trovare il bias (mantiene i feat)
                        artist_clean = self._normalize_for_match(self._get_artist_name(t))
                        title_clean = self._normalize_for_match(t.get("title"))
                        bias_clean = self._normalize_for_match(self.target_artist_bias)

                        try:
                            score_val = float(t.get("score", 0))
                        except:
                            score_val = 0

                        # Cerca il bias sia nell'artista che nel titolo
                        is_bias_present = (bias_clean in artist_clean) or (bias_clean in title_clean)

                        if is_bias_present and score_val >= 70:
                            bias_winner = t
                            print(f"🏆 Bias Winner Scelto: {t['title']} ({score_val}%)")
                            break

                best_track = bias_winner if bias_winner else tracks[0]

                if not self._is_mostly_latin(best_track["title"]):
                    print(f"🐉 Scartato brano non-Latin (Falso Positivo): {best_track['title']}")
                    current_obj = None
                else:
                    best_track_data = best_track
                    best_track_data["display_title"] = self._clean_title_for_display(best_track_data["title"])

                    current_obj = {
                        "title": best_track_data["title"],
                        "artist": self._get_artist_name(best_track_data),
                        "duration_ms": best_track_data.get("duration_ms", 0),
                    }
            else:
                current_obj = None

            if current_obj:
                self.history_buffer.append(current_obj)

                stability_count = 0
                for historical_item in self.history_buffer:
                    if self._are_tracks_equivalent(current_obj, historical_item):
                        stability_count += 1

                if stability_count >= 2:
                    print(
                        f"🛡️ Conferma stabilità ({stability_count}/10 validi): "
                        f"{best_track_data['display_title']} (Artist: {self._get_artist_name(best_track_data)})"
                    )

                    if self.result_callback:
                        final_data = best_track_data.copy()
                        final_data["title"] = best_track_data["display_title"]
                        final_data["artist"] = self._get_artist_name(best_track_data)
                        self.result_callback(final_data, target_artist=self.target_artist_bias)
            else:
                pass
        finally:
            self.upload_lock.release()

    def _loop_logic(self):
        print("⏱️ Avvio ciclo di monitoraggio...")
        time.sleep(self.window_duration)
        while self.is_running:
            threading.Thread(target=self._process_window).start()
            time.sleep(self.overlap_interval)

    def start_continuous_recognition(self, callback_function, target_artist=None):
        if self.is_running:
            return False

        self.is_running = True
        self.result_callback = callback_function
        self.target_artist_bias = target_artist
        self.audio_buffer.clear()
        self.history_buffer.clear()
        self.low_quality_mode = False

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            blocksize=self.block_size,
            callback=self._audio_callback,
        )
        self.stream.start()

        self.monitor_thread = threading.Thread(target=self._loop_logic)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

        return True

    def stop_continuous_recognition(self):
        self.is_running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
        print("🛑 Monitoraggio Fermato.")
        return True

    def _call_acr_api(self, audio_buffer, bias_artist=None):
        THRESHOLD_MUSIC = 72
        THRESHOLD_HUMMING = 72

        http_method = "POST"
        http_uri = "/v1/identify"
        data_type = "audio"
        signature_version = "1"
        timestamp = str(int(time.time()))

        string_to_sign = (
            http_method
            + "\n"
            + http_uri
            + "\n"
            + self.access_key
            + "\n"
            + data_type
            + "\n"
            + signature_version
            + "\n"
            + timestamp
        )

        sign = base64.b64encode(
            hmac.new(
                self.access_secret.encode("ascii"),
                string_to_sign.encode("ascii"),
                digestmod=hashlib.sha1,
            ).digest()
        ).decode("ascii")

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
            response = self.session.post(
                f"https://{self.host}/v1/identify", files=files, data=data, timeout=10
            )
            elapsed = time.time() - start_time

            if elapsed > 4.0:
                if not self.low_quality_mode:
                    print(f"⚠️ Upload lento ({elapsed:.1f}s) -> Attivo LowQ.")
                    self.low_quality_mode = True
            elif elapsed < 1.5:
                if self.low_quality_mode:
                    print(f"🚀 Upload veloce ({elapsed:.1f}s) -> Torno a HighQ.")
                    self.low_quality_mode = False

            result = response.json()
            status_code = result.get("status", {}).get("code")

            if status_code == 0:
                metadata = result.get("metadata", {})
                all_found = []

                def norm(sc):
                    return int(float(sc) * 100) if float(sc) <= 1.0 else int(float(sc))

                def aggregate_tracks(raw_list):
                    grouped = []

                    for t in raw_list:
                        # Deduplica: usa normalizzazione AGGRESSIVA
                        t["artist_norm"] = self._normalize_text(self._get_artist_name(t))
                        t["title_norm"] = self._normalize_text(t.get("title"))

                        merged = False
                        for g in grouped:
                            if self._are_tracks_equivalent(t, g):
                                existing_score = norm(g.get("score", 0))
                                new_score = norm(t.get("score", 0))
                                g["score"] = max(existing_score, new_score) + 5
                                print(f"🔗 AGGREGAZIONE: '{t.get('title')}' -> '{g.get('title')}'")
                                merged = True
                                break

                        if not merged:
                            grouped.append(t)

                    return grouped

                def process_section(track_list, threshold, type_label):
                    aggregated_list = aggregate_tracks(track_list)
                    results_count = len(aggregated_list)
                    current_bonus_val = 50 if results_count == 1 else 40

                    for t in aggregated_list:
                        raw_score = norm(t.get("score", 0))
                        final_score = raw_score
                        title = t.get("title", "Sconosciuto")
                        artist_name = self._get_artist_name(t)
                        applied_bonus = 0

                        # --- LOGICA BIAS ESISTENTE ---
                        if bias_artist:
                            bias_norm_str = self._normalize_for_match(bias_artist)
                            bias_tokens = set(bias_norm_str.split())

                            def check_match_smart(text_to_check):
                                if not text_to_check:
                                    return False
                                text_norm = self._normalize_for_match(text_to_check)
                                if bias_norm_str in text_norm:
                                    return True
                                target_tokens = set(text_norm.split())
                                if bias_tokens.issubset(target_tokens):
                                    return True
                                return False

                            is_match = False
                            if check_match_smart(artist_name):
                                is_match = True
                            if not is_match and check_match_smart(title):
                                is_match = True

                            if not is_match and "artists" in t:
                                for art in t["artists"]:
                                    if check_match_smart(art["name"]):
                                        is_match = True
                                        break

                            if not is_match and "external_metadata" in t:
                                ext_meta_dump = json.dumps(t["external_metadata"])
                                if self._normalize_for_match(bias_artist) in self._normalize_for_match(ext_meta_dump):
                                    is_match = True

                            if is_match:
                                applied_bonus = current_bonus_val
                                final_score += applied_bonus

                        # ============================================================
                        # [NUOVO] FILTRO ANTI "ID" / TITOLI GENERICI
                        # ============================================================
                        clean_check = re.sub(r"[\(\[].*?[\)\]]", "", title)
                        clean_check = re.sub(
                            r"(?i)\b(feat\.|ft\.|remix|edit|version|live|mixed|vip)\b.*",
                            "",
                            clean_check,
                        )
                        clean_check = re.sub(r"[^a-zA-Z0-9]", "", clean_check).lower().strip()

                        # Regex: Cattura "id", "id1", "id23", "track1", "track05"
                        if re.match(r"^(id|track)\d*$", clean_check):
                            penalty = final_score * 0.30  # Calcolo il 30%
                            final_score -= penalty  # Sottraggo
                            print(
                                f"📉 PENALITÀ GENERIC ID: '{title}' -> "
                                f"Score abbattuto del 30% ({int(final_score + penalty)}% -> {int(final_score)}%)"
                            )
                        # ============================================================

                        if final_score >= threshold:
                            if raw_score < threshold:
                                print(f"🚀 BOOST DECISIVO (+{applied_bonus}): '{title}' ({raw_score}% -> {final_score}%)")
                            elif applied_bonus > 0:
                                print(f"✨ Boost applicato (+{applied_bonus}): '{title}'")

                            cover_url = self._extract_best_cover(t)
                            all_found.append({
                                "status": "success",
                                "type": type_label,
                                "title": title,
                                "artist": artist_name,
                                "album": t.get("album", {}).get("name"),
                                "cover": cover_url,
                                "score": final_score,
                                "duration_ms": t.get("duration_ms"),
                                "isrc": t.get("external_ids", {}).get("isrc"),
                                "upc": t.get("external_metadata", {}).get("upc"),
                                "external_metadata": t.get("external_metadata", {}),
                                "contributors": t.get("contributors", {}),
                            })
                        else:
                            bias_msg = " (Bias fallito)" if bias_artist and applied_bonus == 0 else ""
                            reason = " (ID Penalty)" if re.match(r"^(id|track)\d*$", clean_check) else ""
                            print(f"📉 SCARTATO: '{title}' - Score: {final_score}%{bias_msg}{reason}")

                if "music" in metadata:
                    process_section(metadata["music"], THRESHOLD_MUSIC, "Original")
                if "humming" in metadata:
                    process_section(metadata["humming"], THRESHOLD_HUMMING, "Cover/Humming")

                if all_found:
                    all_found.sort(key=lambda x: x["score"], reverse=True)
                    print(f"✅ TROVATO MIGLIORE: {all_found[0]['title']} ({all_found[0]['score']}%)")
                    return {"status": "multiple_results", "tracks": all_found}

                print("⚠️ Nessun risultato sopra soglia.")
                return {"status": "not_found"}

            elif status_code == 1001:
                print("🚫 API: Nessuna corrispondenza (Code 1001)")
                return {"status": "not_found"}

            else:
                print(f"❌ API Error Code: {status_code}: {result.get('status', {}).get('msg')}")
                return {"status": "not_found"}

        except Exception as e:
            print(f"❌ Errore rete: {e}")
            if not self.low_quality_mode:
                self.low_quality_mode = True
            return {"status": "error"}