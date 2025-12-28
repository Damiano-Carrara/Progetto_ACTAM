import threading
import time
import os
import shutil
import re
import lyricsgenius
from dotenv import load_dotenv

load_dotenv()

class LyricsDownloader:
    def __init__(self):
        self.genius_token = os.getenv("GENIUS_ACCESS_TOKEN")
        self.base_path = "lyrics_cache"
        self.is_downloading = False
        
        # Crea la cartella se non esiste
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

    def start_background_download(self, artist_name, song_list):
        """Avvia il download in un thread separato"""
        if not song_list:
            print("⚠️ [LyricsDownloader] Lista brani vuota, nulla da scaricare.")
            return

        if self.is_downloading:
            return

        thread = threading.Thread(
            target=self._download_loop,
            args=(artist_name, song_list),
            daemon=True
        )
        thread.start()

    def _download_loop(self, artist_name, song_list):
        self.is_downloading = True
        print(f"📥 [LyricsDownloader] Avvio download background per {len(song_list)} brani...")
        
        try:
            genius = lyricsgenius.Genius(self.genius_token)
            genius.verbose = False
        except:
            print("❌ [LyricsDownloader] Errore Token Genius")
            self.is_downloading = False
            return

        # Cartella specifica per l'artista
        artist_folder = os.path.join(self.base_path, self._sanitize(artist_name))
        if not os.path.exists(artist_folder):
            os.makedirs(artist_folder)

        count = 0
        for title in song_list:
            safe_title = self._sanitize(title)
            file_path = os.path.join(artist_folder, f"{safe_title}.txt")
            
            # Se esiste già, saltiamo
            if os.path.exists(file_path):
                continue

            try:
                # Cerca e scarica
                song = genius.search_song(title, artist_name)
                if song:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(song.lyrics)
                    count += 1
                    # print(f"   📄 Testo scaricato: {title}") # Decommenta se vuoi vedere i log
                
                # Pausa Anti-Ban (Fondamentale)
                time.sleep(1.5) 

            except Exception as e:
                # print(f"   ⚠️ Errore download '{title}': {e}")
                time.sleep(2)

        print(f"🏁 [LyricsDownloader] Finito! Scaricati {count} testi in cache.")
        self.is_downloading = False

    def clear_cache(self):
        """Cancella l'intera cartella della cache"""
        if os.path.exists(self.base_path):
            try:
                shutil.rmtree(self.base_path)
                print("🧹 [LyricsDownloader] Cache svuotata e rimossa.")
            except Exception as e:
                print(f"❌ Errore pulizia cache: {e}")

    def _sanitize(self, name):
        return re.sub(r'[\\/*?:"<>|]', "", name).strip()