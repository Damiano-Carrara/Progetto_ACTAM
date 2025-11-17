// app.js

let isRecording = false;
let currentPlaylist = [];

// ---- GESTIONE VISTE -------------------------------------------------

function showView(id) {
  const views = document.querySelectorAll('.view');
  views.forEach(v => {
    if (v.id === id) {
      v.hidden = false;
      v.classList.add('view--active');
    } else {
      v.hidden = true;
      v.classList.remove('view--active');
    }
  });
}

// ---- STATO / INDICATORE ---------------------------------------------

function updateStatus(text, stateClass) {
  const indicator = document.getElementById('status-indicator');
  const label = document.getElementById('status-text');
  if (!indicator || !label) return;
  label.innerText = text;
  indicator.className = 'status-box ' + (stateClass || 'idle');
}

function highlightRow(id) {
  const row = document.getElementById(`row-${id}`);
  if (row) {
    const originalBg = row.style.backgroundColor;
    row.style.backgroundColor = '#2e7d32';
    setTimeout(() => {
      row.style.backgroundColor = originalBg || '';
    }, 2000);
  }
}

// ---- SESSIONE: START / STOP / LOOP ----------------------------------

async function startSession() {
  if (isRecording) return;
  isRecording = true;

  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnReview = document.getElementById('btn-go-review');

  if (btnStart) btnStart.disabled = true;
  if (btnStop) btnStop.disabled = false;
  if (btnReview) btnReview.disabled = true;

  updateStatus('🔴 In ascolto...', 'recording');

  // Avvio loop di riconoscimento
  runRecognitionLoop();
}

function stopSession() {
  if (!isRecording) return;
  isRecording = false;

  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnReview = document.getElementById('btn-go-review');

  if (btnStart) btnStart.disabled = false;
  if (btnStop) btnStop.disabled = true;
  if (btnReview) btnReview.disabled = false;

  updateStatus('Sessione terminata', 'idle');
}

// Loop: chiama /api/start_recognition finché isRecording è true
async function runRecognitionLoop() {
  if (!isRecording) return;

  try {
    const res = await fetch('/api/start_recognition', {
      method: 'POST'
    });
    if (!res.ok) throw new Error('Errore HTTP ' + res.status);
    const data = await res.json();
    handleRecognitionResponse(data);
  } catch (err) {
    console.error(err);
    updateStatus('Errore nel riconoscimento', 'error');
  } finally {
    // Riesegui il loop solo se siamo ancora in modalità recording
    if (isRecording) {
      // Lasciamo un piccolo delay per non martellare il server
      setTimeout(runRecognitionLoop, 1000);
    }
  }
}

// ---- GESTIONE RISPOSTA / POPOLAMENTO UI -----------------------------

function handleRecognitionResponse(data) {
  const recognition = data.recognition || {};
  const sessionUpdate = data.session_update || {};

  // Aggiorna "Now playing" se il riconoscimento è andato bene
  if (recognition.status === 'success') {
    updateNowPlaying(recognition);
  } else if (recognition.status === 'not_found') {
    updateStatus('Nessun brano trovato', 'idle');
  } else if (recognition.status === 'error') {
    updateStatus('Errore API: ' + (recognition.message || ''), 'error');
  }

  // Se il SessionManager ha aggiunto un brano nuovo aggiornare playlist
  if (sessionUpdate.added) {
    // Ricarico playlist dal backend e aggiorno log + review
    fetchPlaylistAndRender().then(() => {
      if (sessionUpdate.song && sessionUpdate.song.id) {
        highlightRow(sessionUpdate.song.id);
      }
    });
  } else {
    // Duplicate / No match → opzionale: loggare da qualche parte
    if (sessionUpdate.reason === 'Duplicate') {
      console.log('Brano duplicato ignorato');
    }
  }
}

// --- NOW PLAYING CARD ------------------------------------------------

