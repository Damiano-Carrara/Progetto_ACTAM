// --- STATO APP ---
const state = {
  mode: "dj", // "dj" | "band" | "concert"
  route: "welcome", // "welcome" | "session" | "review"
  concertArtist: "",
};

// playlist locale (frontend)
let songs = [];

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

// stato dell'onda (idle = piatta, playing = viva, paused = si spegne lentamente)
let waveMode = "idle"; // "idle" | "playing" | "paused"

// --- UTILS ---
const $ = (sel) => document.querySelector(sel);

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

// --- NAVIGAZIONE / STATO MODALITÀ ---
function setMode(mode) {
  if (mode === "dj" || mode === "band" || mode === "concert") {
    state.mode = mode;
    if (mode !== "concert") {
      state.concertArtist = "";
    }
  } else {
    state.mode = "dj";
    state.concertArtist = "";
  }
}

function setRoute(route) {
  state.route = route;
}

function showView(id) {
  document
    .querySelectorAll(".view")
    .forEach((v) => v.classList.remove("view--active"));
  const el = document.querySelector(id);
  if (el) el.classList.add("view--active");
}

// === VISUALIZER A QUADRATINI ===
const VIS_COLS = 48;
const VIS_ROWS = 16;
let visTick = null;

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
  cols.forEach((col) => {
    const cells = col.children;
    const level = Math.floor(Math.random() * (VIS_ROWS + 1)); // altezza random

    for (let i = 0; i < cells.length; i++) {
      cells[i].classList.toggle("active", i < level);
    }
  });
}

function startVisualizer() {
  if (visTick) return;
  visTick = setInterval(updateVisualizer, 120);
}

function stopVisualizer() {
  if (visTick) {
    clearInterval(visTick);
    visTick = null;
  }
  document.querySelectorAll(".vis-cell.active").forEach((cell) => {
    cell.classList.remove("active");
  });
}


// --- SESSION HEADER ---
function hydrateSessionHeader() {
  const badge = $("#mode-badge");
  if (!badge) return;

  if (state.mode === "band") {
    badge.textContent = "Live band";
  } else if (state.mode === "concert") {
    badge.textContent = state.concertArtist
      ? `Concerto – ${state.concertArtist}`
      : "Concerto";
  } else {
    badge.textContent = "DJ set";
  }
}

// --- NOW PLAYING ---
function setNow(title, composer) {
  const titleEl = $("#now-title");
  const compEl = $("#now-composer");

  if (titleEl) {
    titleEl.textContent = title || "In ascolto";
  }
  if (compEl) {
    compEl.textContent = composer || "—";
  }
}


// --- LOG LIVE ---
function pushLog({ when, title, composer, status }) {
  const row = document.createElement("div");
  row.className = "log-row";

  const cls =
    status === "NEW"
      ? "status-new"
      : status === "SAME"
      ? "status-same"
      : "status-ok";

  row.innerHTML = `
    <span>${when}</span>
    <span>${title || "—"}</span>
    <span>${composer || "—"}</span>
    <span class="${cls}">${status}</span>
  `;

  $("#live-log").prepend(row);
}

