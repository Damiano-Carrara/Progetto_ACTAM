let isRecording = false;
let currentPlaylist = [];
let sessionTargetArtist = null; // <--- 1. Variabile globale per salvare l'artista

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

// ---- SESSIONE: START / STOP ----------------------------------

async function startSession() {
  if (isRecording) return;

  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnReview = document.getElementById('btn-go-review');

  if (btnStart) btnStart.disabled = true;
  if (btnStop) btnStop.disabled = false;
  if (btnReview) btnReview.disabled = true;

  updateStatus('Avvio motore audio...', 'recording');

  try {
    // 2. CHIAMATA UNICA ALL'API DI START (Con il Target Artist)
    const payload = {};
    if (sessionTargetArtist) {
        payload.targetArtist = sessionTargetArtist;
        console.log("🚀 Avvio con Bias Artista:", sessionTargetArtist);
    }

    const res = await fetch('/api/start_recognition', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload) // <--- Inviamo il JSON
    });

    const data = await res.json();
    
    if (data.status === 'started' || data.message === 'Già in esecuzione') {
        isRecording = true;
        updateStatus('🔴 In ascolto (Live)', 'recording');
        // 3. Avviamo il polling SOLO per aggiornare la lista, non per riconoscere
        startPlaylistPolling();
    } else {
        throw new Error(data.message || 'Errore sconosciuto');
    }

  } catch (err) {
    console.error(err);
    updateStatus('Errore: ' + err.message, 'error');
    // Reset bottoni
    if (btnStart) btnStart.disabled = false;
    if (btnStop) btnStop.disabled = true;
  }
}

async function stopSession() {
  if (!isRecording) return;
  
  try {
      // Chiamiamo l'API di stop
      await fetch('/api/stop_recognition', { method: 'POST' });
  } catch (e) { console.error(e); }

  isRecording = false;

  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnReview = document.getElementById('btn-go-review');

  if (btnStart) btnStart.disabled = false;
  if (btnStop) btnStop.disabled = true;
  if (btnReview) btnReview.disabled = false;

  updateStatus('Sessione terminata', 'idle');
}

// ---- POLLING LISTA (Nuova Funzione) ----------------------------------
// Questa sostituisce la vecchia "runRecognitionLoop". 
// Ora il backend lavora da solo, noi chiediamo solo "che novità ci sono?"

async function startPlaylistPolling() {
    if (!isRecording) return;

    await fetchPlaylistAndRender();

    if (isRecording) {
        // Aggiorna la tabella ogni 2 secondi
        setTimeout(startPlaylistPolling, 2000);
    }
}

// ---- PLAYLIST & RENDER ----------------------------------------------

