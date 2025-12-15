// --- STATO APP ---
const state = {
  mode: null,          // "dj" | "band" | "concert"
  route: "welcome",    // "welcome" | "session" | "review"
  concertArtist: "",
  bandArtist: "",      // artista opzionale per live band
  notes: ""            // note su mismatch/errori dalla sessione
};

// playlist locale (frontend)
let songs = []; // ogni song può avere .order (indice originale)

// id massimo visto (per capire quali brani sono nuovi quando facciamo polling)
let lastMaxSongId = 0;

// brano attualmente mostrato come "Now playing"
let currentSongId = null;

// [NUOVO] URL Copertina attuale (per evitare refresh inutili dello sfondo)
let currentCoverUrl = null;

// polling della playlist backend
let playlistPollInterval = null;

// timer sessione
let sessionStartMs = 0;
let sessionAccumulatedMs = 0;
let sessionTick = null;

// undo stack (ultimi 5 stati della playlist in review)
let undoStack = [];

// snapshot eventuale per tornare da review a sessione (se servirà)
let lastSessionSnapshot = null;

// stato dell'onda
let waveMode = "idle"; // "idle" | "playing" | "paused"

// --- VISUALIZER: equalizzatore continuo full-width ---
const VIS_COLS = 96;
const VIS_ROWS = 16;

let visTick = null;
let visLevels = new Array(VIS_COLS).fill(0);

// contesto attuale del modal note: "session" | "review"
let notesModalContext = "session";

/** selettore rapido */
const $ = (sel) => document.querySelector(sel);

// --- UTILS ---
function pad2(n) {
  return n.toString().padStart(2, "0");
}

