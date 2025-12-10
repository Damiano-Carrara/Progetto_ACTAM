import time
from metadata_manager import MetadataManager

def test_single_case(bot, title, artist, source_expected, mock_raw_data=None):
    print(f"\n{'='*60}")
    print(f"🧪 TEST: {title} - {artist}")
    print(f"🎯 Obiettivo: Trovare compositore tramite {source_expected}")
    print(f"{'='*60}")
    
    start = time.time()
    # Passiamo il mock_raw_data alla funzione
    result = bot.find_composer(title, artist, raw_acr_meta=mock_raw_data)
    end = time.time()
    
    print(f"\n📝 Risultato: {result}")
    print(f"⏱️ Tempo: {end - start:.2f}s")
    
    if result != "Sconosciuto":
        print("✅ TEST SUPERATO")
    else:
        print("❌ TEST FALLITO (Nessun risultato)")

if __name__ == "__main__":
    # Inizializza il bot
    bot = MetadataManager()
    
    # 1. TEST MUSICBRAINZ 
    test_single_case(bot, "Bohemian Rhapsody", "Queen", "MusicBrainz")

    # 2. TEST ITUNES 
    test_single_case(bot, "Levitating", "Dua Lipa", "iTunes")

    # 3. TEST DEEZER -> SPOTIFY RAW FALLBACK
    # Simuliamo i dati che ACRCloud invierebbe per CENERE
    mock_spotify_data = {
        "spotify": {
            "artists": [
                {"name": "Lazza"},
                {"name": "Dardust"}, 
                {"name": "Davide Petrella"}
            ],
            "track": {"name": "CENERE"}
        }
    }
    
    test_single_case(bot, "CENERE", "Lazza", "Spotify Raw (Fallback)", mock_spotify_data)