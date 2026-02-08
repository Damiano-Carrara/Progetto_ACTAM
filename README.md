# KYMA: Sistema di riconoscimento musicale e compilazione automatica di borderò
### Progetto di gruppo per il corso di Advanced Coding Tools and Methodologies, A.A. 2025/2026

**Componenti del gruppo:** Bo Lorenzo, Bocchi Arianna, Carrara Damiano, Guidi Alberto Javier

---

## 🎵 Descrizione del Progetto
**KYMA** è una web app completa volta a supportare compositori, artisti esecutori ed organizzatori di eventi musicali. 

Utilizzando un motore di riconoscimento ibrido (Audio + Testo), KYMA riconosce canzoni in tempo reale, arricchisce i metadati recuperando i compositori dei brani e genera automaticamente dei report in formato Excel e PDF, aiutando l'utente nella compilazione del borderò SIAE.

---

## 🚀 Funzionalità Principali

### 🧠 Motore di riconoscimento ibrido
* **Integrazione con ACRCloud:** utilizza il confronto di campioni audio per ottenere un riconoscimento musicale ad alta precisione.
* **ElevenLabs Scribe:** utilizza un modello di IA per trascrivere il testo delle canzoni in tempo reale, fornendo una validazione aggiuntiva che migliora la precisione del riconoscimento durante gli eventi dal vivo.
* **Decisione smart:** In base ai risultati ottenuti da ACRCloud e da Scribe, il software decide autonomamente di chi fidarsi per confermare i risultati, garantendo la massima precisione possibile.

### 🌍 Attenzione al contesto
* **Artist Bias:** inserendo il nome dell'artista che si sta esibendo (o delle relative tribute band) il software scarica il relativo repertorio (da Spotify e Setlist.fm), migliorando ulteriormente la precisione della rilevazione.
* **Aggregazione dei metadati:** Il software effettua una ricerca multi-piattaforma su **MusicBrainz**, **Spotify**, **iTunes**, **Deezer**, e **Genius** in modo da recuperare la lista corretta dei compositori per ciascun brano.

### ⏱️ Gestione della sessione
* **Aggiornamento in tempo reale:** L'interfaccia mostra in tempo reale le canzoni rilevate, con la relativa cover dell'album e i compositori trovati.
* **Recupero in caso di crash:** Lo stato di ciascuna sessione viene salvato su un database **Firestore**, permettendo a ciascun utente di recuperare l'ultima sessione in caso di crash o chiusure inaspettate.
* **Modifiche manuali:** durante la fase di revisione l'utente può modificare, aggiungere o rimuovere manualmente delle tracce per correggere eventuali errori.

### 📊 Download del report e statistiche
* **Generazione automatica dei report:** al termine di ciascuna sessione è possibile scaricare un documento simile al Borderò SIAE in formato Excel e PDF.
* **Dashboard Compositore:** Una pagina esclusiva per i compositori per tracciare i brani più ascoltati e ricevere una stima delle royalties.
* **Profilo utente:** statistiche personali su ascolti, artisti preferiti e brani frequenti.

---

## 🛠️ Info Tecniche

### Backend
* **Linguaggio:** Python 3.x
* **Framework:** Flask
* **Audio Processing:** numpy, scipy, sounddevice
* **Database:** Google Firebase Firestore
* **APIs:**
    * ACRCloud (Audio Fingerprinting) 
    * ElevenLabs (Lyrics/Speech-to-Text)
    * Spotify Web API (Metadata & Covers)
    * MusicBrainz (Dati compositori)
    * Genius (Lyrics)
    * iTunes & Deezer (Metadata di riserva)

### Frontend
* **Struttura:** HTML5, CSS3 (Variabili custom, animazioni keyframe)
* **Logica:** Vanilla JavaScript (ES6+)
* **Real-time:** Meccanismo di polling per aggiornare la playlist
* **Librerie:** Firebase SDK (Auth & Firestore), Chart.js (Analytics)

---

## ⚙️ Installazione

### Prerequisiti
* Python 3.8+
* Un progetto Firebase con Firestore configurato
* Chiavi API per i servizi elencati nella configurazione.

### Passaggi

**1. Clona la repository**
```bash
git clone https://github.com/Damiano-Carrara/Progetto_ACTAM.git kyma
cd kyma
```

**2. Installa le dipendenze**
```bash
pip install -r requirements.txt
```
*(Nota: Assicurati di avere PortAudio installato sul tuo sistema per permettere a sounddevice di funzionare correttamente).*

**3. Firebase Setup**
1.  Scarica la tua chiave privata **Firebase Admin SDK**.
2.  Rinominala in `firebase_credentials.json` e copiala nella cartella principale del progetto.
3.  Assicurati che le tue regole Firestore consentano lettura e scrittura per gli utenti autenticati.

**4. Configurazione dell'ambiente**
Crea un file `.env` nella cartella principale e aggiungi le tue chiavi API:

```env
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
```

**5. Avvio dell'applicazione**
Nel terminale attiva il virtual environment ed esegui:
```bash
python app.py
```
L'applicazione si avvierà sul server locale: `http://localhost:5000`.

---

## 📖 Guida all'utilizzo

1.  **Selezione ruolo:** Nella home page scegli il tuo ruolo (utente, organizzatore o compositore) e accedi/registrati.
2.  **Selezione modalità di rilevamento:**
    * **Live Band:** Ottimizzata per cover band generiche, con repertorio misto.
    * **Concerto:** Ottimizzata per concerti di grandi artisti o Tribute Band (richiede nome artista).
    * *(Solo compositori: Visualizza le statistiche e le stime delle royalties) .
3.  **Avvio e gestione della sessione:**
    * *(Solo organizzatori: inserisci l'incasso totale della serata per stimare le royalties).
    * Premi **Start** per avviare il monitoraggio. Il sistema mostrerà le canzoni riconosciute in tempo reale.
    * Usa **Pausa** per sospendere o annota modifiche da effettuare successivamente.
4.  **Revisione:**
    * Premi **Stop** per terminare e andare alla revisione.
    * Modifica o conferma i brani rilevati.
    * Clicca su **"Scarica i documenti"** per ottenere il borderò in PDF/Excel.
    * Clicca su **"Ripartizioni totali"** per vedere i compositori più frequenti.