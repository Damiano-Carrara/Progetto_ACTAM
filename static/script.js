// --- STATO APP ---
const state = {
  mode: null,       // "dj" | "band" | "concert"
  route: "welcome", // "welcome" | "session" | "review"
  concertArtist: "",
  bandArtist: "",   // artista opzionale per live band
  notes: ""         // note su mismatch/errori dalla sessione
};

// playlist locale (frontend)
let songs = []; // ogni song può avere .order (indice originale)

// id massimo visto (per capire quali brani sono nuovi quando facciamo polling)
let lastMaxSongId = 0;

// brano attualmente mostrato come "Now playing"
let currentSongId = null;

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

let currentCoverUrl = null;

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

function nowHHMM() {
  const d = new Date();
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

// --- SALVATAGGIO STATO LOCALE (Dal Collega - Per Restore) ---
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

// --- VISUALIZER BUILD + UPDATE (Tua logica originale completa) ---
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

// --- LOG LIVE ---
function pushLog({ id, index, title, composer, artist, cover}) {
  const row = document.createElement("div");
  row.className = "log-row";

  if (id != null) row.dataset.id = id;

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

// --- BACKEND START/STOP RICONOSCIMENTO ---
async function startBackendRecognition() {
  const body = {};
  let targetArtist = null;

  if (state.mode === "concert" && state.concertArtist) targetArtist = state.concertArtist;
  else if (state.mode === "band" && state.bandArtist) targetArtist = state.bandArtist;

  if (targetArtist) body.targetArtist = targetArtist;

  try {
    const res = await fetch("/api/start_recognition", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      console.error("Errore HTTP /api/start_recognition:", res.status);
      return;
    }

    const data = await res.json();
    console.log("start_recognition:", data);
  } catch (err) {
    console.error("Errore fetch /api/start_recognition:", err);
  }
}

async function stopBackendRecognition() {
  try {
    const res = await fetch("/api/stop_recognition", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });

    if (!res.ok) {
      console.error("Errore HTTP /api/stop_recognition:", res.status);
      return;
    }

    const data = await res.json();
    console.log("stop_recognition:", data);
  } catch (err) {
    console.error("Errore fetch /api/stop_recognition:", err);
  }
}

// --- POLLING PLAYLIST (Tua logica di aggiornamento metadata completa) ---
// --- POLLING PLAYLIST (Aggiornata) ---
// --- POLLING PLAYLIST (Aggiornata e corretta) ---
async function pollPlaylistOnce() {
  try {
    // FIX 1: Aggiunto ?t=timestamp per evitare che il browser usi la cache
    const res = await fetch("/api/get_playlist?t=" + Date.now());
    
    if (!res.ok) {
      console.error("Errore HTTP /api/get_playlist:", res.status);
      return;
    }

    const data = await res.json();
    const playlist = Array.isArray(data.playlist) ? data.playlist : [];

    let maxIdSeen = lastMaxSongId;
    let updatedExisting = false;

    playlist.forEach((song) => {
      const id = Number(song.id);
      if (!Number.isFinite(id)) return;

      const existing = songs.find((t) => t.id === id);

      if (!existing) {
        // --- NUOVO BRANO ---
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
            cover: song.cover || null, // Importante: ora gestiamo la cover!
            original_title: song.title,
            original_composer: song.composer,
            original_artist: song.artist
          };

          songs.push(track);
          currentSongId = track.id;
          setNow(track.title, track.composer);

          // Aggiunge la riga al Log Live (in cima)
          pushLog({
            id: track.id,
            index: track.order,
            title: track.title,
            composer: track.composer,
            artist: track.artist,
            cover: track.cover
          });
        }
      } else {
        // --- BRANO ESISTENTE (AGGIORNAMENTO) ---
        
        // FIX 2: Definiamo le variabili PRIMA di usarle (questo causava il blocco!)
        const oldComposer = existing.composer;
        const oldArtist = existing.artist;
        
        // Aggiorniamo i dati locali
        if (song.cover && song.cover !== existing.cover) {
             existing.cover = song.cover;
             // Aggiornamento puntuale della cover nel DOM
             const logRow = document.querySelector(`.log-row[data-id="${id}"]`);
             if (logRow) {
                 const coverSpan = logRow.querySelector(".col-cover");
                 // Se prima non c'era o è cambiata, la aggiorniamo
                 if (coverSpan) coverSpan.innerHTML = `<img src="${existing.cover}" alt="Cover" loading="lazy">`;
             }
             updatedExisting = true; 
        }

        if (!existing.confirmed) {
          existing.title = song.title || existing.title;
          existing.composer = song.composer || existing.composer;
          existing.artist = song.artist || existing.artist;
        }

        const composerChanged = existing.composer !== oldComposer;
        const artistChanged = existing.artist !== oldArtist;

        if (composerChanged || artistChanged) {
          updatedExisting = true;
          if (currentSongId === id) setNow(existing.title, existing.composer);

          // Aggiorna il testo nel Log Live
          const logRow = document.querySelector(`.log-row[data-id="${id}"]`);
          if (logRow) {
            const composerSpan = logRow.querySelector(".col-composer");
            if (composerSpan) composerSpan.textContent = existing.composer;

            const artistSpan = logRow.querySelector(".col-artist");
            if (artistSpan) artistSpan.textContent = existing.artist || "—";
          }
        }
      }

      if (id > maxIdSeen) maxIdSeen = id;
    });

    lastMaxSongId = maxIdSeen;

    // Aggiornamento sfondo dinamico se l'ultimo brano ha una cover
    const lastSongWithCover = [...songs].reverse().find(s => s.cover);
    if (lastSongWithCover && lastSongWithCover.cover !== currentCoverUrl) {
        currentCoverUrl = lastSongWithCover.cover;
        if (typeof updateBackground === "function") updateBackground(currentCoverUrl);
    }

    // Se siamo nella vista Review, ricarichiamo la tabella completa
    if (updatedExisting && state.route === "review") renderReview();
    
  } catch (err) {
    console.error("Errore nel polling playlist:", err);
  }
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

