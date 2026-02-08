KYMA: Sistema di riconoscimento musicale e compilazione automatica di borderò per eventi di musica dal vivo
Progetto di gruppo per il corso di Advanced Coding Tools and Methodologies, A.A. 2025/2026
Componenti del gruppo: Bocchi Arianna, Bo Lorenzo, Carrara Damiano, Guidi Alberto Javier

KYMA è una web app completa volta a supportare compositori, artisti esecutori ed organizzatori di eventi musicali. Utilizzando un motore di riconoscimento ibrido (Audio + Testo), KYMA riconosce canzoni in tempo reale, arricchisce i metadati recuperando i compositori dei brani e genera automaticamente dei report in formato Excel e PDF, aiutando l’utente nella compilazione del borderò SIAE.

 Funzionalità Principali
 Motore di riconoscimento ibrido
Integrazione con ACRCloud: utilizza il confronto di campioni audio per ottenere un riconoscimento musicale ad alta precisione.
ElevenLabs Scribe: utilizza un modello di IA per trascrivere il testo delle canzoni in tempo reale, fornendo una validazione aggiuntiva che migliora la precisione del riconoscimento durante gli eventi dal vivo.
Decisione smart: In base ai risultati ottenuti da ACRCloud e da Scribe, il software decide autonomamente di chi fidarsi per confermare i risultati, garantendo la massima precisione possibile.
 Attenzione al contesto
Artist Bias: inserendo il nome dell’artista che si sta esibendo (o delle relative tribute band) il software scarica il relativo repertorio (da Spotify e Setlist.fm), migliorando ulteriormente la precisione della rilevazione e fornendo un’esperienza utente ottimale.
Aggregazione dei metadati: Il software effettua una ricerca multi-piattaforma su MusicBrainz, Spotify, iTunes, Deezer, e Genius in modo da recuperare la lista corretta dei compositori per ciascun brano.
 Gestione della sessione
Aggiornamento in tempo reale: L’interfaccia mostra in tempo reale le canzoni rilevate, con la relativa cover dell’album e i compositori trovati.
Recupero in caso di crash: Lo stato di ciascuna sessione viene salvato su un database Firestore, permettendo a ciascun utente di recuperare l’ultima sessione in caso di crash o chiusure inaspettate.
Modifiche manuali: durante la fase di revisione, al termine del riconoscimento, l’utente può manualmente modificare, aggiungere o rimuovere delle tracce in modo da correggere eventuali errori del rilevamento automatico.
 Download del report e statistiche
Generazione automatica dei report: al termine di ciascuna sessione è possibile scaricare un documento simile al Borderò SIAE in formato Excel e PDF.
Dashboard Compositore: Una pagina esclusiva per i compositori in cui viene tenuta traccia dei propri brani più ascoltati e ricevere una stima delle royalties maturate grazie ad eventi dal vivo.
Profilo utente: ciascun utente può accedere alle proprie statistiche, visualizzando il numero di ascolti, i propri artisti preferiti e i brani ascoltati più spesso.

Info Tecniche
Backend
Linguaggio: Python 3.x
Framework: Flask
Audio Processing: numpy, scipy, sounddevice
Database: Google Firebase Firestore
APIs:
ACRCloud (Audio Fingerprinting)
ElevenLabs (Lyrics/Speech-to-Text)
Spotify Web API (Metadata & Covers)
MusicBrainz (Dati compositori)
Genius (Lyrics)
iTunes & Deezer (Metadata di riserva)
Frontend
Struttura: HTML5, CSS3 (Variabili custom, animazioni keyframe)
Logica: Vanilla JavaScript (ES6+)
Real-time: Meccanismo di polling per aggiornare la playlist
Librerie: Firebase SDK (Auth & Firestore), Chart.js (Analytics)

Installazione
Prerequisiti
Python 3.8+
Un progetto Firebase con Firestore configurato
Chiavi API per i servizi elencati nella configurazione.

1. Clona la repository
git clone https://github.com/your-username/kyma.git
cd kyma

2. Installa dipendenze
pip install -r requirements.txt

(Nota: Assicurati di avere PortAudio installato sul tuo sistema per permettere a sounddevice di funzionare correttamente).
3. Firebase Setup
Scarica la tua chiave privata Firebase Admin SDK.
Rinominala it firebase_credentials.json e copiala nella cartella principale del progetto.
Assicurati che le tue regole Firestore consentano lettura e scrittura per gli utenti autenticati.
4. Configurazione dell’ambiente
Crea un file .env nella cartella principale e aggiungi le tue chiavi API in questo modo:
# ACRCloud
ACR_HOST=Identify-EU-West-1.acrcloud.com
ACR_ACCESS_KEY=your_acr_key
ACR_ACCESS_SECRET=your_acr_secret

# Spotify
SPOTIFY_CLIENT_ID=your_spotify_id
SPOTIFY_CLIENT_SECRET=your_spotify_secret

# Genius (Lyrics & Composers)
GENIUS_ACCESS_TOKEN=your_genius_token

# ElevenLabs (Scribe/Lyrics Recognition)
ELEVENLABS_API_KEY=your_elevenlabs_key

5.Avvio dell’applicazione
Nel terminale attiva venv (.venv\Scripts\activate) ed esegui:
python app.py

L’applicazione si avvierà sul server locale: http://localhost:5000.

Guida all’utilizzo
Selezione ruolo: Nella home page scegli il tuo ruolo (utente, organizzatore o compositore) e accedi al tuo account (o registrati in caso di primo accesso).
Selezione modalità di rilevamento:
Live Band: Ottimizzata per cover band generiche, con repertorio misto.
Concerto: Ottimizzata per concerti di grandi artisti o esibizioni di Tribute Band (richiede di inserire il nome dell’artista per ottimizzare il funzionamento del software).
*Solo per compositori: Visualizza le statistiche e le stime delle royalties.
Avvio e gestione della sessione:
*Solo per organizzatori: inserisci l’incasso totale della serata, verrà utilizzato per stimare le royalties.
Premi start per avviare il monitoraggio audio.
Il sistema inizierà a mostrare man mano le canzoni riconosciute, ricercando i relativi compositori.
Usa il tasto pausa per sospendere temporaneamente il monitoraggio.
Se noti errori nel rilevamento, puoi annotare modifiche da effettuare successivamente, che ritroverai in fase di revisione.
Revisione:
Utilizza il tasto stop per interrompere il monitoraggio ed avviare la revisione.
In caso di errori, effettua le modifiche necessarie (puoi usare le note scritte in precedenza), oppure conferma i brani corretti.
Clicca su “Scarica i documenti” per effettuare il download del borderò in PDF e/o Excel.
Clicca su “Ripartizioni totali” per vedere quali sono i compositori più frequenti nella sessione corrente e, nel caso di un organizzatore, gestire i pagamenti delle relative royalties.
