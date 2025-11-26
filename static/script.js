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
  $("#now-title").textContent = title || "In ascolto";
  $("#now-composer").textContent = composer || "—";
}

// --- ONDA STAZIONARIA SOTTO "IN ASCOLTO" ---
function initListeningWave() {
  const canvas = document.getElementById("now-wave");
  if (!canvas || !canvas.getContext) return;

  const ctx = canvas.getContext("2d");
  let dpr = window.devicePixelRatio || 1;

  function resize() {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  const MIN_NODES = 2;
  const MAX_NODES = 20;

  // nodi interni (numero di "lobi" della stazionaria)
  let currentNodes = 8;
  let targetNodes = 8;
  let lastNodeChange = 0;

  // fattore di ampiezza casuale dell’inviluppo (0.3..1.0, liscio nel tempo)
  let envAmpCurrent = 0.7;
  let envAmpTarget = 0.7;
  let lastEnvChange = 0;

  // nodo centrale mobile (in coordinate normalizzate 0..1)
  const MIN_CENTER = 0.15;
  const MAX_CENTER = 0.85;
  let nodeCenter = 0.5;
  let nodeDir = Math.random() < 0.5 ? 1 : -1; // +1 dx, -1 sx
  let nextDirSwitch = 0;
  const nodeSpeed = 0.0002; // frazione di larghezza per ms (~0.2/sec)

  const speed = 0.002; // velocità di oscillazione base
  let phase = 0; // fase dell'onda
  let amplitudeLevel = 0; // 0 = linea piatta, 1 = piena

  let lastTime = 0;

  function draw(timestamp) {
    if (!lastTime) lastTime = timestamp;
    const dt = timestamp - lastTime;
    lastTime = timestamp;

    // fase a seconda dello stato
    if (waveMode === "playing") {
      phase += speed * dt;
    } else if (waveMode === "paused") {
      phase += speed * dt * 0.3; // si muove piano mentre svanisce
    }

    // cambio “target” nodi circa ogni DUE secondi (2..20)
    if (!lastNodeChange) lastNodeChange = timestamp;
    if (timestamp - lastNodeChange > 500) {
      lastNodeChange = timestamp;

      let next =
        MIN_NODES +
        Math.floor(Math.random() * (MAX_NODES - MIN_NODES + 1)); // 2..20

      if (next === Math.round(targetNodes)) {
        const span = MAX_NODES - MIN_NODES + 1;
        next = MIN_NODES + ((next - MIN_NODES + 1) % span);
      }
      targetNodes = next;
    }

    // transizione morbida tra numero di nodi attuale e target
    currentNodes += (targetNodes - currentNodes) * 0.08;

    // ampiezza globale: playing = 1, idle/paused = 0 (va a zero gradualmente)
    const targetAmplitudeLevel = waveMode === "playing" ? 1 : 0;
    amplitudeLevel += (targetAmplitudeLevel - amplitudeLevel) * 0.05;

    // fattore di ampiezza casuale dell’inviluppo (respira random)
    if (!lastEnvChange) lastEnvChange = timestamp;
    if (timestamp - lastEnvChange > 900) {
      lastEnvChange = timestamp;
      envAmpTarget = 0.3 + Math.random() * 0.7; // 0.3..1.0
    }
    envAmpCurrent += (envAmpTarget - envAmpCurrent) * 0.05;

    // nodo centrale che si muove con moto continuo e inversione random (< 2s)
    if (!nextDirSwitch) {
      nextDirSwitch = timestamp + 300 + Math.random() * 1700; // tra 0.3s e 2s
    }
    if (timestamp >= nextDirSwitch) {
      nodeDir *= -1; // cambia direzione
      nextDirSwitch = timestamp + 300 + Math.random() * 1700;
    }

    nodeCenter += nodeDir * nodeSpeed * dt;

    // rimbalzo ai bordi con reset del timer di inversione
    if (nodeCenter < MIN_CENTER) {
      nodeCenter = MIN_CENTER;
      nodeDir = 1;
      nextDirSwitch = timestamp + 300 + Math.random() * 1700;
    } else if (nodeCenter > MAX_CENTER) {
      nodeCenter = MAX_CENTER;
      nodeDir = -1;
      nextDirSwitch = timestamp + 300 + Math.random() * 1700;
    }

    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      requestAnimationFrame(draw);
      return;
    }

    const width = rect.width;
    const height = rect.height;
    const centerY = height / 2;
    const baseAmplitude = height * 0.35;

    // fading: più veloce quando “suona”, più lento quando va a spegnersi
    const fadeAlpha = waveMode === "playing" ? 0.06 : 0.0075;
    ctx.fillStyle = `rgba(11, 12, 16, ${fadeAlpha})`;
    ctx.fillRect(0, 0, width, height);

    // k controlla il numero di nodi interni della stazionaria
    const k = (currentNodes * Math.PI) / width;

    ctx.beginPath();
    for (let x = 0; x <= width; x += 2) {
      const pos = x / width;

      // inviluppo con nodo a sinistra (0), nodo centrale mobile (nodeCenter),
      // nodo a destra (1), costruito con due mezze sinusoidi
      let envelope;
      if (pos <= nodeCenter) {
        const denom = nodeCenter <= 0.001 ? 0.001 : nodeCenter;
        const t = pos / denom; // 0..1
        envelope = Math.sin(Math.PI * t); // 0 -> π
      } else {
        const denom = 1 - nodeCenter <= 0.001 ? 0.001 : 1 - nodeCenter;
        const t = (pos - nodeCenter) / denom; // 0..1
        envelope = Math.sin(Math.PI * t);
      }
      if (envelope < 0) envelope = 0;

      // ampiezza locale = inviluppo * fattore random * ampiezza globale
      const localGain = envAmpCurrent * envelope;
      const amplitude =
        baseAmplitude * amplitudeLevel * localGain; // 0 se idle/paused completo

      const y = centerY + amplitude * Math.sin(k * x) * Math.cos(phase);

      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }

    const grad = ctx.createLinearGradient(0, 0, width, 0);
    grad.addColorStop(0, "rgba(94, 234, 212, 0.7)");
    grad.addColorStop(0.5, "rgba(120, 150, 255, 0.8)");
    grad.addColorStop(1, "rgba(124, 58, 237, 0.9)");

    ctx.lineWidth = 2;
    ctx.strokeStyle = grad;
    ctx.globalCompositeOperation = "lighter";
    ctx.stroke();
    ctx.globalCompositeOperation = "source-over";

    requestAnimationFrame(draw);
  }

  resize();
  window.addEventListener("resize", resize);
  requestAnimationFrame(draw);
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
}