// --- SESSION CONTROLS ---
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
    console.log("Richiesta reset database backend...");
    await fetch("/api/reset_session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
  } catch (err) {
    console.error("Errore durante il reset del backend:", err);
  }

  localStorage.removeItem("appMode");
  localStorage.removeItem("concertArtist");
  localStorage.removeItem("bandArtist");

  currentSongId = null;
  setNow("In ascolto", "—");

  songs = [];
  undoStack = [];
  updateUndoButton();

  const liveLog = $("#live-log");
  if (liveLog) liveLog.innerHTML = "";

  lastMaxSongId = 0;

  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");

  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = true;

  stopVisualizer();
}

// --- REVIEW / SNAPSHOT (per ora snapshot non usato ma tenuto) ---
function restoreSessionFromSnapshot() {
  if (!lastSessionSnapshot) return;

  songs = lastSessionSnapshot.songs.map((s) => ({ ...s }));

  const snapshotCurrentId = lastSessionSnapshot.currentSongId ?? null;
  currentSongId = snapshotCurrentId;

  sessionAccumulatedMs = lastSessionSnapshot.sessionAccumulatedMs || 0;
  sessionStartMs = 0;
  sessionTick = null;

  const timerEl = $("#session-timer");
  if (timerEl) timerEl.textContent = fmt(sessionAccumulatedMs);

  const current = currentSongId != null ? songs.find((s) => s.id === currentSongId) : null;

  if (current) setNow(current.title, current.composer);
  else setNow("In ascolto", "—");

  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");

  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = false;
}

function backToSessionFromReview() {
  restoreSessionFromSnapshot();
  setRoute("session");
  showView("#view-session");
}

