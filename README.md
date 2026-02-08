# KYMA: Sistema di riconoscimento musicale e compilazione automatica di borderò
### Progetto di gruppo per il corso di Advanced Coding Tools and Methodologies, A.A. 2025/2026

**Componenti del gruppo:** Bo Lorenzo, Bocchi Arianna, Carrara Damiano, Guidi Alberto Javier

---

## 🎵 Descrizione del Progetto
[cite_start]**KYMA** è una web app completa volta a supportare compositori, artisti esecutori ed organizzatori di eventi musicali[cite: 2]. 

[cite_start]Utilizzando un motore di riconoscimento ibrido (Audio + Testo), KYMA riconosce canzoni in tempo reale, arricchisce i metadati recuperando i compositori dei brani e genera automaticamente dei report in formato Excel e PDF, aiutando l'utente nella compilazione del borderò SIAE[cite: 3].

---

## 🚀 Funzionalità Principali

### 🧠 Motore di riconoscimento ibrido
* [cite_start]**Integrazione con ACRCloud:** utilizza il confronto di campioni audio per ottenere un riconoscimento musicale ad alta precisione[cite: 6].
* [cite_start]**ElevenLabs Scribe:** utilizza un modello di IA per trascrivere il testo delle canzoni in tempo reale, fornendo una validazione aggiuntiva che migliora la precisione del riconoscimento durante gli eventi dal vivo[cite: 7].
* [cite_start]**Decisione smart:** In base ai risultati ottenuti da ACRCloud e da Scribe, il software decide autonomamente di chi fidarsi per confermare i risultati, garantendo la massima precisione possibile[cite: 8].

### 🌍 Attenzione al contesto
* [cite_start]**Artist Bias:** inserendo il nome dell'artista che si sta esibendo (o delle relative tribute band) il software scarica il relativo repertorio (da Spotify e Setlist.fm), migliorando ulteriormente la precisione della rilevazione[cite: 10].
* [cite_start]**Aggregazione dei metadati:** Il software effettua una ricerca multi-piattaforma su **MusicBrainz**, **Spotify**, **iTunes**, **Deezer**, e **Genius** in modo da recuperare la lista corretta dei compositori per ciascun brano[cite: 11].

### ⏱️ Gestione della sessione
* [cite_start]**Aggiornamento in tempo reale:** L'interfaccia mostra in tempo reale le canzoni rilevate, con la relativa cover dell'album e i compositori trovati[cite: 15].
* [cite_start]**Recupero in caso di crash:** Lo stato di ciascuna sessione viene salvato su un database **Firestore**, permettendo a ciascun utente di recuperare l'ultima sessione in caso di crash o chiusure inaspettate[cite: 16].
* [cite_start]**Modifiche manuali:** durante la fase di revisione l'utente può modificare, aggiungere o rimuovere manualmente delle tracce per correggere eventuali errori[cite: 17].

### 📊 Download del report e statistiche
* [cite_start]**Generazione automatica dei report:** al termine di ciascuna sessione è possibile scaricare un documento simile al Borderò SIAE in formato Excel e PDF[cite: 19].
* [cite_start]**Dashboard Compositore:** Una pagina esclusiva per i compositori per tracciare i brani più ascoltati e ricevere una stima delle royalties[cite: 20].
* [cite_start]**Profilo utente:** statistiche personali su ascolti, artisti preferiti e brani frequenti[cite: 21].

---

## 🛠️ Info Tecniche

### Backend
* [cite_start]**Linguaggio:** Python 3.x [cite: 24]
* [cite_start]**Framework:** Flask [cite: 25]
* [cite_start]**Audio Processing:** numpy, scipy, sounddevice [cite: 26]
* [cite_start]**Database:** Google Firebase Firestore [cite: 26]
* **APIs:**
    * [cite_start]ACRCloud (Audio Fingerprinting) [cite: 28]
    * [cite_start]ElevenLabs (Lyrics/Speech-to-Text) [cite: 30]
    * [cite_start]Spotify Web API (Metadata & Covers) [cite: 31]
    * [cite_start]MusicBrainz (Dati compositori) [cite: 32]
    * [cite_start]Genius (Lyrics) [cite: 33]
    * [cite_start]iTunes & Deezer (Metadata di riserva) [cite: 35]

