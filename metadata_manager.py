import musicbrainzngs

class MetadataManager:
    def __init__(self):
        # Configurazione obbligatoria per MusicBrainz (identifica la tua app)
        # Sostituisci con la tua email reale o finta, serve per cortesia verso il server
        musicbrainzngs.set_useragent("SIAE_Project_Univ", "0.1", "tua_email@esempio.com")
        print("📚 Metadata Manager (MusicBrainz) Inizializzato")

    def find_composer(self, title, artist):
        """
        Cerca il compositore su MusicBrainz dato Titolo e Artista (Performer).
        Restituisce una stringa con i cognomi o 'Sconosciuto'.
        """
        print(f"🔎 Cerco compositore per: {title} - {artist}")
        
        try:
            # 1. Cerca la REGISTRAZIONE (Recording)
            # Usiamo una ricerca flessibile (senza match esatto per gestire typos)
            search_results = musicbrainzngs.search_recordings(query=f'recording:"{title}" AND artist:"{artist}"', limit=3)
            
            if not search_results['recording-list']:
                print("⚠️ Nessuna registrazione trovata su MusicBrainz.")
                return "Sconosciuto"

            # Prendiamo il primo risultato (il più probabile)
            recording = search_results['recording-list'][0]
            recording_id = recording['id']

            # 2. Cerca le RELAZIONI (Work) legate a questa registrazione
            # Un brano registrato è collegato a un'Opera (Work) che ha i compositori
            try:
                # Ottiene i dettagli della registrazione incluse le relazioni con le 'works'
                rec_details = musicbrainzngs.get_recording_by_id(recording_id, includes=['work-rels'])
            except Exception:
                return "Sconosciuto"

            if 'work-relation-list' not in rec_details['recording']:
                # A volte il link diretto manca. Proviamo a cercare l'opera per titolo
                return self._fallback_search_work(title)

            # 3. Estrai i COMPOSITORI dall'Opera
            # Di solito c'è una sola opera collegata, ma controlliamo
            work_id = rec_details['recording']['work-relation-list'][0]['work']['id']
            
            # Ora scarichiamo i dettagli dell'Opera (Work) per vedere gli autori
            work_details = musicbrainzngs.get_work_by_id(work_id, includes=['artist-rels'])
            
            composers = []
            if 'artist-relation-list' in work_details['work']:
                for relation in work_details['work']['artist-relation-list']:
                    # Cerchiamo relazioni di tipo 'composer' o 'writer'
                    if relation['type'] in ['composer', 'writer']:
                        full_name = relation['artist']['name']
                        # Estrai solo il cognome (euristica semplice: ultima parola)
                        # Per la SIAE spesso basta il cognome, ma salviamo tutto per sicurezza
                        composers.append(full_name)

            if composers:
                return ", ".join(composers) # Restituisce es: "Mercury, May"
            else:
                return "Sconosciuto"

        except Exception as e:
            print(f"❌ Errore MusicBrainz: {e}")
            return "Sconosciuto"

    def _fallback_search_work(self, title):
        """Tentativo disperato: cerca direttamente l'Opera per titolo"""
        try:
            res = musicbrainzngs.search_works(query=f'work:"{title}"', limit=1)
            if res['work-list']:
                work_id = res['work-list'][0]['id']
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