// --- NOTE SESSIONE ---
function syncReviewNotes() {
  const view = $("#review-notes-view");
  if (!view) return;

  const text = (state.notes || "").trim();
  view.textContent = text || "—";
}

function openNotesModal(context = "session") {
  const modal = $("#notes-modal");
  const textarea = $("#notes-textarea");
  const saveBtn = $("#notes-save");
  if (!modal || !textarea) return;

  notesModalContext = context;
  textarea.value = state.notes || "";

  if (context === "review") {
    textarea.readOnly = true;
    if (saveBtn) saveBtn.classList.add("hidden");
  } else {
    textarea.readOnly = false;
    if (saveBtn) saveBtn.classList.remove("hidden");
  }

  modal.classList.remove("modal--hidden");
}

function closeNotesModal(save) {
  const modal = $("#notes-modal");
  const textarea = $("#notes-textarea");
  if (!modal || !textarea) return;

  if (save && notesModalContext !== "review") {
    state.notes = textarea.value || "";
    syncReviewNotes();
  }

  modal.classList.add("modal--hidden");
}

// --- MODAL DI CONFERMA ---
function showConfirm(message) {
  return new Promise((resolve) => {
    const modal = $("#confirm-modal");
    const msgEl = $("#confirm-message");
    const btnOk = $("#confirm-ok");
    const btnCancel = $("#confirm-cancel");

    if (!modal || !msgEl || !btnOk || !btnCancel) {
      resolve(false);
      return;
    }

    msgEl.textContent = message || "Sei sicuro?";
    modal.classList.remove("modal--hidden");

    function cleanup(result) {
      modal.classList.add("modal--hidden");
      btnOk.removeEventListener("click", onOk);
      btnCancel.removeEventListener("click", onCancel);
      resolve(result);
    }

    function onOk(e) {
      e.preventDefault();
      cleanup(true);
    }

    function onCancel(e) {
      e.preventDefault();
      cleanup(false);
    }

    btnOk.addEventListener("click", onOk);
    btnCancel.addEventListener("click", onCancel);
  });
}

// --- REVIEW (Tua logica originale) ---
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
        } catch (err) {
          console.error("Errore delete:", err);
        }
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

        const newSong = {
          id: null,
          title: "",
          composer: "",
          artist: "",
          album: "",
          type: "",
          isrc: null,
          upc: null,
          ms: 0,
          confirmed: false,
          timestamp: null,
          manual: true
        };

        songs.splice(insertPos, 0, newSong);
        renderReview();
      });
    }

    container.appendChild(node);
  });

  function updateGenerateState() {
    const total = songs.length;
    // const confirmedCount = songs.filter((s) => s.confirmed).length;
    // const ok = total > 0 && confirmedCount === total;
    const ok = total > 0; // Abilitiamo sempre, ma diamo warning se non confermati
    btnGenerate.disabled = !ok;
  }

  updateGenerateState();
  updateUndoButton();
  syncReviewNotes();
}

// --- WELCOME / MODALITÀ + CAMPI ARTISTA (Tua logica + SaveState) ---
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

function updateConcertArtistVisibility() {
  syncWelcomeModeRadios();
}

function backToWelcome() {
  setRoute("welcome");
  showView("#view-welcome");
  syncWelcomeModeRadios();
}