function fmt(ms) {
  const sec = Math.floor(ms / 1000);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${pad2(m)}:${pad2(s)}`;
}

// --- SALVATAGGIO STATO LOCALE ---
function saveStateToLocal() {
  if (!state.mode) return;
  localStorage.setItem("appMode", state.mode);
  if (state.concertArtist) localStorage.setItem("concertArtist", state.concertArtist);
  else localStorage.removeItem("concertArtist");
  if (state.bandArtist) localStorage.setItem("bandArtist", state.bandArtist);
  else localStorage.removeItem("bandArtist");
}

// --- THEME (colore coerente alla modalità) ---
function applyTheme() {
  const app = document.getElementById("app");
  if (!app) return;
  app.classList.remove("theme-dj", "theme-band", "theme-concert");

  if (state.mode === "band") app.classList.add("theme-band");
  else if (state.mode === "concert") app.classList.add("theme-concert");
  else if (state.mode === "dj") app.classList.add("theme-dj");
}

// --- NAVIGAZIONE / ROUTE ---
function setRoute(route) {
  state.route = route;
  const body = document.body;
  if (body) {
    if (route === "welcome" || route === "session") body.classList.add("no-scroll");
    else body.classList.remove("no-scroll");
  }
}

function showView(id) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("view--active"));
  const el = document.querySelector(id);
  if (el) el.classList.add("view--active");
}

// --- VISUALIZER ---
function buildVisualizer() {
  const container = document.querySelector("#visualizer");
  if (!container) return;
  container.innerHTML = "";
  for (let c = 0; c < VIS_COLS; c++) {
    const col = document.createElement("div");
    col.className = "vis-col";
    for (let r = 0; r < VIS_ROWS; r++) {
      const cell = document.createElement("div");
      cell.className = "vis-cell";
      col.appendChild(cell);
    }
    container.appendChild(col);
  }
}

function updateVisualizer() {
  const cols = document.querySelectorAll(".vis-col");
  if (!cols.length) return;
  for (let colIndex = 0; colIndex < cols.length; colIndex++) {
    let current = visLevels[colIndex] || 0;
    let base = Math.pow(Math.random(), 3.2);
    let target = base * VIS_ROWS * 0.9;
    if (Math.random() < 0.1) target = VIS_ROWS * (0.55 + 0.45 * Math.random());

    const speedUp = 0.45;
    const speedDown = 0.12;
    if (target > current) current += (target - current) * speedUp;
    else current += (target - current) * speedDown;

    current *= 0.985;
    if (current < 0) current = 0;
    if (current > VIS_ROWS) current = VIS_ROWS;
    visLevels[colIndex] = current;

    const cells = cols[colIndex].children;
    const levelRounded = Math.round(current);
    for (let i = 0; i < VIS_ROWS; i++) {
      const active = i < levelRounded;
      cells[i].classList.toggle("active", active);
    }
  }
}

function startVisualizer() {
  if (visTick) return;
  visLevels = new Array(VIS_COLS).fill(0);
  visTick = setInterval(updateVisualizer, 80);
}

function pauseVisualizer() {
  if (!visTick) return;
  clearInterval(visTick);
  visTick = null;
}

function stopVisualizer() {
  pauseVisualizer();
  document.querySelectorAll(".vis-cell.active").forEach((cell) => cell.classList.remove("active"));
  visLevels = new Array(VIS_COLS).fill(0);
}

// --- SESSION HEADER ---
function hydrateSessionHeader() {
  const badge = $("#mode-badge");
  if (!badge) return;
  if (state.mode === "band") {
    badge.textContent = state.bandArtist ? `Live band – ${state.bandArtist}` : "Live band";
  } else if (state.mode === "concert") {
    badge.textContent = state.concertArtist ? `Concerto – ${state.concertArtist}` : "Concerto";
  } else {
    badge.textContent = "DJ set";
  }
  applyTheme();
}

// --- NOW PLAYING ---
function setNow(title, composer) {
  const titleEl = $("#now-title");
  const compEl = $("#now-composer");
  if (titleEl) titleEl.textContent = title || "In ascolto";
  if (compEl) compEl.textContent = composer || "—";
}

// --- LOG LIVE (AGGIORNATO PER COVER) ---
function pushLog({ id, index, title, composer, artist, cover }) {
  const row = document.createElement("div");
  row.className = "log-row";
  if (id != null) row.dataset.id = id;

  // Se c'è cover -> tag IMG. Se no -> Placeholder grigio.
  const imgHtml = cover 
    ? `<img src="${cover}" alt="Cover" loading="lazy">` 
    : `<div style="width:32px; height:32px; background: rgba(255,255,255,0.1); border-radius:4px;"></div>`;

  row.innerHTML = `
    <span class="col-index">${index != null ? index : "—"}</span>
    <span class="col-cover">${imgHtml}</span>
    <span>${title || "—"}</span>
    <span class="col-composer">${composer || "—"}</span>
    <span class="col-artist">${artist || "—"}</span>
  `;

  $("#live-log").prepend(row);
}

// --- TIMER SESSIONE ---
function startSessionTimer() {
  if (sessionTick) return;
  sessionStartMs = Date.now();
  sessionTick = setInterval(() => {
    const elapsed = sessionAccumulatedMs + (Date.now() - sessionStartMs);
    const el = $("#session-timer");
    if (el) el.textContent = fmt(elapsed);
  }, 1000);
}

function pauseSessionTimer() {
  if (!sessionTick) return;
  clearInterval(sessionTick);
  sessionTick = null;
  sessionAccumulatedMs += Date.now() - sessionStartMs;
}

function resetSessionTimer() {
  clearInterval(sessionTick);
  sessionTick = null;
  sessionStartMs = 0;
  sessionAccumulatedMs = 0;
  const el = $("#session-timer");
  if (el) el.textContent = "00:00";
}

// --- UNDO ---
function pushUndoState() {
  const snapshot = songs.map((s) => ({ ...s }));
  undoStack.push(snapshot);
  if (undoStack.length > 5) undoStack.shift();
  updateUndoButton();
}

function updateUndoButton() {
  const btnUndo = $("#btn-undo");
  if (!btnUndo) return;
  btnUndo.disabled = undoStack.length === 0;
}

function undoLast() {
  if (!undoStack.length) return;
  const snapshot = undoStack.pop();
  songs = snapshot.map((s) => ({ ...s }));
  renderReview();
  updateUndoButton();
}

// --- BACKEND START/STOP ---
async function startBackendRecognition() {
  const body = {};
  let targetArtist = null;
  if (state.mode === "concert" && state.concertArtist) targetArtist = state.concertArtist;
  else if (state.mode === "band" && state.bandArtist) targetArtist = state.bandArtist;
  if (targetArtist) body.targetArtist = targetArtist;

  try {
    await fetch("/api/start_recognition", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  } catch (err) { console.error(err); }
}

async function stopBackendRecognition() {
  try {
    await fetch("/api/stop_recognition", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
  } catch (err) { console.error(err); }
}

// --- AGGIORNAMENTO SFONDO (NUOVO) ---
function updateBackground(url) {
    const bgEl = document.getElementById("app-background");
    if (!bgEl) return;

    if (url) {
        // Precarica immagine per evitare "flash" neri
        const img = new Image();
        img.src = url;
        img.onload = () => {
            bgEl.style.backgroundImage = `url('${url}')`;
            bgEl.style.opacity = "1";
        };
    } else {
        bgEl.style.opacity = "0"; // Nasconde se non c'è cover
    }
}

// --- POLLING PLAYLIST (MERGED: COVER + METADATA) ---
async function pollPlaylistOnce() {
  try {
    // Aggiungiamo timestamp per evitare cache
    const res = await fetch("/api/get_playlist?t=" + Date.now());
    if (!res.ok) return;

    const data = await res.json();
    const playlist = Array.isArray(data.playlist) ? data.playlist : [];

    let maxIdSeen = lastMaxSongId;
    let updatedExisting = false;

    playlist.forEach((song) => {
      const id = Number(song.id);
      if (!Number.isFinite(id)) return;
      const existing = songs.find((t) => t.id === id);

      if (!existing) {
        // NUOVO BRANO
        if (id > lastMaxSongId) {
          const track = {
            id,
            order: songs.length + 1,
            title: song.title || "Titolo sconosciuto",
            composer: song.composer || "—",
            artist: song.artist || "",
            album: song.album || "",
            type: song.type || "",
            isrc: song.isrc || null,
            upc: song.upc || null,
            ms: song.duration_ms || 0,
            confirmed: false,
            timestamp: song.timestamp || null,
            cover: song.cover || null, // [NUOVO]
            // Backup dati originali per Raw Report
            original_title: song.title,
            original_composer: song.composer,
            original_artist: song.artist
          };

          songs.push(track);
          currentSongId = track.id;
          setNow(track.title, track.composer);

          pushLog({
            id: track.id,
            index: track.order,
            title: track.title,
            composer: track.composer,
            artist: track.artist,
            cover: track.cover // [NUOVO]
          });
        }
      } else {
        // BRANO ESISTENTE
        const oldComposer = existing.composer;
        const oldArtist = existing.artist;
        const oldCover = existing.cover;

        // Aggiorna metadati se non confermati dall'utente
        if (!existing.confirmed) {
            existing.title = song.title || existing.title;
            existing.composer = song.composer || existing.composer;
            existing.artist = song.artist || existing.artist;
            // ...altri campi se servono...
        }
        
        // La cover si aggiorna SEMPRE se ne arriva una nuova migliore
        if (song.cover && song.cover !== existing.cover) {
             existing.cover = song.cover;
        }

        const composerChanged = existing.composer !== oldComposer;
        const artistChanged = existing.artist !== oldArtist;
        const coverChanged = existing.cover !== oldCover;
        const logRow = document.querySelector(`.log-row[data-id="${id}"]`);

        // AGGIORNAMENTO DOM IMMEDIATO
        if (logRow && coverChanged && existing.cover) {
             const coverSpan = logRow.querySelector(".col-cover");
             if (coverSpan) {
                 coverSpan.innerHTML = `<img src="${existing.cover}" alt="Cover" loading="lazy">`;
             }
        }

        if (composerChanged || artistChanged) {
          updatedExisting = true;
          if (currentSongId === id) setNow(existing.title, existing.composer);

          if (logRow) {
            const compSpan = logRow.querySelector(".col-composer");
            if (compSpan) compSpan.textContent = existing.composer;
            const artSpan = logRow.querySelector(".col-artist");
            if (artSpan) artSpan.textContent = existing.artist || "—";
          }
        }
      }
      if (id > maxIdSeen) maxIdSeen = id;
    });

    lastMaxSongId = maxIdSeen;

    // [NUOVO] Logica Sfondo Dinamico
    // Trova l'ultimo brano che ha una cover
    const lastSongWithCover = [...songs].reverse().find(s => s.cover);
    if (lastSongWithCover && lastSongWithCover.cover !== currentCoverUrl) {
        currentCoverUrl = lastSongWithCover.cover;
        updateBackground(currentCoverUrl);
    }

    if (updatedExisting && state.route === "review") renderReview();

  } catch (err) { console.error(err); }
}

function startPlaylistPolling() {
  if (playlistPollInterval) return;
  pollPlaylistOnce();
  playlistPollInterval = setInterval(pollPlaylistOnce, 2000);
}

function stopPlaylistPolling() {
  if (!playlistPollInterval) return;
  clearInterval(playlistPollInterval);
  playlistPollInterval = null;
}

// --- SESSION ACTIONS ---
async function sessionStart() {
  setRoute("session");
  showView("#view-session");
  hydrateSessionHeader();

  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  if (btnStart) btnStart.disabled = true;
  if (btnPause) btnPause.disabled = false;
  if (btnStop) btnStop.disabled = false;

  waveMode = "playing";
  if (!sessionTick) startSessionTimer();

  await startBackendRecognition();
  startPlaylistPolling();
  startVisualizer();
}

async function sessionPause() {
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = false;

  waveMode = "paused";
  pauseSessionTimer();
  await stopBackendRecognition();
  stopPlaylistPolling();
  pauseVisualizer();
}

async function sessionStop() {
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = true;

  waveMode = "idle";
  pauseSessionTimer();
  await stopBackendRecognition();
  stopPlaylistPolling();
  await pollPlaylistOnce();
  resetSessionTimer();
  currentSongId = null;
  setNow("In ascolto", "—");

  // === MODIFICA: Reset dello sfondo quando ci si ferma ===
  currentCoverUrl = null;
  updateBackground(null);
  // ====================================================

  undoStack = [];
  renderReview();
  setRoute("review");
  showView("#view-review");
  stopVisualizer();
}

async function sessionReset() {
  waveMode = "idle";
  await stopBackendRecognition();
  stopPlaylistPolling();
  pauseSessionTimer();
  resetSessionTimer();

  try {
    await fetch("/api/reset_session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
  } catch (err) { console.error(err); }

  localStorage.removeItem("appMode");
  localStorage.removeItem("concertArtist");
  localStorage.removeItem("bandArtist");

  currentSongId = null;
  setNow("In ascolto", "—");
  songs = [];
  undoStack = [];
  updateUndoButton();
  $("#live-log").innerHTML = "";
  lastMaxSongId = 0;
  
  // Reset Sfondo
  currentCoverUrl = null;
  updateBackground(null);

  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = true;
  stopVisualizer();
}

// --- REVIEW LOGIC ---
function renderReview() {
  const container = $("#review-rows");
  const template = $("#review-row-template");
  const btnGenerate = $("#btn-generate");
  if (!container || !template || !btnGenerate) return;

  container.innerHTML = "";
  songs.forEach((song, index) => {
    if (typeof song.confirmed !== "boolean") song.confirmed = false;
    const node = template.content.firstElementChild.cloneNode(true);

    const indexSpan = node.querySelector(".review-index");
    const inputComposer = node.querySelector('[data-field="composer"]');
    const inputTitle = node.querySelector('[data-field="title"]');
    const btnConfirm = node.querySelector(".btn-confirm");
    const btnEdit = node.querySelector(".btn-edit");
    const btnDelete = node.querySelector(".btn-delete");
    const btnAdd = node.querySelector(".btn-add");

    if (indexSpan) indexSpan.textContent = index + 1;
    inputComposer.value = song.composer || "";
    inputTitle.value = song.title || "";
    inputComposer.readOnly = true;
    inputTitle.readOnly = true;

    if (song.confirmed) node.classList.add("row--confirmed");

    btnEdit.addEventListener("click", (e) => {
      e.preventDefault();
      inputComposer.readOnly = false;
      inputTitle.readOnly = false;
      song.confirmed = false;
      node.classList.remove("row--confirmed");
      updateGenerateState();
      inputTitle.focus();
    });

    btnConfirm.addEventListener("click", (e) => {
      e.preventDefault();
      pushUndoState();
      song.composer = inputComposer.value || "";
      song.title = inputTitle.value || "";
      song.confirmed = true;
      inputComposer.readOnly = true;
      inputTitle.readOnly = true;
      node.classList.add("row--confirmed");
      updateGenerateState();
    });

    btnDelete.addEventListener("click", async (e) => {
      e.preventDefault();
      const ok = await showConfirm("Sei sicuro di voler cancellare questo brano?");
      if (!ok) return;
      pushUndoState();

      if (song.id != null) {
        try {
          await fetch("/api/delete_song", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: song.id })
          });
        } catch (err) { console.error(err); }
      }
      const idx = songs.indexOf(song);
      if (idx !== -1) songs.splice(idx, 1);
      renderReview();
    });

    if (btnAdd) {
      btnAdd.addEventListener("click", (e) => {
        e.preventDefault();
        pushUndoState();
        const idx = songs.indexOf(song);
        const insertPos = idx === -1 ? songs.length : idx + 1;
        const newSong = { id: null, title: "", composer: "", artist: "", confirmed: false, manual: true };
        songs.splice(insertPos, 0, newSong);
        renderReview();
      });
    }
    container.appendChild(node);
  });

  function updateGenerateState() {
    const total = songs.length;
    const ok = total > 0;
    btnGenerate.disabled = !ok;
  }
  updateGenerateState();
  updateUndoButton();
  syncReviewNotes();
}

// --- WELCOME & MODALS ---
function syncWelcomeModeRadios() {
  const cards = document.querySelectorAll(".mode-card");
  cards.forEach((card) => card.classList.remove("mode-card--selected", "active"));

  const djCard = document.querySelector('.mode-card[data-mode="dj"]');
  const bandCard = document.querySelector('.mode-card[data-mode="band"]');
  const concertCard = document.querySelector('.mode-card[data-mode="concert"]');

  const artistWrapper = document.getElementById("artistInputWrapper");
  const artistInput = document.getElementById("artistInput");
  const bandWrapper = document.getElementById("bandArtistWrapper");
  const bandInput = document.getElementById("bandArtistInput");
  const djWrapper = document.getElementById("djConfirmWrapper");

  if (artistWrapper) artistWrapper.classList.remove("visible");
  if (bandWrapper) bandWrapper.classList.remove("visible");
  if (djWrapper) djWrapper.classList.remove("visible");

  if (state.mode === "dj" && djCard) {
    djCard.classList.add("mode-card--selected");
    if (djWrapper) djWrapper.classList.add("visible");
  } else if (state.mode === "band" && bandCard) {
    bandCard.classList.add("mode-card--selected");
    if (bandWrapper) bandWrapper.classList.add("visible");
    if (bandInput) bandInput.value = state.bandArtist || "";
  } else if (state.mode === "concert" && concertCard) {
    concertCard.classList.add("mode-card--selected", "active");
    if (artistWrapper) artistWrapper.classList.add("visible");
    if (artistInput) artistInput.value = state.concertArtist || "";
  }
}

function initWelcome() {
  const modeCards = document.querySelectorAll(".mode-card");
  const artistInput = document.getElementById("artistInput");
  const artistConfirmBtn = document.getElementById("artistConfirmBtn");
  const bandInput = document.getElementById("bandArtistInput");
  const bandConfirmBtn = document.getElementById("bandConfirmBtn");
  const djConfirmBtn = document.getElementById("djConfirmBtn");

  state.mode = null;
  applyTheme();
  syncWelcomeModeRadios();

  function goToSession() {
    hydrateSessionHeader();
    setRoute("session");
    showView("#view-session");
  }

  modeCards.forEach((card) => {
    card.addEventListener("click", () => {
      state.mode = card.dataset.mode;
      // Reset artisti se cambio modalità
      if (state.mode === "dj") { state.concertArtist = ""; state.bandArtist = ""; }
      applyTheme();
      syncWelcomeModeRadios();
      // Focus input
      if (state.mode === "concert" && artistInput) setTimeout(() => artistInput.focus(), 10);
      if (state.mode === "band" && bandInput) setTimeout(() => bandInput.focus(), 10);
    });
  });

  if (artistConfirmBtn) {
    artistConfirmBtn.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      const name = artistInput.value.trim();
      if (!name) return alert("Inserisci nome artista");
      state.concertArtist = name;
      saveStateToLocal();
      goToSession();
    });
  }

  if (bandConfirmBtn) {
    bandConfirmBtn.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      state.bandArtist = bandInput ? bandInput.value.trim() : "";
      saveStateToLocal();
      goToSession();
    });
  }

  if (djConfirmBtn) {
    djConfirmBtn.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      state.concertArtist = ""; state.bandArtist = "";
      saveStateToLocal();
      goToSession();
    });
  }
}

// --- WIRING BOTTONI ---
function wireSessionButtons() {
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  const btnReset = $("#btn-session-reset");
  const btnShowQr = $("#btn-show-qr");
  const qrModal = $("#qr-modal");

  if (btnShowQr) {
    btnShowQr.addEventListener("click", () => {
       const img = document.getElementById("qr-image");
       img.src = "/api/get_qr_image?t=" + Date.now();
       qrModal.classList.remove("modal--hidden");
    });
  }

  if (qrModal) {
    const closeBtn = qrModal.querySelector("#qr-close");
    const backdrop = qrModal.querySelector(".modal-backdrop");
    if(closeBtn) closeBtn.onclick = () => qrModal.classList.add("modal--hidden");
    if(backdrop) backdrop.onclick = () => qrModal.classList.add("modal--hidden");
  }

  if (btnStart) btnStart.onclick = (e) => { e.preventDefault(); sessionStart(); };
  if (btnPause) btnPause.onclick = (e) => { e.preventDefault(); sessionPause(); };
  if (btnStop) btnStop.onclick = async (e) => { 
    e.preventDefault(); 
    if(await showConfirm("Passare alla review?")) sessionStop(); 
  };
  if (btnReset) btnReset.onclick = async (e) => {
    e.preventDefault();
    if(await showConfirm("Resettare tutto?")) sessionReset();
  };

  // GESTIONE EXPORT
  const btnGenerate = $("#btn-generate");
  const exportModal = $("#export-modal");
  
  if (btnGenerate) {
      btnGenerate.onclick = (e) => {
          e.preventDefault();
          if(songs.length === 0) return alert("Nessun brano.");
          exportModal.classList.remove("modal--hidden");
      };
  }

  async function downloadReport(fmt) {
      // Chiudi modale
      exportModal.classList.add("modal--hidden");
      
      let exportArtist = "Various";
      if (state.mode === "concert") exportArtist = state.concertArtist;
      if (state.mode === "band") exportArtist = state.bandArtist;
      if (state.mode === "dj") exportArtist = "DJ_Set";

      try {
          const res = await fetch("/api/generate_report", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ songs: songs, mode: state.mode, artist: exportArtist, format: fmt })
          });
          if(!res.ok) throw new Error("Errore export");
          
          const blob = await res.blob();
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.style.display = "none";
          a.href = url;
          a.download = `report.${fmt === 'excel' ? 'xlsx' : 'pdf'}`;
          document.body.appendChild(a);
          a.click();
          window.URL.revokeObjectURL(url);
      } catch(e) { console.error(e); alert("Errore download"); }
  }

  const btnExcel = $("#btn-export-excel");
  const btnPdf = $("#btn-export-pdf");
  const btnRaw = $("#btn-export-raw");
  const btnCloseExp = $("#btn-export-close");

  if(btnExcel) btnExcel.onclick = () => downloadReport("excel");
  if(btnPdf) btnPdf.onclick = () => downloadReport("pdf_official");
  if(btnRaw) btnRaw.onclick = () => downloadReport("pdf_raw");
  if(btnCloseExp) btnCloseExp.onclick = () => exportModal.classList.add("modal--hidden");

  // Altri bottoni standard (undo, back, notes)...
  const btnUndo = $("#btn-undo");
  if(btnUndo) btnUndo.onclick = (e) => { e.preventDefault(); undoLast(); };
  
  const btnBackSession = $("#btn-back-session");
  if(btnBackSession) btnBackSession.onclick = backToSessionFromReview;
  
  const btnBackWelcome = $("#btn-back-welcome");
  if(btnBackWelcome) btnBackWelcome.onclick = () => { setRoute("welcome"); showView("#view-welcome"); };
  
  const btnNotes = $("#btn-session-notes");
  if(btnNotes) btnNotes.onclick = () => openNotesModal("session");
  
  const btnRevNotes = $("#btn-review-notes");
  if(btnRevNotes) btnRevNotes.onclick = () => openNotesModal("review");

  const notesCancel = $("#notes-cancel");
  const notesSave = $("#notes-save");
  if(notesCancel) notesCancel.onclick = () => closeNotesModal(false);
  if(notesSave) notesSave.onclick = () => closeNotesModal(true);
}

// --- RESTORE LOGIC ---
async function checkRestoreSession() {
  try {
    const res = await fetch("/api/get_playlist");
    if (!res.ok) return;
    const data = await res.json();
    if (!data.playlist || data.playlist.length === 0) return;

    const modal = document.getElementById("restore-modal");
    const btnNew = document.getElementById("restore-new");
    const btnRecover = document.getElementById("restore-ok");

    if (!modal) return;
    modal.classList.remove("modal--hidden");

    btnNew.onclick = async () => {
      await fetch("/api/reset_session", { method: "POST" });
      localStorage.removeItem("appMode");
      localStorage.removeItem("concertArtist");
      localStorage.removeItem("bandArtist");
      modal.classList.add("modal--hidden");
      songs = [];
    };

    btnRecover.onclick = () => {
      modal.classList.add("modal--hidden");
      const savedMode = localStorage.getItem("appMode");
      if (savedMode) {
        state.mode = savedMode;
        state.concertArtist = localStorage.getItem("concertArtist") || "";
        state.bandArtist = localStorage.getItem("bandArtist") || "";
        sessionStart();
      } else {
        alert("Dati recuperati! Seleziona la modalità.");
      }
    };
  } catch (err) { console.error(err); }
}

// --- NOTE MODALS & CONFIRM ---
function syncReviewNotes() {
  const view = $("#review-notes-view");
  if (view) view.textContent = (state.notes || "").trim() || "—";
}
function openNotesModal(ctx) {
  notesModalContext = ctx;
  const modal = $("#notes-modal");
  const ta = $("#notes-textarea");
  const save = $("#notes-save");
  if(!modal) return;
  ta.value = state.notes || "";
  if(ctx === "review") { ta.readOnly = true; save.classList.add("hidden"); }
  else { ta.readOnly = false; save.classList.remove("hidden"); }
  modal.classList.remove("modal--hidden");
}
function closeNotesModal(save) {
  const modal = $("#notes-modal");
  if(save && notesModalContext !== "review") {
      state.notes = $("#notes-textarea").value || "";
      syncReviewNotes();
  }
  modal.classList.add("modal--hidden");
}

function showConfirm(msg) {
  return new Promise((resolve) => {
    const m = $("#confirm-modal");
    $("#confirm-message").textContent = msg || "Sicuro?";
    m.classList.remove("modal--hidden");
    const ok = $("#confirm-ok");
    const cancel = $("#confirm-cancel");
    
    function cleanup(res) {
       m.classList.add("modal--hidden");
       ok.removeEventListener("click", onOk);
       cancel.removeEventListener("click", onCancel);
       resolve(res);
    }
    function onOk() { cleanup(true); }
    function onCancel() { cleanup(false); }
    
    ok.addEventListener("click", onOk);
    cancel.addEventListener("click", onCancel);
  });
}

// --- BOOTSTRAP ---
document.addEventListener("DOMContentLoaded", () => {
  const app = document.getElementById("app");
  const isViewer = app.dataset.viewer === "true";

  wireSessionButtons();
  buildVisualizer();

  if (isViewer) {
    state.route = "session";
    showView("#view-session");
    hydrateSessionHeader();
    startPlaylistPolling();
    startVisualizer();
    const rm = document.getElementById("restore-modal");
    if(rm) rm.classList.add("modal--hidden");
  } else {
    setRoute("welcome");
    showView("#view-welcome");
    initWelcome();
    checkRestoreSession();
    syncReviewNotes();
  }
});