### Frontend
* [cite_start]**Struttura:** HTML5, CSS3 (Variabili custom, animazioni keyframe) [cite: 37]
* [cite_start]**Logica:** Vanilla JavaScript (ES6+) [cite: 37]
* [cite_start]**Real-time:** Meccanismo di polling per aggiornare la playlist [cite: 38]
* [cite_start]**Librerie:** Firebase SDK (Auth & Firestore), Chart.js (Analytics) [cite: 39]

---

## ⚙️ Installazione

### Prerequisiti
* [cite_start]Python 3.8+ [cite: 42]
* [cite_start]Un progetto Firebase con Firestore configurato [cite: 43]
* [cite_start]Chiavi API per i servizi elencati nella configurazione[cite: 43].

### Passaggi

**1. Clona la repository**
```bash
git clone [https://github.com/your-username/kyma.git](https://github.com/your-username/kyma.git)
cd kyma
```

**2. Installa le dipendenze**
```bash
pip install -r requirements.txt
```
[cite_start]*(Nota: Assicurati di avere PortAudio installato sul tuo sistema per permettere a sounddevice di funzionare correttamente)[cite: 48].*

**3. Firebase Setup**
1.  [cite_start]Scarica la tua chiave privata **Firebase Admin SDK**[cite: 50].
2.  [cite_start]Rinominala in `firebase_credentials.json` e copiala nella cartella principale del progetto[cite: 51].
3.  [cite_start]Assicurati che le tue regole Firestore consentano lettura e scrittura per gli utenti autenticati[cite: 52].

**4. Configurazione dell'ambiente**
[cite_start]Crea un file `.env` nella cartella principale e aggiungi le tue chiavi API[cite: 54]:

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
[cite_start]Nel terminale attiva il virtual environment ed esegui[cite: 67]:
```bash
python app.py
```
[cite_start]L'applicazione si avvierà sul server locale: `http://localhost:5000`[cite: 68].

---

## 📖 Guida all'utilizzo

1.  [cite_start]**Selezione ruolo:** Nella home page scegli il tuo ruolo (utente, organizzatore o compositore) e accedi/registrati[cite: 70].
2.  **Selezione modalità di rilevamento:**
    * [cite_start]**Live Band:** Ottimizzata per cover band generiche, con repertorio misto[cite: 72].
    * [cite_start]**Concerto:** Ottimizzata per concerti di grandi artisti o Tribute Band (richiede nome artista)[cite: 73].
    * [cite_start]*(Solo compositori: Visualizza le statistiche e le stime delle royalties) [cite: 74]*.
3.  **Avvio e gestione della sessione:**
    * [cite_start]*(Solo organizzatori: inserisci l'incasso totale della serata per stimare le royalties) [cite: 76]*.
    * Premi **Start** per avviare il monitoraggio. [cite_start]Il sistema mostrerà le canzoni riconosciute in tempo reale[cite: 77, 78].
    * [cite_start]Usa **Pausa** per sospendere o annota modifiche da effettuare successivamente[cite: 79, 80].
4.  **Revisione:**
    * [cite_start]Premi **Stop** per terminare e andare alla revisione[cite: 83].
    * [cite_start]Modifica o conferma i brani rilevati[cite: 84].
    * [cite_start]Clicca su **"Scarica i documenti"** per ottenere il borderò in PDF/Excel[cite: 85].
    * [cite_start]Clicca su **"Ripartizioni totali"** per vedere i compositori più frequenti[cite: 86].