function initWelcome() {
  const modeCards = document.querySelectorAll(".mode-card");
  const concertCard = document.querySelector(".mode-card-concerto");

  const artistWrapper = document.getElementById("artistInputWrapper");
  const artistInput = document.getElementById("artistInput");
  const artistConfirmBtn = document.getElementById("artistConfirmBtn");
  const artistError = document.getElementById("artistError");

  const bandWrapper = document.getElementById("bandArtistWrapper");
  const bandInput = document.getElementById("bandArtistInput");
  const bandConfirmBtn = document.getElementById("bandConfirmBtn");

  const djWrapper = document.getElementById("djConfirmWrapper");
  const djConfirmBtn = document.getElementById("djConfirmBtn");

  state.mode = null;
  applyTheme();
  syncWelcomeModeRadios();

  function goToSession() {
    hydrateSessionHeader();
    setRoute("session");
    showView("#view-session");
  }

  function handleModeSelection(mode) {
    if (mode === "concert") {
      state.mode = "concert";
      applyTheme();
      if (concertCard) concertCard.classList.add("active");
      if (artistError) artistError.textContent = "";
      syncWelcomeModeRadios();
      if (artistInput) setTimeout(() => artistInput.focus(), 10);
      return;
    }

    if (mode === "band") {
      state.mode = "band";
      applyTheme();
      syncWelcomeModeRadios();
      if (bandInput) setTimeout(() => bandInput.focus(), 10);
      return;
    }

    if (mode === "dj") {
      state.mode = "dj";
      state.concertArtist = "";
      state.bandArtist = "";
      applyTheme();
      syncWelcomeModeRadios();
      return;
    }
  }

  function handleConcertSubmit() {
    if (!artistInput) return;

    const name = artistInput.value.trim();
    if (!name) {
      if (artistError) artistError.textContent = "Inserisci il nome dell’artista prima di continuare.";
      return;
    }

    if (artistError) artistError.textContent = "";

    state.mode = "concert";
    state.concertArtist = name;

    saveStateToLocal();

    applyTheme();
    goToSession();
  }

  function handleBandSubmit() {
    const name = bandInput ? bandInput.value.trim() : "";
    state.mode = "band";
    state.bandArtist = name;

    saveStateToLocal();

    applyTheme();
    goToSession();
  }

  function handleDjSubmit() {
    state.mode = "dj";
    state.concertArtist = "";
    state.bandArtist = "";

    saveStateToLocal();

    applyTheme();
    goToSession();
  }

  modeCards.forEach((card) => {
    card.addEventListener("click", () => {
      const mode = card.dataset.mode;
      handleModeSelection(mode);
    });

    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        const mode = card.dataset.mode;
        handleModeSelection(mode);
      }
    });
  });

  if (artistWrapper) artistWrapper.addEventListener("click", (e) => e.stopPropagation());
  if (bandWrapper) bandWrapper.addEventListener("click", (e) => e.stopPropagation());
  if (djWrapper) djWrapper.addEventListener("click", (e) => e.stopPropagation());

  if (artistConfirmBtn) {
    artistConfirmBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      handleConcertSubmit();
    });
  }

  if (artistInput) {
    artistInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleConcertSubmit();
      }
      e.stopPropagation();
    });
  }

  if (bandConfirmBtn) {
    bandConfirmBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      handleBandSubmit();
    });
  }

  if (bandInput) {
    bandInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleBandSubmit();
      }
      e.stopPropagation();
    });
  }

  if (djConfirmBtn) {
    djConfirmBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      handleDjSubmit();
    });
  }
}