// --- TIMER SESSIONE ---
function startSessionTimer() {
  if (sessionTick) return;
  sessionStartMs = Date.now();
  sessionTick = setInterval(() => {
    const elapsed = sessionAccumulatedMs + (Date.now() - sessionStartMs);
    $("#session-timer").textContent = fmt(elapsed);
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
  $("#session-timer").textContent = "00:00";
}

// --- UNDO ---
function pushUndoState() {
  const snapshot = songs.map((s) => ({ ...s }));
  undoStack.push(snapshot);
  if (undoStack.length > 5) {
    undoStack.shift();
  }
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

// --- CHIAMATE BACKEND START/STOP RICONOSCIMENTO ---

async function startBackendRecognition() {
  const body = {};
  if (state.mode === "concert" && state.concertArtist) {
    body.targetArtist = state.concertArtist;
  }

  try {
    const res = await fetch("/api/start_recognition", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
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
      body: JSON.stringify({}),
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

// --- POLLING PLAYLIST BACKEND ---

async function pollPlaylistOnce() {
  try {
    const res = await fetch("/api/get_playlist");
    if (!res.ok) {
      console.error("Errore HTTP /api/get_playlist:", res.status);
      return;
    }
    const data = await res.json();
    const playlist = Array.isArray(data.playlist) ? data.playlist : [];

    let maxIdSeen = lastMaxSongId;

    playlist.forEach((song) => {
      const id = Number(song.id);
      if (!Number.isFinite(id)) return;

      if (id > lastMaxSongId) {
        const track = {
          id,
          title: song.title || "Titolo sconosciuto",
          composer: song.composer || "—",
          artist: song.artist || "",
          album: song.album || "",
          type: song.type || "",
          isrc: song.isrc || null,
          upc: song.upc || null,
          ms: song.duration_ms || 0,
          confirmed: false,
        };

        songs.push(track);
        currentSongId = track.id;
        setNow(track.title, track.composer);

        pushLog({
          when: song.timestamp || nowHHMM(),
          title: track.title,
          composer: track.composer,
          status: "NEW",
        });
      }

      if (id > maxIdSeen) maxIdSeen = id;
    });

    lastMaxSongId = maxIdSeen;
  } catch (err) {
    console.error("Errore nel polling playlist:", err);
  }
}

function startPlaylistPolling() {
  if (playlistPollInterval) return;
  // prima chiamata immediata
  pollPlaylistOnce();
  // POCO SPAM: una richiesta ogni 15 secondi
  playlistPollInterval = setInterval(pollPlaylistOnce, 15000);
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

  $("#btn-session-start").disabled = true;
  $("#btn-session-pause").disabled = false;
  $("#btn-session-stop").disabled = false;

  // l'onda parte
  waveMode = "playing";

  if (!sessionTick) {
    startSessionTimer();
  }

  await startBackendRecognition();
  startPlaylistPolling();
  startVisualizer();
}

async function sessionPause() {
  $("#btn-session-start").disabled = false;
  $("#btn-session-pause").disabled = true;
  $("#btn-session-stop").disabled = false;

  waveMode = "paused";

  pauseSessionTimer();
  await stopBackendRecognition();
  stopPlaylistPolling();
  stopVisualizer();
}

// STOP → ferma riconoscimento, sincronizza playlist e va direttamente in review
async function sessionStop() {
  $("#btn-session-start").disabled = false;
  $("#btn-session-pause").disabled = true;
  $("#btn-session-stop").disabled = true;

  waveMode = "idle";

  pauseSessionTimer();
  await stopBackendRecognition();
  stopPlaylistPolling();

  // sync finale con backend
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

// RESET SESSIONE: ferma tutto, pulisce UI e playlist locale
async function sessionReset() {
  waveMode = "idle";

  await stopBackendRecognition();
  stopPlaylistPolling();
  pauseSessionTimer();
  resetSessionTimer();

  currentSongId = null;
  setNow("In ascolto", "—");

  songs = [];
  undoStack = [];
  updateUndoButton();

  const liveLog = $("#live-log");
  if (liveLog) liveLog.innerHTML = "";

  // qui facciamo UNA sola get_playlist per riallineare lastMaxSongId
  try {
    const res = await fetch("/api/get_playlist");
    if (res.ok) {
      const data = await res.json();
      const playlist = Array.isArray(data.playlist) ? data.playlist : [];
      lastMaxSongId = playlist.reduce(
        (acc, s) => (s.id && s.id > acc ? s.id : acc),
        0
      );
    }
  } catch (err) {
    console.error("Errore get_playlist in reset:", err);
  }

  $("#btn-session-start").disabled = false;
  $("#btn-session-pause").disabled = true;
  $("#btn-session-stop").disabled = true;
}

// --- (OPZIONALE) RIPRISTINO SESSIONE DA REVIEW ---
function restoreSessionFromSnapshot() {
  if (!lastSessionSnapshot) return;

  songs = lastSessionSnapshot.songs.map((s) => ({ ...s }));
  const snapshotCurrentId = lastSessionSnapshot.currentSongId ?? null;
  currentSongId = snapshotCurrentId;
  sessionAccumulatedMs = lastSessionSnapshot.sessionAccumulatedMs || 0;
  sessionStartMs = 0;
  sessionTick = null;

  $("#session-timer").textContent = fmt(sessionAccumulatedMs);

  const current =
    currentSongId != null
      ? songs.find((s) => s.id === currentSongId)
      : null;

  if (current) {
    setNow(current.title, current.composer);
  } else {
    setNow("In ascolto", "—");
  }

  $("#btn-session-start").disabled = false;
  $("#btn-session-pause").disabled = true;
  $("#btn-session-stop").disabled = false;
}

function backToSessionFromReview() {
  restoreSessionFromSnapshot();
  setRoute("session");
  showView("#view-session");
}

// --- MODAL DI CONFERMA ---
function showConfirm(message) {
  return new Promise((resolve) => {
    const modal = $("#confirm-modal");
    const msgEl = $("#confirm-message");
    const btnOk = $("#confirm-ok");
    const btnCancel = $("#confirm-cancel");

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

// --- REVIEW ---
function renderReview() {
  const container = $("#review-rows");
  const template = $("#review-row-template");
  const btnGenerate = $("#btn-generate");
  container.innerHTML = "";

  songs.forEach((song) => {
    if (typeof song.confirmed !== "boolean") {
      song.confirmed = false;
    }

    const node = template.content.firstElementChild.cloneNode(true);

    const inputComposer = node.querySelector('[data-field="composer"]');
    const inputTitle = node.querySelector('[data-field="title"]');
    const btnConfirm = node.querySelector(".btn-confirm");
    const btnEdit = node.querySelector(".btn-edit");
    const btnDelete = node.querySelector(".btn-delete");

    inputComposer.value = song.composer || "";
    inputTitle.value = song.title || "";

    inputComposer.readOnly = true;
    inputTitle.readOnly = true;

    if (song.confirmed) {
      node.classList.add("row--confirmed");
    }

    // MODIFICA
    btnEdit.addEventListener("click", (e) => {
      e.preventDefault();
      inputComposer.readOnly = false;
      inputTitle.readOnly = false;
      song.confirmed = false;
      node.classList.remove("row--confirmed");
      updateGenerateState();
      inputTitle.focus();
    });

    // CONFERMA
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

    // DELETE
    btnDelete.addEventListener("click", async (e) => {
      e.preventDefault();

      const ok = await showConfirm(
        "Sei sicuro di voler cancellare questo brano?"
      );
      if (!ok) return;

      pushUndoState();

      if (song.id != null) {
        try {
          await fetch("/api/delete_song", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: song.id }),
          });
        } catch (err) {
          console.error("Errore delete:", err);
        }
      }

      const idx = songs.indexOf(song);
      if (idx !== -1) {
        songs.splice(idx, 1);
      }
      node.remove();
      updateGenerateState();
    });

    container.appendChild(node);
  });

  function updateGenerateState() {
    const total = songs.length;
    const confirmedCount = songs.filter((s) => s.confirmed).length;
    const ok = total > 0 && confirmedCount === total;
    btnGenerate.disabled = !ok;
  }

  updateGenerateState();
  updateUndoButton();
}

// --- WELCOME / MODALITÀ + CAMPO CONCERTO ---

function syncWelcomeModeRadios() {
  // Evidenzia la card corretta in base allo stato attuale
  const cards = document.querySelectorAll(".mode-card");
  cards.forEach((card) => card.classList.remove("mode-card--selected", "active"));

  const djCard = document.querySelector('.mode-card[data-mode="dj"]');
  const bandCard = document.querySelector('.mode-card[data-mode="band"]');
  const concertCard = document.querySelector('.mode-card[data-mode="concert"]');
  const artistWrapper = document.getElementById("artistInputWrapper");
  const artistInput = document.getElementById("artistInput");

  if (state.mode === "band" && bandCard) {
    bandCard.classList.add("mode-card--selected");
  } else if (state.mode === "concert" && concertCard) {
    concertCard.classList.add("mode-card--selected", "active");
    if (artistWrapper) {
      artistWrapper.classList.add("visible");
    }
    if (artistInput) {
      artistInput.value = state.concertArtist || "";
    }
  } else if (djCard) {
    djCard.classList.add("mode-card--selected");
  }
}

// Con la nuova UI la visibilità è gestita da syncWelcomeModeRadios
function updateConcertArtistVisibility() {
  syncWelcomeModeRadios();
}

function backToWelcome() {
  // Torna alla facciata 1 mantenendo l'eventuale scelta fatta
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
  const backBtn = document.getElementById("backBtn");

  // Quando arrivi sulla welcome, sincronizza le card con lo stato
  syncWelcomeModeRadios();

  function handleModeSelection(mode) {
    if (mode === "concert") {
      if (concertCard) concertCard.classList.add("active");
      if (artistWrapper) artistWrapper.classList.add("visible");
      if (artistError) artistError.textContent = "";
      if (artistInput) {
        setTimeout(() => artistInput.focus(), 10);
      }
      return;
    }

    // DJ set o live band
    state.mode = mode === "band" ? "band" : "dj";
    state.concertArtist = "";
    hydrateSessionHeader();
    setRoute("session");
    showView("#view-session");
  }

  function handleArtistSubmit() {
    if (!artistInput) return;
    const name = artistInput.value.trim();
    if (!name) {
      if (artistError) {
        artistError.textContent =
          "Inserisci il nome dell’artista prima di continuare.";
      }
      return;
    }

    if (artistError) artistError.textContent = "";

    state.mode = "concert";
    state.concertArtist = name;
    hydrateSessionHeader();
    setRoute("session");
    showView("#view-session");
  }

  modeCards.forEach((card) => {
    card.addEventListener("click", () => {
      const mode = card.dataset.mode;
      handleModeSelection(mode);
    });

    // Accessibilità tastiera
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        const mode = card.dataset.mode;
        handleModeSelection(mode);
      }
    });
  });

  if (artistWrapper) {
    // Evita che i click sull'input trigghino anche il click sulla card
    artistWrapper.addEventListener("click", (event) => {
      event.stopPropagation();
    });
  }

  if (artistConfirmBtn) {
    artistConfirmBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      handleArtistSubmit();
    });
  }

  if (artistInput) {
    artistInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        handleArtistSubmit();
      }
      event.stopPropagation();
    });
  }

  if (backBtn) {
    backBtn.addEventListener("click", (event) => {
      event.preventDefault();
      if (window.history.length > 1) {
        window.history.back();
      }
    });
  }
}

// --- WIRING BOTTONI SESSIONE / REVIEW ---
function wireSessionButtons() {
  $("#btn-session-start").addEventListener("click", (e) => {
    e.preventDefault();
    sessionStart();
  });

  $("#btn-session-pause").addEventListener("click", (e) => {
    e.preventDefault();
    sessionPause();
  });

  $("#btn-session-stop").addEventListener("click", (e) => {
    e.preventDefault();
    sessionStop();
  });

  const btnReset = $("#btn-session-reset");
  if (btnReset) {
    btnReset.addEventListener("click", (e) => {
      e.preventDefault();
      sessionReset();
    });
  }

  $("#btn-generate").addEventListener("click", (e) => {
    e.preventDefault();
    alert("TODO: Generazione PDF / CSV");
  });

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
}

// --- AVVIO ---
document.addEventListener("DOMContentLoaded", () => {
  setRoute("welcome");
  showView("#view-welcome");
  initWelcome();
  wireSessionButtons();
  
  buildVisualizer(); 
});
