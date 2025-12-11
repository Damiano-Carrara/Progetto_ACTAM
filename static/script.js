// --- STATO APP ---
const state = {
  mode: null,          // "dj" | "band" | "concert"
  route: "welcome",    // "welcome" | "session" | "review"
  concertArtist: "",
  bandArtist: "",      // artista opzionale per live band
  notes: ""            // note su mismatch/errori dalla sessione
};

// playlist locale (frontend)
let songs = []; 

// id massimo visto (per polling efficiente)
let lastMaxSongId = 0;

// brano attualmente mostrato come "Now playing"
let currentSongId = null;

// polling timer
let playlistPollInterval = null;

// timer sessione
let sessionStartMs = 0;
let sessionAccumulatedMs = 0;
let sessionTick = null;

// undo stack
let undoStack = [];

// visualizer
const VIS_COLS = 96;
const VIS_ROWS = 16;
let visTick = null;
let visLevels = new Array(VIS_COLS).fill(0);

// contesto attuale modal note
let notesModalContext = "session";

/** selettore rapido */
const $ = (sel) => document.querySelector(sel);

// --- UTILS ---
function pad2(n) { return n.toString().padStart(2, "0"); }

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

// --- SALVATAGGIO STATO LOCALE (Per il Restore) ---
function saveStateToLocal() {
  if (!state.mode) return;
  localStorage.setItem("appMode", state.mode);
  if (state.concertArtist) {
    localStorage.setItem("concertArtist", state.concertArtist);
  } else {
    localStorage.removeItem("concertArtist");
  }
  if (state.bandArtist) {
    localStorage.setItem("bandArtist", state.bandArtist);
  } else {
    localStorage.removeItem("bandArtist");
  }
}

// --- THEME ---
function applyTheme() {
  const app = document.getElementById("app");
  if (!app) return;
  app.classList.remove("theme-dj", "theme-band", "theme-concert");
  if (state.mode === "band") app.classList.add("theme-band");
  else if (state.mode === "concert") app.classList.add("theme-concert");
  else if (state.mode === "dj") app.classList.add("theme-dj");
}

// --- NAVIGAZIONE ---
function setRoute(route) {
  state.route = route;
  const body = document.body;
  if (body) {
    if (route === "welcome" || route === "session") {
      body.classList.add("no-scroll");
    } else {
      body.classList.remove("no-scroll");
    }
  }
}

function showView(id) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("view--active"));
  const el = document.querySelector(id);
  if (el) el.classList.add("view--active");
}

// --- VISUALIZER ---
function buildVisualizer() {
  const container = $("#visualizer");
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
    const speedUp = 0.45; const speedDown = 0.12;
    if (target > current) current += (target - current) * speedUp;
    else current += (target - current) * speedDown;
    current *= 0.985;
    if (current < 0) current = 0;
    if (current > VIS_ROWS) current = VIS_ROWS;
    visLevels[colIndex] = current;
    const cells = cols[colIndex].children;
    const levelRounded = Math.round(current);
    for (let i = 0; i < VIS_ROWS; i++) {
      cells[i].classList.toggle("active", i < levelRounded);
    }
  }
}

function startVisualizer() {
  if (visTick) return;
  visLevels = new Array(VIS_COLS).fill(0);
  visTick = setInterval(updateVisualizer, 80);
}