// --- WIRING BOTTONI SESSIONE / REVIEW ---
function wireSessionButtons() {
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  const btnReset = $("#btn-session-reset");

  const btnShowQr = document.getElementById("btn-show-qr");
  const qrModal = document.getElementById("qr-modal");
  const qrImage = document.getElementById("qr-image");
  const qrClose = document.getElementById("qr-close");

  if (btnShowQr) {
    btnShowQr.addEventListener("click", () => {
      qrImage.src = "/api/get_qr_image?t=" + Date.now();
      qrModal.classList.remove("modal--hidden");
    });
  }

  if (qrClose) {
    qrClose.addEventListener("click", () => {
      qrModal.classList.add("modal--hidden");
    });
  }

  if (qrModal) {
    const backdrop = qrModal.querySelector(".modal-backdrop");
    if (backdrop) backdrop.addEventListener("click", () => qrModal.classList.add("modal--hidden"));
  }

  if (btnStart) {
    btnStart.addEventListener("click", (e) => {
      e.preventDefault();
      sessionStart();
    });
  }

  if (btnPause) {
    btnPause.addEventListener("click", (e) => {
      e.preventDefault();
      sessionPause();
    });
  }

  if (btnStop) {
    btnStop.addEventListener("click", async (e) => {
      e.preventDefault();
      const ok = await showConfirm("Vuoi fermare la sessione e passare alla review?");
      if (!ok) return;
      sessionStop();
    });
  }

  if (btnReset) {
    btnReset.addEventListener("click", async (e) => {
      e.preventDefault();
      const msg = "Vuoi resettare la sessione e cancellare il log corrente?";
      showConfirm(msg).then((ok) => {
        if (!ok) return;
        sessionReset();
      });
    });
  }

  // --- GESTIONE EXPORT (Nuova logica completa) ---
  const btnGenerate = $("#btn-generate");
  const exportModal = $("#export-modal");
  const btnExportExcel = $("#btn-export-excel");
  const btnExportPdf = $("#btn-export-pdf");
  const btnExportRaw = $("#btn-export-raw");
  const btnExportClose = $("#btn-export-close");

  async function downloadReport(format) {
    // 1. Controllo Brani non confermati (solo per formati ufficiali)
    if (format !== "pdf_raw") {
      const unconfirmed = songs.filter((s) => !s.confirmed).length;
      if (unconfirmed > 0) {
        const proceed = await showConfirm(
          `Hai ${unconfirmed} brani non confermati. Nel report ufficiale verranno esclusi. Continuare?`
        );
        if (!proceed) return;
      }
    }

    // 2. Prepara Dati
    let exportArtist = "Various";
    if (state.mode === "concert") exportArtist = state.concertArtist;
    if (state.mode === "band") exportArtist = state.bandArtist;
    if (state.mode === "dj") exportArtist = "DJ_Set";

    // Chiudi modale e metti loading
    exportModal.classList.add("modal--hidden");
    const originalText = btnGenerate.textContent;
    btnGenerate.textContent = "Downloading...";
    btnGenerate.disabled = true;

    try {
      const res = await fetch("/api/generate_report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ songs: songs, mode: state.mode, artist: exportArtist, format: format })
      });

      if (!res.ok) throw new Error("Errore server");

      // Download
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.style.display = "none";
      a.href = url;

      // Nome file da header o fallback
      const contentDisp = res.headers.get("Content-Disposition");
      let fileName = `report.${format === "excel" ? "xlsx" : "pdf"}`;
      if (contentDisp && contentDisp.includes("filename=")) {
        fileName = contentDisp.split("filename=")[1].replace(/"/g, "");
      }

      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      alert("Errore durante il download del report.");
    } finally {
      btnGenerate.textContent = originalText;
      btnGenerate.disabled = false;
    }
  }

  // Apertura Modal
  if (btnGenerate) {
    btnGenerate.addEventListener("click", (e) => {
      e.preventDefault();
      // Mostra il modal solo se ci sono canzoni (opzionale)
      if (songs.length === 0) {
        alert("Nessun brano in lista.");
        return;
      }
      exportModal.classList.remove("modal--hidden");
    });
  }

  // Click Opzioni Modal
  if (btnExportExcel) btnExportExcel.onclick = () => downloadReport("excel");
  if (btnExportPdf) btnExportPdf.onclick = () => downloadReport("pdf_official");
  if (btnExportRaw) btnExportRaw.onclick = () => downloadReport("pdf_raw");

  // Chiusura Modal
  if (btnExportClose) btnExportClose.onclick = () => exportModal.classList.add("modal--hidden");

  // Chiusura clickando fuori
  if (exportModal) {
    const backdrop = exportModal.querySelector(".modal-backdrop");
    if (backdrop) backdrop.onclick = () => exportModal.classList.add("modal--hidden");
  }

  const btnUndo = $("#btn-undo");
  if (btnUndo) {
    btnUndo.addEventListener("click", (e) => {
      e.preventDefault();
      undoLast();
    });
  }

  const btnBackSession = $("#btn-back-session");
  if (btnBackSession) {
    btnBackSession.addEventListener("click", (e) => {
      e.preventDefault();
      backToSessionFromReview();
    });
  }

  const btnBackWelcome = $("#btn-back-welcome");
  if (btnBackWelcome) {
    btnBackWelcome.addEventListener("click", (e) => {
      e.preventDefault();
      backToWelcome();
    });
  }

  const btnNotes = $("#btn-session-notes");
  if (btnNotes) {
    btnNotes.addEventListener("click", (e) => {
      e.preventDefault();
      openNotesModal("session");
    });
  }

  const btnReviewNotes = $("#btn-review-notes");
  if (btnReviewNotes) {
    btnReviewNotes.addEventListener("click", (e) => {
      e.preventDefault();
      openNotesModal("review");
    });
  }

  const notesCancel = $("#notes-cancel");
  const notesSave = $("#notes-save");

  if (notesCancel) {
    notesCancel.addEventListener("click", (e) => {
      e.preventDefault();
      closeNotesModal(false);
    });
  }

  if (notesSave) {
    notesSave.addEventListener("click", (e) => {
      e.preventDefault();
      closeNotesModal(true);
    });
  }
}

