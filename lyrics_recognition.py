import whisper
import lyricsgenius
import re
import os
import unicodedata
from dotenv import load_dotenv

load_dotenv()

class LyricsRecognizer:
    def __init__(self):
        # Carica il modello Whisper (Tiny è veloce, Base è più preciso)
        print("🧠 [Lyrics] Caricamento modello Whisper...")
        self.model = whisper.load_model("tiny") 
        
        # Configura Genius per il fallback online
        token = os.getenv("GENIUS_ACCESS_TOKEN")
        self.genius = lyricsgenius.Genius(token)
        self.genius.verbose = False
        
        # Percorso della cache (deve coincidere con quello del Downloader)
        self.cache_path = "lyrics_cache"
        
        print("✅ [Lyrics] Modulo pronto (Cache + Online).")

    def identify(self, audio_array, sample_rate, target_artist=None):
        """
        Processo:
        1. Trascrizione Audio (Whisper)
        2. Controllo Cache Locale (Se abbiamo target_artist)
        3. Ricerca Online (Fallback)
        """
        try:
            # 1. TRASCRIZIONE
            result = self.model.transcribe(audio_array, fp16=False, language='it')
            text = result['text'].strip()

            if not text or len(text) < 15: # Ignora frasi troppo corte
                return None
            
            # Pulizia base della frase trascritta
            clean_text = self._clean_text_for_search(text)
            print(f"    🗣️ Whisper ha sentito: \"{text}\"")

            # 2. RICERCA IN CACHE LOCALE (Priorità Massima)
            if target_artist:
                cached_match = self._search_in_local_cache(clean_text, target_artist)
                if cached_match:
                    print(f"    ⚡ [CACHE HIT] Trovato nel file locale: {cached_match['title']}")
                    # Aggiungiamo lo snippet originale per il log
                    cached_match['metadata'] = {'snippet': text}
                    return cached_match

            # 3. RICERCA ONLINE (Fallback se la cache fallisce)
            print("    🌍 Cache miss. Cerco su Genius...")
            online_match = self._search_online(text, target_artist)
            if online_match:
                online_match['metadata'] = {'snippet': text}
                return online_match
                
        except Exception as e:
            print(f"❌ Errore Lyrics Recognition: {e}")
        
        return None

    def _search_in_local_cache(self, phrase, artist):
        """Cerca la frase trascritta dentro i file di testo scaricati"""
        
        # Costruisci il percorso cartella artista
        safe_artist = self._sanitize_filename(artist)
        artist_dir = os.path.join(self.cache_path, safe_artist)
        
        if not os.path.exists(artist_dir):
            return None

        # Ottimizzazione: la frase deve essere abbastanza lunga per evitare falsi positivi
        phrase_tokens = phrase.split()
        if len(phrase_tokens) < 3: 
            return None

        # Scansiona tutti i file .txt nella cartella
        best_match = None
        
        for filename in os.listdir(artist_dir):
            if not filename.endswith(".txt"): continue
            
            filepath = os.path.join(artist_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = self._clean_text_for_search(f.read())
                
                # CHECK 1: La frase esatta è nel testo?
                if phrase in content:
                    title = filename.replace(".txt", "")
                    return self._build_result(title, artist, 100, "Cache Match")
                
            except Exception:
                continue
                
        return None

    def _search_online(self, text, bias_artist=None):
        """Vecchia logica di ricerca su Genius"""
        try:
            # Se abbiamo un bias artist, lo aggiungiamo alla query per aiutare Genius
            query = f"{text} {bias_artist}" if bias_artist else text
            
            hits = self.genius.search_songs(query, per_page=1)
            if hits and 'hits' in hits and len(hits['hits']) > 0:
                best = hits['hits'][0]['result']
                
                # Controllo coerenza artista (se specificato)
                found_artist = best['primary_artist']['name']
                if bias_artist:
                    if not self._is_artist_match(bias_artist, found_artist):
                        return None
                
                return self._build_result(
                    best['title'], 
                    found_artist, 
                    90, # Score un po' più basso della cache perché è online
                    "Genius Match"
                )
        except:
            pass
        return None

    def _build_result(self, title, artist, score, type_lbl):
        return {
            "title": title,
            "artist": artist,
            "score": score,
            "type": type_lbl,
            "duration_ms": 0
        }

    def _clean_text_for_search(self, text):
        """Normalizza il testo per il confronto (rimuove accenti e punteggiatura)"""
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text) # Via punteggiatura
        text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
        return text

    def _sanitize_filename(self, name):
        """Deve essere identico a quello usato nel LyricsDownloader!"""
        return re.sub(r'[\\/*?:"<>|]', "", name).strip()

    def _is_artist_match(self, target, found):
        """Helper per verificare se l'artista corrisponde"""
        t = self._clean_text_for_search(target)
        f = self._clean_text_for_search(found)
        return t in f or f in t