function stopVisualizer() {
  if (visTick) clearInterval(visTick);
  visTick = null;
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

// --- LOG LIVE ---
function setNow(title, composer) {
  const titleEl = $("#now-title");
  const compEl = $("#now-composer");
  if (titleEl) titleEl.textContent = title || "In ascolto";
  if (compEl) compEl.textContent = composer || "—";
}

function pushLog({ id, index, title, composer, artist }) {
  const row = document.createElement("div");
  row.className = "log-row";
  if (id != null) row.dataset.id = id;

  row.innerHTML = `
    <span class="col-index">${index != null ? index : "—"}</span>
    <span>${title || "—"}</span>
    <span class="col-composer">${composer || "—"}</span>
    <span class="col-artist">${artist || "—"}</span>
  `;
  $("#live-log").prepend(row);
}

// --- TIMER ---
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

// --- BACKEND API ---
async function startBackendRecognition() {
  const body = {};
  if (state.mode === "concert" && state.concertArtist) body.targetArtist = state.concertArtist;
  else if (state.mode === "band" && state.bandArtist) body.targetArtist = state.bandArtist;

  try {
    await fetch("/api/start_recognition", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
  } catch (err) { console.error("Err start_recognition:", err); }
}

async function stopBackendRecognition() {
  try {
    await fetch("/api/stop_recognition", { method: "POST", headers: { "Content-Type": "application/json" } });
  } catch (err) { console.error("Err stop_recognition:", err); }
}

// --- POLLING PLAYLIST ---
async function pollPlaylistOnce() {
  try {
    const res = await fetch("/api/get_playlist");
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
            timestamp: song.timestamp || null
          };
          songs.push(track);
          currentSongId = track.id;
          setNow(track.title, track.composer);
          pushLog({ id: track.id, index: track.order, title: track.title, composer: track.composer, artist: track.artist });
        }
      } else {
        const oldComposer = existing.composer;
        const oldArtist = existing.artist;
        
        existing.title = song.title || existing.title;
        existing.composer = song.composer || existing.composer;
        existing.artist = song.artist || existing.artist;
        
        if (existing.composer !== oldComposer || existing.artist !== oldArtist) {
          updatedExisting = true;
          if (currentSongId === id) setNow(existing.title, existing.composer);
          
          const logRow = document.querySelector(`.log-row[data-id="${id}"]`);
          if (logRow) {
            const cSpan = logRow.querySelector(".col-composer");
            if (cSpan) cSpan.textContent = existing.composer;
            const aSpan = logRow.querySelector(".col-artist");
            if (aSpan) aSpan.textContent = existing.artist || "—";
          }
        }
      }
      if (id > maxIdSeen) maxIdSeen = id;
    });

    lastMaxSongId = maxIdSeen;
    if (updatedExisting && state.route === "review") renderReview();

  } catch (err) { console.error("Err polling:", err); }
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
  if(btnStart) btnStart.disabled = true;
  if(btnPause) btnPause.disabled = false;
  if(btnStop) btnStop.disabled = false;

  if (!sessionTick) startSessionTimer();
  await startBackendRecognition();
  startPlaylistPolling();
  startVisualizer();
}

async function sessionPause() {
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  if(btnStart) btnStart.disabled = false;
  if(btnPause) btnPause.disabled = true;

  pauseSessionTimer();
  await stopBackendRecognition();
  stopPlaylistPolling();
  stopVisualizer(); // Risparmia CPU
}

async function sessionStop() {
  pauseSessionTimer();
  await stopBackendRecognition();
  stopPlaylistPolling();
  await pollPlaylistOnce(); // Sync finale
  
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
  await stopBackendRecognition();
  stopPlaylistPolling();
  pauseSessionTimer();
  resetSessionTimer();

  // CHIAMATA AL BACKEND PER SVUOTARE IL DB
  try {
    await fetch("/api/reset_session", { method: "POST" });
  } catch (err) { console.error("Err reset backend:", err); }

  // Pulisce anche la memoria locale
  localStorage.removeItem("appMode");
  localStorage.removeItem("concertArtist");
  localStorage.removeItem("bandArtist");

  currentSongId = null;
  setNow("In ascolto", "—");
  songs = [];
  undoStack = [];
  lastMaxSongId = 0;
  
  $("#live-log").innerHTML = "";

  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  if(btnStart) btnStart.disabled = false;
  if(btnPause) btnPause.disabled = true;
  if(btnStop) btnStop.disabled = true;

  stopVisualizer();
}

// --- NOTE ---
function syncReviewNotes() {
  const view = $("#review-notes-view");
  if (view) view.textContent = (state.notes || "").trim() || "—";
}

function openNotesModal(context = "session") {
  const modal = $("#notes-modal");
  const textarea = $("#notes-textarea");
  if (!modal || !textarea) return;
  notesModalContext = context;
  textarea.value = state.notes || "";
  modal.classList.remove("modal--hidden");
}