// --- LOGICA RIPRISTINO SESSIONE ALL'AVVIO (Dal Collega) ---
async function checkRestoreSession() {
  try {
    const res = await fetch("/api/get_playlist");
    if (!res.ok) return;

    const data = await res.json();
    const playlist = Array.isArray(data.playlist) ? data.playlist : [];

    if (playlist.length === 0) return;

    const modal = document.getElementById("restore-modal");
    const btnNew = document.getElementById("restore-new");
    const btnRecover = document.getElementById("restore-ok");

    if (!modal || !btnNew || !btnRecover) return;

    modal.classList.remove("modal--hidden");

    btnNew.onclick = async () => {
      await fetch("/api/reset_session", { method: "POST" });
      localStorage.removeItem("appMode");
      localStorage.removeItem("concertArtist");
      localStorage.removeItem("bandArtist");

      modal.classList.add("modal--hidden");
      songs = [];
      console.log("Database pulito.");
    };

    btnRecover.onclick = () => {
      modal.classList.add("modal--hidden");
      console.log("Sessione recuperata.");

      const savedMode = localStorage.getItem("appMode");

      if (savedMode) {
        state.mode = savedMode;
        state.concertArtist = localStorage.getItem("concertArtist") || "";
        state.bandArtist = localStorage.getItem("bandArtist") || "";
        sessionStart();
      } else {
        alert("Dati recuperati! Seleziona la modalità (DJ/Band) per visualizzarli.");
      }
    };
  } catch (err) {
    console.error("Errore checkRestoreSession:", err);
  }
}

// --- AVVIO ---
document.addEventListener("DOMContentLoaded", () => {
  const app = document.getElementById("app");
  const isViewer = app.dataset.viewer === "true";

  wireSessionButtons();
  buildVisualizer();

  if (isViewer) {
    console.log("Modalità Viewer attiva: salto diretto alla sessione.");

    state.route = "session";
    showView("#view-session");
    hydrateSessionHeader();

    startPlaylistPolling();
    startVisualizer();

    const restoreModal = document.getElementById("restore-modal");
    if (restoreModal) restoreModal.classList.add("modal--hidden");
  } else {
    setRoute("welcome");
    showView("#view-welcome");
    initWelcome();
    checkRestoreSession();
    syncReviewNotes();
  }
});

function updateBackground(url) {
    const bgEl = document.getElementById("app-background");
    if (!bgEl) return;

    if (url) {
        // Precarica l'immagine per evitare scatti
        const img = new Image();
        img.src = url;
        img.onload = () => {
            bgEl.style.backgroundImage = `url('${url}')`;
            bgEl.style.opacity = "1";
        };
    } else {
        bgEl.style.opacity = "0"; // Nascondi se non c'è cover
    }
}

