import musicbrainzngs
import time # Importiamo il tempo
import re

class MetadataManager:
    def __init__(self):
        musicbrainzngs.set_useragent("SIAE_Project_Univ", "0.1", "tuamail@esempio.com")
        print("📚 Metadata Manager (MusicBrainz) Inizializzato")

    def find_composer(self, title, artist, isrc=None, upc=None):
        """
        Logica a cascata per trovare il compositore: ISRC > UPC > Titolo.
        Include lunghe pause di sicurezza (timeout) tra i tentativi.
        """
        composer = None

        # --- TENTATIVO 1: ISRC ---
        if isrc:
            print(f"🎯 [Meta] Provo ricerca ISRC: {isrc}")
            composer = self._search_by_isrc(isrc)
            if composer: return composer
            # Pausa lunga prima di passare al fallback
            time.sleep(2.0) 

        # --- TENTATIVO 2: UPC (Barcode) ---
        if upc:
            print(f"📦 [Meta] Provo ricerca UPC: {upc}")
            composer = self._search_by_upc(upc, title)
            if composer: return composer
            # Pausa lunga prima di passare al fallback
            time.sleep(2.0)

        # --- TENTATIVO 3: CLASSICO (Titolo + Artista) ---
        print(f"🔎 [Meta] Fallback su ricerca testuale: {title} - {artist}")
        return self._search_by_text(title, artist)

    # ---------------------------------------------------------
    # METODI HELPER SPECIFICI
    # ---------------------------------------------------------

    def _search_by_isrc(self, isrc):
        try:
            # PASSAGGIO 1: Otteniamo l'ID della registrazione
            res = musicbrainzngs.get_recordings_by_isrc(isrc, includes=[])
            
            if 'isrc' in res and res['isrc']['recording-list']:
                rec_stub = res['isrc']['recording-list'][0]
                rec_id = rec_stub['id']
                
                time.sleep(0.5) # Pausa di sicurezza interna
                
                # PASSAGGIO 2: Chiediamo i dettagli completi Work-Relations
                rec_details = musicbrainzngs.get_recording_by_id(rec_id, includes=['work-rels'])
                
                return self._extract_composer_from_recording(rec_details['recording'])
                
        except Exception as e:
            print(f"⚠️ Errore ISRC: {e}")
        return None

    def _search_by_upc(self, upc, target_title):
        try:
            # Cerca la "Release" (Album) tramite Barcode
            res = musicbrainzngs.search_releases(query=f'barcode:{upc}', limit=1)
            
            if not res['release-list']:
                return None
                
            release = res['release-list'][0]
            release_id = release['id']
            
            time.sleep(0.5) # Pausa di sicurezza interna
            
            # Scarica le tracce di questa release
            rel_details = musicbrainzngs.get_release_by_id(release_id, includes=['recordings'])
            
            found_recording_id = None
            for medium in rel_details['release']['medium-list']:
                for track in medium['track-list']:
                    track_title = track['recording']['title']
                    if target_title.lower() in track_title.lower() or track_title.lower() in target_title.lower():
                        found_recording_id = track['recording']['id']
                        break
                if found_recording_id: break
            
            if found_recording_id:
                time.sleep(0.5) # Pausa di sicurezza interna
                rec_details = musicbrainzngs.get_recording_by_id(found_recording_id, includes=['work-rels'])
                return self._extract_composer_from_recording(rec_details['recording'])

        except Exception as e:
            print(f"⚠️ Errore UPC: {e}")
        return None

        
    def _clean_title(self, title):
        """
        Rimuove il testo tra parentesi e parole comuni dei remix
        Es: "Reload (RAWA & Voltech Remix)" -> "Reload"
        """
        # Rimuove tutto ciò che è tra parentesi tonde o quadre
        clean = re.sub(r"[\(\[].*?[\)\]]", "", title)
        # Rimuove spazi extra
        return clean.strip()

    def _search_by_text(self, title, artist):
        """
        Prova la ricerca esatta. Se fallisce, pulisce il titolo e riprova.
        """
        # 1. Primo tentativo: Titolo esatto
        composer = self._perform_text_query(title, artist)
        if composer != "Sconosciuto":
            return composer

        # 2. Secondo tentativo: Titolo "pulito" (senza Remix/Feat)
        cleaned_title = self._clean_title(title)
        
        # Se il titolo pulito è diverso dall'originale (es. avevamo parentesi)
        if cleaned_title != title and len(cleaned_title) > 0:
            print(f"🧹 [Meta] Nessun risultato. Riprovo con titolo pulito: '{cleaned_title}'")
            time.sleep(1.0) # Pausa gentilezza
            composer = self._perform_text_query(cleaned_title, artist)
            if composer != "Sconosciuto":
                return composer

        return "Sconosciuto"

    def _perform_text_query(self, title, artist):
        """
        Esegue la chiamata effettiva a MusicBrainz per testo
        """
        try:
            # Cerca Recordings
            # Usa 'strict=False' implicito o rimuovi AND per essere più lasco se serve
            query = f'recording:"{title}" AND artist:"{artist}"'
            res = musicbrainzngs.search_recordings(query=query, limit=3)
            
            if not res['recording-list']:
                # Fallback immediato sull'opera (Work) se non trova la registrazione
                return self._fallback_search_work(title)
            
            rec = res['recording-list'][0]
            time.sleep(0.5)
            
            # Dettagli recording + work-rels
            rec_details = musicbrainzngs.get_recording_by_id(rec['id'], includes=['work-rels'])
            val = self._extract_composer_from_recording(rec_details['recording'])
            
            if val == "Sconosciuto":
                return self._fallback_search_work(title)
            
            return val

        except Exception as e:
            print(f"⚠️ Errore ricerca testo: {e}")
            return "Sconosciuto"

    def _extract_composer_from_recording(self, recording_data):
        """Estrae i compositori dati i dettagli di una registrazione"""
        try:
            if 'work-relation-list' not in recording_data:
                return "Sconosciuto"
            
            work_id = recording_data['work-relation-list'][0]['work']['id']
            
            # ⭐ PAUSA CRITICA: Prima dell'ultima e più complessa chiamata
            time.sleep(0.5) 
            
            work_details = musicbrainzngs.get_work_by_id(work_id, includes=['artist-rels'])
            
            composers = []
            if 'artist-relation-list' in work_details['work']:
                for relation in work_details['work']['artist-relation-list']:
                    if relation['type'] in ['composer', 'writer']:
                        composers.append(relation['artist']['name'])
            
            return ", ".join(composers) if composers else "Sconosciuto"
        except Exception:
            return "Sconosciuto"

    def _fallback_search_work(self, title):
        try:
            res = musicbrainzngs.search_works(query=f'work:"{title}"', limit=1)
            if res['work-list']:
                work_id = res['work-list'][0]['id']
                time.sleep(0.5) 
                work_details = musicbrainzngs.get_work_by_id(work_id, includes=['artist-rels'])
                composers = []
                if 'artist-relation-list' in work_details['work']:
                    for relation in work_details['work']['artist-relation-list']:
                        if relation['type'] in ['composer', 'writer']:
                            composers.append(relation['artist']['name'])
                return ", ".join(composers) if composers else "Sconosciuto"
        except:
            pass
        return "Sconosciuto"