function closeNotesModal(save) {
  const modal = $("#notes-modal");
  const textarea = $("#notes-textarea");
  if (save && notesModalContext !== "review") {
    state.notes = textarea.value || "";
    syncReviewNotes();
  }
  modal.classList.add("modal--hidden");
}

// --- REVIEW ---
function renderReview() {
  const container = $("#review-rows");
  const template = $("#review-row-template");
  const btnGenerate = $("#btn-generate");
  if (!container || !template || !btnGenerate) return;

  container.innerHTML = "";

  songs.forEach((song, index) => {
    const node = template.content.firstElementChild.cloneNode(true);
    
    node.querySelector(".review-index").textContent = index + 1;
    const inputComposer = node.querySelector('[data-field="composer"]');
    const inputTitle = node.querySelector('[data-field="title"]');
    
    inputComposer.value = song.composer || "";
    inputTitle.value = song.title || "";
    inputComposer.readOnly = true;
    inputTitle.readOnly = true;

    if (song.confirmed) node.classList.add("row--confirmed");

    // EVENTI
    node.querySelector(".btn-edit").addEventListener("click", () => {
      inputComposer.readOnly = false;
      inputTitle.readOnly = false;
      song.confirmed = false;
      node.classList.remove("row--confirmed");
      updateGenerateState();
    });

    node.querySelector(".btn-confirm").addEventListener("click", () => {
      song.composer = inputComposer.value || "";
      song.title = inputTitle.value || "";
      song.confirmed = true;
      inputComposer.readOnly = true;
      inputTitle.readOnly = true;
      node.classList.add("row--confirmed");
      updateGenerateState();
    });

    node.querySelector(".btn-delete").addEventListener("click", async () => {
      if(await showConfirm("Cancellare questo brano?")) {
        if(song.id != null) {
            await fetch("/api/delete_song", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: song.id }) });
        }
        songs.splice(songs.indexOf(song), 1);
        renderReview();
      }
    });

    if(node.querySelector(".btn-add")) {
        node.querySelector(".btn-add").addEventListener("click", () => {
            const insertPos = songs.indexOf(song) + 1;
            songs.splice(insertPos, 0, { id: null, title: "", composer: "", artist: "", confirmed: false, manual: true });
            renderReview();
        });
    }

    container.appendChild(node);
  });

  function updateGenerateState() {
    const total = songs.length;
    const confirmed = songs.filter(s => s.confirmed).length;
    btnGenerate.disabled = !(total > 0 && confirmed === total);
  }
  updateGenerateState();
}

// --- CONFIRM MODAL ---
function showConfirm(message) {
  return new Promise((resolve) => {
    const modal = $("#confirm-modal");
    const msgEl = $("#confirm-message");
    const btnOk = $("#confirm-ok");
    const btnCancel = $("#confirm-cancel");
    
    msgEl.textContent = message || "Confermi?";
    modal.classList.remove("modal--hidden");

    const cleanup = (res) => {
      modal.classList.add("modal--hidden");
      btnOk.onclick = null;
      btnCancel.onclick = null;
      resolve(res);
    };
    btnOk.onclick = () => cleanup(true);
    btnCancel.onclick = () => cleanup(false);
  });
}