function msToMinSec(ms) {
  if (!ms || ms <= 0) return '';
  const totalSeconds = Math.round(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function updateNowPlaying(rec) {
  const titleEl = document.getElementById('now-playing-title');
  const artistEl = document.getElementById('now-playing-artist');
  const albumEl = document.getElementById('now-playing-album');
  const typeEl = document.getElementById('now-playing-type');
  const tsEl = document.getElementById('now-playing-timestamp');
  const durEl = document.getElementById('now-playing-duration');
  const scoreEl = document.getElementById('now-playing-score');

  if (titleEl) titleEl.textContent = rec.title || 'Titolo sconosciuto';
  if (artistEl) artistEl.textContent = rec.artist || 'Artista sconosciuto';
  if (albumEl) albumEl.textContent = rec.album || '';
  if (typeEl) {
    typeEl.textContent = rec.type || 'Original';
    typeEl.style.display = 'inline-block';
  }

  if (tsEl) {
    const now = new Date();
    tsEl.textContent = `Rilevato alle ${now.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
  }

  if (durEl) durEl.textContent = rec.duration_ms ? `Durata: ${msToMinSec(rec.duration_ms)}` : '';
  if (scoreEl) scoreEl.textContent = rec.score ? `Score match: ${rec.score}` : '';
}

// ---- PLAYLIST: LOAD, RENDER LIVE LOG + REVIEW -----------------------

async function fetchPlaylistAndRender() {
  try {
    const res = await fetch('/api/get_playlist');
    if (!res.ok) throw new Error('Errore HTTP ' + res.status);
    const data = await res.json();
    currentPlaylist = data.playlist || [];
    renderLiveLog();
    renderReviewTable();
    updateExportButtonState();
  } catch (err) {
    console.error(err);
  }
}

function renderLiveLog() {
  const tbody = document.getElementById('live-log-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  currentPlaylist.forEach(song => {
    const tr = document.createElement('tr');
    tr.id = `row-${song.id}`;

    // 1. Ora
    const tdTime = document.createElement('td');
    tdTime.textContent = song.timestamp || '';

    // 2. Titolo
    const tdTitle = document.createElement('td');
    tdTitle.innerHTML = `<strong>${song.title || ''}</strong>`; // Grassetto per leggibilità

    // 3. Artista
    const tdArtist = document.createElement('td');
    tdArtist.textContent = song.artist || '';

    // 4. Compositore (NUOVO)
    const tdComposer = document.createElement('td');
    tdComposer.textContent = song.composer || '-';
    tdComposer.style.fontStyle = 'italic'; // Stile corsivo opzionale
    tdComposer.style.color = '#aaa';       // Colore leggermente più scuro

    // 5. Durata
    const tdDur = document.createElement('td');
    tdDur.textContent = msToMinSec(song.duration_ms);

    // 6. Score (NUOVO)
    const tdScore = document.createElement('td');
    tdScore.textContent = song.score ? song.score + '%' : '-';

    // 7. Tipo
    const tdType = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'badge';
    badge.textContent = song.type || '';
    tdType.appendChild(badge);

    // 8. Azioni
    const tdActions = document.createElement('td');
    const btnDelete = document.createElement('button');
    btnDelete.textContent = '🗑️';
    btnDelete.className = 'btn btn-icon btn-delete';
    btnDelete.addEventListener('click', () => deleteSong(song.id));
    tdActions.appendChild(btnDelete);

    // --- ORDINE DI INSERIMENTO (Deve coincidere con l'HTML!) ---
    tr.appendChild(tdTime);
    tr.appendChild(tdTitle);
    tr.appendChild(tdArtist);
    tr.appendChild(tdComposer); // Aggiunto
    tr.appendChild(tdDur);
    tr.appendChild(tdScore);    // Aggiunto
    tr.appendChild(tdType);
    tr.appendChild(tdActions);

    tbody.appendChild(tr);
  });
}

function renderReviewTable() {
  const tbody = document.getElementById('review-table-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  currentPlaylist.forEach(song => {
    const tr = document.createElement('tr');

    // Helper per creare celle con input
    const createInputCell = (value) => {
        const td = document.createElement('td');
        const input = document.createElement('input');
        input.type = 'text';
        input.value = value || '';
        td.appendChild(input);
        return td;
    };

    // 1. Ora
    tr.appendChild(createInputCell(song.timestamp));

    // 2. Titolo
    tr.appendChild(createInputCell(song.title));

    // 3. Artista
    tr.appendChild(createInputCell(song.artist));
    
    // 4. Compositore (NUOVO - Modificabile)
    tr.appendChild(createInputCell(song.composer));

    // 5. Album
    tr.appendChild(createInputCell(song.album));

    // 6. Durata
    tr.appendChild(createInputCell(msToMinSec(song.duration_ms)));

    // 7. Tipo
    tr.appendChild(createInputCell(song.type));

    // 8. Azioni (Delete)
    const tdActions = document.createElement('td');
    const btnDelete = document.createElement('button');
    btnDelete.textContent = '🗑️';
    btnDelete.className = 'btn btn-icon btn-delete';
    btnDelete.addEventListener('click', () => deleteSong(song.id));
    tdActions.appendChild(btnDelete);
    tr.appendChild(tdActions);

    tbody.appendChild(tr);
  });
}

// ---- EXPORT BORDERÒ (CSV) -------------------------------------------

function updateExportButtonState() {
  const btn = document.getElementById('btn-export');
  if (!btn) return;
  btn.disabled = currentPlaylist.length === 0;
}

function exportBorderoCsv() {
  const tbody = document.getElementById('review-table-body');
  if (!tbody || !tbody.rows.length) return;

  // Raccoglie i dati dagli input (che sono editabili dall'utente)
  const rows = Array.from(tbody.rows).map(tr => {
    const inputs = tr.querySelectorAll('input');
    return Array.from(inputs).map(inp => {
        // Gestiamo eventuali virgolette o punti e virgola nel testo per il CSV
        let text = inp.value;
        if (text.includes(';') || text.includes('"')) {
            text = `"${text.replace(/"/g, '""')}"`; // Escape CSV standard
        }
        return text;
    });
  });

  // Intestazione del CSV (Deve corrispondere all'ordine delle colonne sopra)
  const header = ['Ora', 'Titolo', 'Artista', 'Compositore', 'Album', 'Durata', 'Tipo'];
  
  const csvLines = [];
  csvLines.push(header.join(';')); // Usiamo il punto e virgola (standard Excel europeo)

  rows.forEach(r => {
    csvLines.push(r.join(';'));
  });

  // Creazione e download del file
  const blob = new Blob([csvLines.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  
  // Nome file con data odierna
  const dateStr = new Date().toISOString().slice(0,10);
  a.download = `bordero_siae_${dateStr}.csv`;
  
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---- INIT -----------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  // Form evento → passa alla view sessione
  const eventForm = document.getElementById('event-form');
  if (eventForm) {
    eventForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const mode = eventForm.elements['mode'].value;
      const name = eventForm.elements['eventName'].value;
      const venue = eventForm.elements['eventVenue'].value;
      const date = eventForm.elements['eventDate'].value;

      const sessionTitle = document.getElementById('session-title');
      const sessionMeta = document.getElementById('session-meta');

      if (sessionTitle) {
        sessionTitle.textContent = mode === 'dj' ? 'Sessione DJ Set' : 'Sessione Live Band';
      }
      if (sessionMeta) {
        const parts = [];
        if (name) parts.push(name);
        if (venue) parts.push(venue);
        if (date) parts.push(new Date(date).toLocaleDateString('it-IT'));
        sessionMeta.textContent = parts.join(' · ');
      }

      showView('view-session');
      fetchPlaylistAndRender();
    });
  }

  // Bottoni sessione
  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnRefresh = document.getElementById('btn-refresh');
  const btnGoReview = document.getElementById('btn-go-review');

  if (btnStart) btnStart.addEventListener('click', startSession);
  if (btnStop) btnStop.addEventListener('click', stopSession);
  if (btnRefresh) btnRefresh.addEventListener('click', fetchPlaylistAndRender);
  if (btnGoReview) btnGoReview.addEventListener('click', () => {
    showView('view-review');
    fetchPlaylistAndRender();
  });

  // Bottoni review
  const btnBackSession = document.getElementById('btn-back-session');
  const btnExport = document.getElementById('btn-export');

  if (btnBackSession) btnBackSession.addEventListener('click', () => {
    showView('view-session');
  });

  if (btnExport) btnExport.addEventListener('click', exportBorderoCsv);

  // All'avvio: vista welcome, stato pronto
  showView('view-welcome');
  updateStatus('Pronto', 'idle');
});
