const state = {
  mode: "dj",       // "dj" | "band"
  route: "welcome", // "welcome" | "session" | "review"
};

function setMode(newMode) {
  if (newMode !== "dj" && newMode !== "band") return;
  state.mode = newMode;
}

function setRoute(newRoute) {
  state.route = newRoute;
}


const $ = (sel) => document.querySelector(sel);
const pad2 = (n) => n.toString().padStart(2, "0");
const fmt = (ms) => {
  const s = Math.floor(ms/1000);
  const m = Math.floor(s/60);
  const r = s % 60;
  return `${pad2(m)}:${pad2(r)}`;
};

//Questa è la funzione che fa la magia “one-page app”: 
//prende l’id della facciata che vuoi vedere;
//nasconde le altre (hidden = true);
//mostra solo quella giusta (hidden = false).
//Quindi: qui decidi quale “schermata” si vede senza cambiare pagina.
function showView(sectionId) {
  ["#view-welcome", "#view-session", "#view-review"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    const active = id === sectionId;
    el.hidden = !active;
    el.classList.toggle("view--active", active);
  });
}

//la memoria della sessione live
const songs = []; //lista dei brani chiusi da mettere nel borderò
let currentSong = null; //il brano che sta suonando adesso
let sessionStartMs = 0;
let sessionTick = null;
let segmentTick = null;
let mockDetector = null;//finto shazam

//Quando entri nella facciata 2, serve mostrare che modalità hai scelto:
//qui semplicemente prende state.mode e aggiorna il badge in alto.
function hydrateSessionHeader(){
  $("#mode-badge").textContent = state.mode === "band" ? "Live band" : "DJ set";
}

//aggiorna i pezzi della UI “Now playing” (titolo, autore, durata).
function setNow(title, composer) {
  $("#now-title").textContent = title || "In ascolto";
  $("#now-composer").textContent = composer || "—";
  $("#now-duration").textContent = currentSong ? fmt(currentSong.ms) : "00:00";
}
//aggiunge una riga nel 'log live'
function pushLog({when, title, composer, status}) {
  const row = document.createElement("div");
  row.className = "log-row";
  row.innerHTML = `
    <span>${when}</span>
    <span>${title}</span>
    <span>${composer}</span>
    <span class="${status === "OK" ? "status-ok" : status === "SAME" ? "status-same" : "status-new"}">${status}</span>
  `;
  $("#live-log").prepend(row);
}

// mock shazam
const MOCK_TRACKS = [
  { title: "Billie Jean", composer: "M. Jackson" },
  { title: "Come Together", composer: "Lennon–McCartney" },
  { title: "Get Lucky", composer: "Pharrell / Daft Punk" },
  { title: "Il cielo in una stanza", composer: "G. Paoli" },
  { title: "Blurred Lines", composer: "Thicke / Williams" },
];

function isRunning(){ return !!sessionTick; }

function startMockDetector() {
  stopMockDetector();
  mockDetector = setInterval(() => {
    if (!isRunning()) return;
    const pick = MOCK_TRACKS[Math.floor(Math.random()*MOCK_TRACKS.length)];
    onTrackDetected(pick);
  }, 14000);
}
function stopMockDetector() {
  if (mockDetector) { clearInterval(mockDetector); mockDetector = null; }
}

//se è detectata una cosa come la prima lascio SAME se è detectata una cosa nuova metto la vecchia nell'array sons e la nuova la faccio apparire
function onTrackDetected(track) {
  const now = new Date();
  const when = `${pad2(now.getHours())}:${pad2(now.getMinutes())}`;

  if (currentSong &&
      currentSong.title === track.title &&
      currentSong.composer === track.composer) {
    pushLog({when, title: track.title, composer: track.composer, status: "SAME"});
    return;
  }

  if (currentSong) {
    songs.push({
      title: currentSong.title,
      composer: currentSong.composer,
      ms: currentSong.ms
    });
  }

  currentSong = {
    title: track.title,
    composer: track.composer,
    startMs: Date.now(),
    ms: 0
  };

  pushLog({when, title: track.title, composer: track.composer, status: "NEW"});
  setNow(track.title, track.composer);
}