async function fetchPlaylistAndRender() {
  try {
    const res = await fetch('/api/get_playlist');
    if (!res.ok) throw new Error('Errore HTTP ' + res.status);
    const data = await res.json();
    
    // Controllo se ci sono nuovi brani per evidenziarli
    const newPlaylist = data.playlist || [];
    const lastOldId = currentPlaylist.length > 0 ? currentPlaylist[currentPlaylist.length -1].id : 0;
    
    currentPlaylist = newPlaylist;
    
    renderLiveLog();
    renderReviewTable();
    updateExportButtonState();

    // Se c'è un nuovo brano (ID maggiore dell'ultimo che avevamo), evidenziamolo
    const lastNewSong = currentPlaylist[currentPlaylist.length - 1];
    if (lastNewSong && lastNewSong.id > lastOldId) {
        highlightRow(lastNewSong.id);
        // Aggiorna anche il widget "Now Playing"
        updateNowPlaying(lastNewSong);
    }

  } catch (err) {
    console.error(err);
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

  if (titleEl) titleEl.textContent = rec.title || 'In ascolto...';
  if (artistEl) artistEl.textContent = rec.artist || '';
  if (albumEl) albumEl.textContent = rec.album || '';
  if (typeEl) {
    typeEl.textContent = rec.type || 'Original';
    typeEl.style.display = 'inline-block';
  }

  if (tsEl) tsEl.textContent = rec.timestamp ? `Rilevato alle ${rec.timestamp}` : '';
  if (durEl) durEl.textContent = rec.duration_ms ? `Durata: ${msToMinSec(rec.duration_ms)}` : '';
  if (scoreEl) scoreEl.textContent = rec.score ? `Score match: ${rec.score}` : '';
}


// ---- RENDER TABELLE (Invariato rispetto a prima, ma incluso per completezza) ---

function renderLiveLog() {
  const tbody = document.getElementById('live-log-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  // Mostriamo la playlist inversa (i più recenti in alto) o normale? 
  // Di solito i log sono: nuovi in alto.
  const listToRender = [...currentPlaylist].reverse(); 

  listToRender.forEach(song => {
    const tr = document.createElement('tr');
    tr.id = `row-${song.id}`;

    const createCell = (html, isHtml=false) => {
        const td = document.createElement('td');
        if(isHtml) td.innerHTML = html; else td.textContent = html;
        return td;
    }

    tr.appendChild(createCell(song.timestamp));
    tr.appendChild(createCell(`<strong>${song.title}</strong>`, true));
    tr.appendChild(createCell(song.artist));
    
    const tdComp = document.createElement('td');
    tdComp.textContent = song.composer || '-';
    tdComp.style.fontStyle = 'italic'; 
    tdComp.style.color = '#aaa';
    tr.appendChild(tdComp);

    tr.appendChild(createCell(msToMinSec(song.duration_ms)));
    tr.appendChild(createCell(song.score ? song.score + '%' : '-'));

    const tdType = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'badge';
    badge.textContent = song.type || '';
    tdType.appendChild(badge);
    tr.appendChild(tdType);

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

function renderReviewTable() {
  const tbody = document.getElementById('review-table-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  currentPlaylist.forEach(song => {
    const tr = document.createElement('tr');
    
    const createInputCell = (value) => {
        const td = document.createElement('td');
        const input = document.createElement('input');
        input.type = 'text';
        input.value = value || '';
        td.appendChild(input);
        return td;
    };

    tr.appendChild(createInputCell(song.timestamp));
    tr.appendChild(createInputCell(song.title));
    tr.appendChild(createInputCell(song.artist));
    tr.appendChild(createInputCell(song.composer));
    tr.appendChild(createInputCell(song.album));
    tr.appendChild(createInputCell(msToMinSec(song.duration_ms)));
    tr.appendChild(createInputCell(song.type));

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

async function deleteSong(id) {
    if(!confirm("Vuoi eliminare questo brano?")) return;
    await fetch('/api/delete_song', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: id })
    });
    fetchPlaylistAndRender();
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

  const rows = Array.from(tbody.rows).map(tr => {
    const inputs = tr.querySelectorAll('input');
    return Array.from(inputs).map(inp => {
        let text = inp.value;
        if (text.includes(';') || text.includes('"')) {
            text = `"${text.replace(/"/g, '""')}"`;
        }
        return text;
    });
  });

  const header = ['Ora', 'Titolo', 'Artista', 'Compositore', 'Album', 'Durata', 'Tipo'];
  const csvLines = [header.join(';')];
  rows.forEach(r => csvLines.push(r.join(';')));

  const blob = new Blob([csvLines.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const dateStr = new Date().toISOString().slice(0,10);
  a.download = `bordero_siae_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ---- INIT -----------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  // Form Setup
  const eventForm = document.getElementById('event-form');
  if (eventForm) {
    eventForm.addEventListener('submit', (e) => {
      e.preventDefault();
      // 4. CATTURIAMO I DATI DEL FORM (incluso il nuovo artista)
      sessionTargetArtist = eventForm.elements['targetArtist'].value;
      
      const name = eventForm.elements['eventName'].value;
      const venue = eventForm.elements['eventVenue'].value;

      const sessionMeta = document.getElementById('session-meta');
      if (sessionMeta) {
          let metaText = [name, venue].filter(Boolean).join(' · ');
          if (sessionTargetArtist) metaText += ` (Bias: ${sessionTargetArtist})`;
          sessionMeta.textContent = metaText;
      }

      showView('view-session');
    });
  }

  // Bind Bottoni
  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnRefresh = document.getElementById('btn-refresh');
  const btnGoReview = document.getElementById('btn-go-review');
  const btnBackSession = document.getElementById('btn-back-session');
  const btnExport = document.getElementById('btn-export');

  if (btnStart) btnStart.addEventListener('click', startSession);
  if (btnStop) btnStop.addEventListener('click', stopSession);
  if (btnRefresh) btnRefresh.addEventListener('click', fetchPlaylistAndRender);
  if (btnGoReview) btnGoReview.addEventListener('click', () => {
    showView('view-review');
    fetchPlaylistAndRender();
  });
  if (btnBackSession) btnBackSession.addEventListener('click', () => showView('view-session'));
  if (btnExport) btnExport.addEventListener('click', exportBorderoCsv);

  showView('view-welcome');
  updateStatus('Pronto', 'idle');
});