// --- ARTIST DASHBOARD LOGIC (CORRETTA) ---

// --- ARTIST DASHBOARD LOGIC (CON ANIMAZIONI) ---

// --- ARTIST DASHBOARD LOGIC (CORRETTA PER SCROLL) ---

function openArtistDashboard() {
  console.log("Apertura Dashboard Artista...");

  // 1. Reset Viste
  document.querySelectorAll('.view').forEach(el => {
    el.classList.remove('view--active');
    el.classList.add('hidden');
  });
  
  // 2. Attiva Dashboard
  const dash = document.getElementById('view-artist-dashboard');
  
  if(dash) {
    // SBLOCCA LO SCROLL DEL BODY (Fondamentale!)
    document.body.classList.remove('no-scroll');

    dash.classList.remove('hidden');
    
    // Timeout per animazioni
    setTimeout(() => {
        dash.classList.add('view--active');
        // Se hai aggiunto la funzione delle animazioni (triggerDashboardAnimations), chiamala qui:
        if (typeof triggerDashboardAnimations === "function") {
            triggerDashboardAnimations();
        }
    }, 10);
    
    updateBackground(""); 
  }
}

function closeArtistDashboard() {
  // 1. Nascondi Dashboard
  const dash = document.getElementById('view-artist-dashboard');
  if(dash) {
    dash.classList.remove('view--active');
    dash.classList.add('hidden');
  }
  
  // 2. Torna alla Welcome Screen
  const welcome = document.getElementById('view-welcome');
  if(welcome) {
    welcome.classList.remove('hidden');
    welcome.classList.add('view--active'); 
    
    // BLOCCA DI NUOVO LO SCROLL (Per la schermata Welcome che è fissa)
    document.body.classList.add('no-scroll');
  }
  
  // 3. Ripristina lo stato dei radio button
  if (typeof syncWelcomeModeRadios === "function") {
    syncWelcomeModeRadios();
  }
}

function triggerDashboardAnimations() {
  // A) Animazione Numeri (KPI)
  const counters = document.querySelectorAll('.animate-num');
  
  counters.forEach(counter => {
    const target = parseFloat(counter.getAttribute('data-target'));
    const prefix = counter.getAttribute('data-prefix') || "";
    const suffix = counter.getAttribute('data-suffix') || "";
    const decimals = parseInt(counter.getAttribute('data-decimals') || "0");
    
    // Reset iniziale
    counter.innerText = prefix + "0" + suffix;

    const duration = 1500; // Durata animazione in ms
    const startTime = performance.now();

    function updateCount(currentTime) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      
      // Easing (effetto rallentamento finale)
      const easeOutQuart = 1 - Math.pow(1 - progress, 4);
      
      const currentVal = (target * easeOutQuart).toFixed(decimals);
      
      counter.innerText = prefix + currentVal + suffix;

      if (progress < 1) {
        requestAnimationFrame(updateCount);
      } else {
        counter.innerText = prefix + target + suffix; // Assicura valore finale pulito
      }
    }

    requestAnimationFrame(updateCount);
  });

  // B) Animazione Barre Grafico (Top Cities)
  const bars = document.querySelectorAll('.progress-bar .fill');
  bars.forEach(bar => {
      // Reset larghezza a 0
      bar.style.width = "0%";
      bar.style.transition = "width 1.5s cubic-bezier(0.16, 1, 0.3, 1)"; // Transizione fluida CSS
      
      // Legge il valore target (es. 24%)
      const targetWidth = bar.getAttribute('data-width');
      
      // Applica dopo un attimo per far partire la transizione
      setTimeout(() => {
          bar.style.width = targetWidth;
      }, 300);
  });
  
}

// --- LOGIN MENU LOGIC ---