// --- WELCOME LOGIC ---
function initWelcome() {
  const cards = document.querySelectorAll(".mode-card");
  
  const handleMode = (mode) => {
    state.mode = mode;
    saveStateToLocal();
    applyTheme();
    
    // Aggiorna UI
    document.querySelectorAll(".artist-input-wrapper").forEach(el => el.classList.remove("visible"));
    cards.forEach(c => c.classList.remove("mode-card--selected", "active"));
    
    const selectedCard = document.querySelector(`.mode-card[data-mode="${mode}"]`);
    if(selectedCard) selectedCard.classList.add("mode-card--selected", "active");

    if (mode === "dj") {
        $("#djConfirmWrapper").classList.add("visible");
    } else if (mode === "band") {
        $("#bandArtistWrapper").classList.add("visible");
        const inp = $("#bandArtistInput");
        if(inp) { inp.value = state.bandArtist || ""; setTimeout(() => inp.focus(), 10); }
    } else if (mode === "concert") {
        $("#artistInputWrapper").classList.add("visible");
        const inp = $("#artistInput");
        if(inp) { inp.value = state.concertArtist || ""; setTimeout(() => inp.focus(), 10); }
    }
  };

  cards.forEach(card => card.addEventListener("click", () => handleMode(card.dataset.mode)));

  // Submit Handlers
  $("#djConfirmBtn").onclick = (e) => { e.stopPropagation(); setRoute("session"); showView("#view-session"); hydrateSessionHeader(); };
  
  $("#bandConfirmBtn").onclick = (e) => { 
      e.stopPropagation(); 
      state.bandArtist = $("#bandArtistInput").value.trim();
      saveStateToLocal();
      setRoute("session"); showView("#view-session"); hydrateSessionHeader();
  };
  
  $("#artistConfirmBtn").onclick = (e) => { 
      e.stopPropagation(); 
      const val = $("#artistInput").value.trim();
      if(!val) return alert("Inserisci nome artista");
      state.concertArtist = val;
      saveStateToLocal();
      setRoute("session"); showView("#view-session"); hydrateSessionHeader();
  };
}

// --- WIRING ---
function wireButtons() {
    // Session Buttons
    $("#btn-session-start")?.addEventListener("click", sessionStart);
    $("#btn-session-pause")?.addEventListener("click", sessionPause);
    $("#btn-session-stop")?.addEventListener("click", async () => { if(await showConfirm("Fermare sessione?")) sessionStop(); });
    $("#btn-session-reset")?.addEventListener("click", async () => { if(await showConfirm("Resettare tutto?")) sessionReset(); });

    // QR Logic
    const qrModal = $("#qr-modal");
    $("#btn-show-qr")?.addEventListener("click", () => {
        $("#qr-image").src = "/api/get_qr_image?t=" + Date.now();
        qrModal.classList.remove("modal--hidden");
    });
    $("#qr-close")?.addEventListener("click", () => qrModal.classList.add("modal--hidden"));

    // Notes
    $("#btn-session-notes")?.addEventListener("click", () => openNotesModal("session"));
    $("#btn-review-notes")?.addEventListener("click", () => openNotesModal("review"));
    $("#notes-save")?.addEventListener("click", () => closeNotesModal(true));
    $("#notes-cancel")?.addEventListener("click", () => closeNotesModal(false));
}

// --- RESTORE LOGIC ---
async function checkRestoreSession() {
    try {
        const res = await fetch("/api/get_playlist");
        if (!res.ok) return;
        const data = await res.json();
        if ((data.playlist || []).length === 0) return;

        const modal = $("#restore-modal");
        modal.classList.remove("modal--hidden");

        $("#restore-new").onclick = async () => {
            await fetch("/api/reset_session", { method: "POST" });
            localStorage.clear();
            modal.classList.add("modal--hidden");
        };

        $("#restore-ok").onclick = () => {
            modal.classList.add("modal--hidden");
            const savedMode = localStorage.getItem("appMode");
            if(savedMode) {
                state.mode = savedMode;
                state.concertArtist = localStorage.getItem("concertArtist") || "";
                state.bandArtist = localStorage.getItem("bandArtist") || "";
                sessionStart();
            } else {
                alert("Dati recuperati. Seleziona la modalità.");
            }
        };
    } catch (e) { console.error(e); }
}

// --- BOOTSTRAP ---
document.addEventListener("DOMContentLoaded", () => {
    const isViewer = document.getElementById("app").dataset.viewer === "true";
    
    wireButtons();
    buildVisualizer();

    if (isViewer) {
        console.log("Viewer Mode");
        setRoute("session");
        showView("#view-session");
        startPlaylistPolling();
        startVisualizer();
        $("#restore-modal")?.classList.add("hidden"); // Nascondi restore su mobile
    } else {
        setRoute("welcome");
        showView("#view-welcome");
        initWelcome();
        checkRestoreSession();
    }
});