async function sessionPause() {
  $("#btn-session-start").disabled = false;
  $("#btn-session-pause").disabled = true;
  $("#btn-session-stop").disabled = false;

  waveMode = "paused";

  pauseSessionTimer();
  await stopBackendRecognition();
  stopPlaylistPolling();
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
  const dj = document.querySelector('input[name="mode"][value="dj"]');
  const band = document.querySelector('input[name="mode"][value="band"]');
  const concert = document.querySelector('input[name="mode"][value="concert"]');
  if (!dj || !band || !concert) return;

  if (state.mode === "band") {
    band.checked = true;
  } else if (state.mode === "concert") {
    concert.checked = true;
  } else {
    dj.checked = true;
  }

  updateConcertArtistVisibility();
}

function updateConcertArtistVisibility() {
  const group = $("#concert-artist-group");
  if (!group) return;
  const modeInput = document.querySelector('input[name="mode"]:checked');
  const modeValue = modeInput ? modeInput.value : "dj";
  if (modeValue === "concert") {
    group.classList.remove("hidden");
  } else {
    group.classList.add("hidden");
  }
}

function backToWelcome() {
  syncWelcomeModeRadios();
  setRoute("welcome");
  showView("#view-welcome");
}

function initWelcome() {
  const form = $("#welcome-form");

  syncWelcomeModeRadios();

  const modeRadios = form.querySelectorAll('input[name="mode"]');
  modeRadios.forEach((radio) => {
    radio.addEventListener("change", () => {
      updateConcertArtistVisibility();
    });
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const modeInput = form.querySelector('input[name="mode"]:checked');
    const modeValue = modeInput ? modeInput.value : "dj";
    setMode(modeValue);

    if (modeValue === "concert") {
      const artistInput = $("#concert-artist");
      state.concertArtist = artistInput ? artistInput.value.trim() : "";
    }

    hydrateSessionHeader();
    setRoute("session");
    showView("#view-session");
  });

  $("#btn-welcome-start").addEventListener("click", (e) => {
    e.preventDefault();
    form.requestSubmit();
  });
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
  initListeningWave(); // onda in stato "idle" finché non premi Start
});