document.addEventListener("DOMContentLoaded", () => {
    // Gestione Toggle Menu
    const loginBtn = document.getElementById("loginToggleBtn");
    const loginMenu = document.getElementById("loginMenu");
    
    if(loginBtn && loginMenu) {
        loginBtn.addEventListener("click", (e) => {
            e.stopPropagation(); // Evita che il click si propaghi al document
            toggleLoginMenu();
        });
        
        // Chiudi menu se clicco ovunque altro nella pagina
        document.addEventListener("click", (e) => {
            if (!loginMenu.contains(e.target) && !loginBtn.contains(e.target)) {
                loginMenu.classList.remove("show");
                loginBtn.classList.remove("active");
            }
        });
    }
});

function toggleLoginMenu() {
    const menu = document.getElementById("loginMenu");
    const btn = document.getElementById("loginToggleBtn");
    
    if (menu.classList.contains("show")) {
        menu.classList.remove("show");
        btn.classList.remove("active");
    } else {
        menu.classList.remove("hidden"); // Assicuriamoci che non sia hidden
        // Piccolo timeout per permettere la transizione CSS
        setTimeout(() => menu.classList.add("show"), 10);
        btn.classList.add("active");
    }
}

// Funzione Placeholder per l'Interfaccia Utente
// --- USER DASHBOARD LOGIC ---

function openUserDashboard() {
    // 1. Chiudi menu a tendina
    const menu = document.getElementById("loginMenu");
    const btn = document.getElementById("loginToggleBtn");
    if(menu) menu.classList.remove("show");
    if(btn) btn.classList.remove("active");
    
    console.log("Apertura Dashboard Utente...");

    // 2. Reset Viste
    document.querySelectorAll('.view').forEach(el => {
        el.classList.remove('view--active');
        el.classList.add('hidden');
    });

    // 3. Mostra Dashboard Utente
    const dash = document.getElementById('view-user-dashboard');
    if(dash) {
        document.body.classList.remove('no-scroll'); // Sblocca scroll
        dash.classList.remove('hidden');
        
        setTimeout(() => {
            dash.classList.add('view--active');
            // Riutilizziamo le animazioni create per l'artista (funzionano su classi .animate-num e .progress-bar)
            if (typeof triggerDashboardAnimations === "function") {
                triggerDashboardAnimations();
            }
        }, 10);
        
        updateBackground(""); // Sfondo pulito
    }
}

function closeUserDashboard() {
    // 1. Nascondi Dashboard Utente
    const dash = document.getElementById('view-user-dashboard');
    if(dash) {
        dash.classList.remove('view--active');
        dash.classList.add('hidden');
    }
    
    // 2. Torna alla Welcome Screen
    const welcome = document.getElementById('view-welcome');
    if(welcome) {
        welcome.classList.remove('hidden');
        welcome.classList.add('view--active');
        document.body.classList.add('no-scroll'); // Blocca scroll home
    }
    
    if (typeof syncWelcomeModeRadios === "function") syncWelcomeModeRadios();
}

// Modifica openArtistDashboard per chiudere il menu quando viene chiamata
const originalOpenArtist = openArtistDashboard; // Salviamo la vecchia ref se serve
openArtistDashboard = function() {
    // Chiudi il menu prima di aprire la dashboard
    const menu = document.getElementById("loginMenu");
    if(menu) menu.classList.remove("show");
    
    // Chiama la tua funzione originale (quella che abbiamo scritto prima con le animazioni)
    // Nota: Ho riscritto la funzione intera sotto per sicurezza, usiamo quella.
    
    console.log("Apertura Dashboard Artista...");
    
    // Reset Viste
    document.querySelectorAll('.view').forEach(el => {
        el.classList.remove('view--active');
        el.classList.add('hidden');
    });

    const dash = document.getElementById('view-artist-dashboard');
    if(dash) {
        document.body.classList.remove('no-scroll');
        dash.classList.remove('hidden');
        setTimeout(() => {
            dash.classList.add('view--active');
            if (typeof triggerDashboardAnimations === "function") triggerDashboardAnimations();
        }, 10);
        updateBackground(""); 
    }
};