//fa partire il timer generale della sessione e il timer
function startTimers(){
  if (!sessionStartMs) sessionStartMs = Date.now();

  sessionTick = setInterval(() => {
    const elapsed = Date.now() - sessionStartMs;
    $("#session-timer").textContent = fmt(elapsed);
  }, 1000);

  segmentTick = setInterval(() => {
    if (currentSong) {
      currentSong.ms = Date.now() - currentSong.startMs;
      $("#now-duration").textContent = fmt(currentSong.ms);
    }
  }, 1000);
}
function stopTimers(){
  if (sessionTick) { clearInterval(sessionTick); sessionTick = null; }
  if (segmentTick) { clearInterval(segmentTick); segmentTick = null; }
}


function sessionStart(){
  $("#btn-session-start").disabled = true;
  $("#btn-session-pause").disabled = false;
  $("#btn-session-stop").disabled = false;

  hydrateSessionHeader();

  if (!currentSong) setNow("In ascolto", "—");
  startTimers();
  startMockDetector();
}

function sessionPause(){
  $("#btn-session-start").disabled = false;
  $("#btn-session-pause").disabled = true;
  $("#btn-session-stop").disabled = false;

  stopTimers();
  stopMockDetector();
}

function sessionStop(){
  stopTimers();
  stopMockDetector();

  if (currentSong) {
    songs.push({
      title: currentSong.title,
      composer: currentSong.composer,
      ms: currentSong.ms
    });
    currentSong = null;
  }
//reset dei bottoni
  $("#btn-session-start").disabled = false;
  $("#btn-session-pause").disabled = true;
  $("#btn-session-stop").disabled = true;

  renderReview();//sto preparando i dati per la facciata 3
  setRoute("review");
  showView("#view-review");
}

function renderReview(){
  const mount = $("#review-rows");
  mount.innerHTML = "";
  if (!songs.length) {
    mount.innerHTML = `<div class="row"><span>—</span><span>Nessun brano</span><span>00:00</span><span></span></div>`;
    $("#btn-generate").disabled = true;
    return;
  }

  let confirmed = new Set();

    const template = $("#review-row-template");

  songs.forEach((seg, idx) => {
    // clona il contenuto del template
    const fragment = template.content.cloneNode(true);
    const row = fragment.querySelector(".row");
    row.dataset.index = idx.toString();

    const composerIn = row.querySelector(".composer-input");
    const titleIn = row.querySelector(".title-input");
    const durationEl = row.querySelector(".duration-cell");

    composerIn.value = seg.composer;
    titleIn.value = seg.title;
    durationEl.textContent = fmt(seg.ms);

    mount.appendChild(row);
  });


  mount.onclick = (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const row = btn.closest(".row");
    const i = Number(row.dataset.index);

    if (btn.dataset.action === "confirm") {
      const [composerIn, titleIn] = row.querySelectorAll("input.inline");
      songs[i].composer = composerIn.value.trim();
      songs[i].title = titleIn.value.trim();
      confirmed.add(i);
      btn.textContent = "OK";
      btn.disabled = true;
    }
    if (btn.dataset.action === "delete") {
    songs.splice(i,1);
      renderReview();
      return;
    }

    $("#btn-generate").disabled =
      confirmed.size !== songs.length || songs.length === 0;
  };
}


function wireSessionButtons(){
  $("#btn-session-start").onclick = (e) => { e.preventDefault(); sessionStart(); };
  $("#btn-session-pause").onclick = (e) => { e.preventDefault(); sessionPause(); };
  $("#btn-session-stop").onclick  = (e) => { e.preventDefault(); sessionStop();  };
}

function initWelcome() {
  const form = $("#welcome-form");
  const startBtn = $("#btn-start-program");

  form.onchange = (e) => {
    if (e.target.name === "mode") setMode(e.target.value);
  };

  startBtn.onclick = (e) => {
    e.preventDefault();
    setRoute("session");
    showView("#view-session");
  };
}


document.addEventListener("DOMContentLoaded", () => {
  initWelcome();
  wireSessionButtons();
  showView("#view-welcome");
});
