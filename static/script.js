// --- STATO APP ---
const state = {
  // Nuovi stati per i ruoli
  role: null,           // "user" | "org" | "composer"
  orgRevenue: 0,        // Incasso totale (solo per Org)
  currentRoyaltySong: null, // Brano in visione per 24esimi

  // Stati originali
  mode: null,           // "dj" | "band" | "concert"
  route: "roles",       // Default ora è "roles" (Page 0)
  concertArtist: "",
  bandArtist: "",
  notes: ""
};

// playlist locale (frontend)
let songs = [];
let lastMaxSongId = 0;
let currentSongId = null;
let currentCoverUrl = null;

// Polling & Timer
let playlistPollInterval = null;
let sessionStartMs = 0;
let sessionAccumulatedMs = 0;
let sessionTick = null;

// Undo & Snapshot
let undoStack = [];
let lastSessionSnapshot = null;

// Visualizer
let waveMode = "idle";
const VIS_COLS = 96;
const VIS_ROWS = 16;
let visTick = null;
let visLevels = new Array(VIS_COLS).fill(0);

let notesModalContext = "session";

const $ = (sel) => document.querySelector(sel);

// --- UTILS ---
function pad2(n) { return n.toString().padStart(2, "0"); }
function fmt(ms) {
  const sec = Math.floor(ms / 1000);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${pad2(m)}:${pad2(s)}`;
}
// Nuova utility per valuta
function formatMoney(amount, currency = "EUR") {
  return new Intl.NumberFormat('it-IT', { style: 'currency', currency: currency }).format(amount);
}

// --- SALVATAGGIO STATO LOCALE (Originale) ---
function saveStateToLocal() {
  if (!state.mode) return;
  localStorage.setItem("appMode", state.mode);
  if (state.concertArtist) localStorage.setItem("concertArtist", state.concertArtist);
  else localStorage.removeItem("concertArtist");
  if (state.bandArtist) localStorage.setItem("bandArtist", state.bandArtist);
  else localStorage.removeItem("bandArtist");
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
    // Aggiungo "roles", "composer" e "payments" alle pagine senza scroll
    if (["welcome", "session", "roles"].includes(route)) body.classList.add("no-scroll");
    else body.classList.remove("no-scroll");
  }
}

function showView(id) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("view--active"));
  const el = document.querySelector(id);
  if (el) el.classList.add("view--active");
}

// ============================================================================
// GESTIONE RUOLI (PAGINA 0 - SVG INTERACTION)
// ============================================================================
function initRoleSelection() {
  // [MODIFICA PER SVG] Selezioniamo i gruppi spotlight invece che le card
  const roleSpots = document.querySelectorAll(".spotlight-group");
  const modalRevenue = $("#revenue-modal");
  const inputRevenue = $("#revenue-input");
  const btnRevConfirm = $("#revenue-confirm");
  const btnRevCancel = $("#revenue-cancel");
  const backBtn = $("#btn-back-roles");

  // Click su un gruppo SVG
  roleSpots.forEach(spot => {
    spot.addEventListener("click", () => {
      const role = spot.dataset.role;
      state.role = role;

      if (role === "composer") {
        setRoute("composer");
        showView("#view-composer");
        initComposerDashboard();
      } else if (role === "org") {
        modalRevenue.classList.remove("modal--hidden");
      } else {
        // Utente normale -> Welcome
        setRoute("welcome");
        showView("#view-welcome");
        initWelcome();
      }
    });
  });

  // Gestione Modale Incasso (Org)
  if(btnRevConfirm) {
    btnRevConfirm.onclick = () => {
      const val = parseFloat(inputRevenue.value);
      if(isNaN(val) || val < 0) return alert("Inserisci un importo valido");
      state.orgRevenue = val;
      modalRevenue.classList.add("modal--hidden");
      // Aggiorna Badge Revenue in sessione
      const badgeRev = $("#org-revenue-badge");
      if(badgeRev) {
        badgeRev.textContent = `Incasso: ${formatMoney(state.orgRevenue)}`;
        badgeRev.classList.remove("hidden");
      }
      setRoute("welcome");
      showView("#view-welcome");
      initWelcome();
    };
  }
  
  if(btnRevCancel) {
    btnRevCancel.onclick = () => {
      modalRevenue.classList.add("modal--hidden");
      state.role = null; 
    };
  }

  // Tasto Indietro nella Welcome Page
  if(backBtn) {
    backBtn.onclick = () => {
      setRoute("roles");
      showView("#view-roles");
      state.role = null;
      state.orgRevenue = 0;
      const br = $("#org-revenue-badge");
      if(br) br.classList.add("hidden");
    };
  }

  // Logout Compositore
  const logoutComp = $("#btn-comp-logout");
  if(logoutComp) {
    logoutComp.onclick = () => {
      setRoute("roles");
      showView("#view-roles");
    };
  }
}

// ============================================================================
// DASHBOARD COMPOSITORE
// ============================================================================
function initComposerDashboard() {
  // Dati finti Mockup
  $("#comp-total-plays").textContent = Math.floor(Math.random() * 500) + 1000;
  $("#comp-est-revenue").textContent = formatMoney(Math.random() * 5000 + 12000);

  // Chart.js Mock
  const ctx = document.getElementById('composerChart');
  if(ctx && window.Chart) {
    if(window.compChartInstance) window.compChartInstance.destroy();
    
    window.compChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: ['Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic'],
        datasets: [{
          label: 'Esecuzioni',
          data: [65, 120, 80, 85, 95, 130],
          borderColor: '#ff3f6a',
          backgroundColor: 'rgba(255, 63, 106, 0.1)',
          tension: 0.4,
          fill: true
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { grid: { color: 'rgba(255,255,255,0.1)' }, ticks: { color: '#9fb0c2' } },
          x: { grid: { display: false }, ticks: { color: '#9fb0c2' } }
        }
      }
    });
  }
}

// ============================================================================
// LOGICA ORIGINALE (VISUALIZER, POLLING, SESSIONE)
// ============================================================================

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

function setNow(title, composer) {
  const titleEl = $("#now-title");
  const compEl = $("#now-composer");
  if (titleEl) titleEl.textContent = title || "In ascolto";
  if (compEl) compEl.textContent = composer || "—";
}

function pushLog({ id, index, title, composer, artist, cover }) {
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
  // Deep copy
  const snapshot = JSON.parse(JSON.stringify(songs));
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
  songs = snapshot;
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
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
  } catch (err) { console.error(err); }
}

async function stopBackendRecognition() {
  try {
    await fetch("/api/stop_recognition", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({})
    });
  } catch (err) { console.error(err); }
}

function updateBackground(url) {
    const bgEl = document.getElementById("app-background");
    if (!bgEl) return;
    if (url) {
        const img = new Image();
        img.src = url;
        img.onload = () => {
            bgEl.style.backgroundImage = `url('${url}')`;
            bgEl.style.opacity = "1";
        };
    } else {
        bgEl.style.opacity = "0"; 
    }
}

async function pollPlaylistOnce() {
  try {
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

      const isDeleted = song.is_deleted; // [MOD] Leggi flag dal backend

      if (!existing) {
        // [MOD] Carica anche se isDeleted = true, ma non pusha in log
        // Salviamo original_fields e manual flag
        const track = {
          id, order: songs.length + 1, 
          title: song.title || "Titolo sconosciuto",
          composer: song.composer || "—", 
          artist: song.artist || "",
          album: song.album || "", type: song.type || "",
          isrc: song.isrc || null, upc: song.upc || null,
          ms: song.duration_ms || 0, confirmed: false,
          timestamp: song.timestamp || null, cover: song.cover || null,
          manual: song.manual || false, // [MOD] Flag manual
          is_deleted: isDeleted,        // [MOD] Flag deleted
          original_title: song.original_title || song.title,
          original_composer: song.original_composer || song.composer,
          original_artist: song.original_artist || song.artist
        };
        songs.push(track);

        // Se è attivo, aggiorna UI live
        if (!isDeleted && id > lastMaxSongId) {
            currentSongId = track.id;
            setNow(track.title, track.composer);
            pushLog({ id: track.id, index: track.order, title: track.title, composer: track.composer, artist: track.artist, cover: track.cover });
        }
      } else {
        // [MOD] Sync stato esistente
        if (!existing.confirmed) {
            existing.title = song.title || existing.title;
            existing.composer = song.composer || existing.composer;
            existing.artist = song.artist || existing.artist;
        }
        if (song.cover && song.cover !== existing.cover) existing.cover = song.cover;
        
        existing.is_deleted = isDeleted; // Sync cancellazione

        const composerChanged = existing.composer !== song.composer; 
        const logRow = document.querySelector(`.log-row[data-id="${id}"]`);

        if (logRow && !isDeleted) {
           if(existing.cover) logRow.querySelector(".col-cover").innerHTML = `<img src="${existing.cover}" alt="Cover" loading="lazy">`;
           if(existing.composer) logRow.querySelector(".col-composer").textContent = existing.composer;
           if(existing.artist) logRow.querySelector(".col-artist").textContent = existing.artist;
        }

        updatedExisting = true;
      }
      if (id > maxIdSeen) maxIdSeen = id;
    });

    lastMaxSongId = maxIdSeen;

    // Background sull'ultimo brano attivo
    const activeSongs = songs.filter(s => !s.is_deleted);
    const lastSongWithCover = [...activeSongs].reverse().find(s => s.cover);
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
  currentCoverUrl = null;
  updateBackground(null);
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
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({})
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

// --- REVIEW LOGIC & 24ESIMI ---
function renderReview() {
  const container = $("#review-rows");
  const template = $("#review-row-template");
  const btnGenerate = $("#btn-generate");
  const btnPayments = $("#btn-global-payments");

  if (!container || !template || !btnGenerate) return;

  container.innerHTML = "";
  
  // [MOD] Filtra solo i brani NON cancellati per la lista visuale
  const activeSongs = songs.filter(s => !s.is_deleted);

  let allConfirmed = activeSongs.length > 0;
  if (activeSongs.length === 0) allConfirmed = false;

  activeSongs.forEach((song, visualIndex) => {
    if (typeof song.confirmed !== "boolean") song.confirmed = false;
    if (!song.confirmed) allConfirmed = false;

    const node = template.content.firstElementChild.cloneNode(true);

    const indexSpan = node.querySelector(".review-index");
    const inputComposer = node.querySelector('[data-field="composer"]');
    const inputTitle = node.querySelector('[data-field="title"]');
    const btnConfirm = node.querySelector(".btn-confirm");
    const btnDelete = node.querySelector(".btn-delete");
    const btnAdd = node.querySelector(".btn-add");
    const btn24 = node.querySelector(".btn-24ths");

    if (indexSpan) indexSpan.textContent = visualIndex + 1;
    inputComposer.value = song.composer || "";
    inputTitle.value = song.title || "";
    
    // [MOD] Se manuale, opzionalmente puoi aggiungere una classe CSS
    if (song.manual) node.classList.add("row--manual");

    const setEditable = (isLocked) => {
        inputComposer.readOnly = isLocked;
        inputTitle.readOnly = isLocked;
        if(isLocked) node.classList.add("row--confirmed");
        else node.classList.remove("row--confirmed");
    };
    
    setEditable(song.confirmed);

    const unlockHandler = () => {
        if(song.confirmed) {
            song.confirmed = false;
            setEditable(false);
            renderReview(); 
        }
    };
    inputComposer.onclick = unlockHandler;
    inputTitle.onclick = unlockHandler;

    if (state.role === "org") {
        btn24.classList.remove("hidden");
        btn24.onclick = (e) => { e.preventDefault(); openRoyaltiesView(song); };
    }

    btnConfirm.addEventListener("click", (e) => {
      e.preventDefault();
      pushUndoState();
      song.composer = inputComposer.value || "";
      song.title = inputTitle.value || "";
      song.confirmed = true;
      renderReview(); 
    });

    // [MOD] DELETE LOGIC: SOFT DELETE
    btnDelete.addEventListener("click", async (e) => {
      e.preventDefault();
      const ok = await showConfirm("Sei sicuro di voler cancellare questo brano?");
      if (!ok) return;
      pushUndoState();
      
      song.is_deleted = true; // Nascondi dalla vista
      
      if (song.id != null) {
        try {
          // Nota: il backend ora fa UPDATE is_deleted=1
          await fetch("/api/delete_song", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: song.id })
          });
        } catch (err) { console.error(err); }
      }
      // Rerender per nasconderlo
      renderReview();
    });

    if (btnAdd) {
      btnAdd.addEventListener("click", (e) => {
        e.preventDefault();
        pushUndoState();
        
        // Trova l'indice reale nell'array completo songs
        const realIndex = songs.indexOf(song);
        const insertPos = realIndex === -1 ? songs.length : realIndex + 1;
        
        // [MOD] Crea brano con manual=true
        const newSong = { 
            id: null, 
            title: "", composer: "", artist: "", 
            confirmed: false, 
            manual: true, 
            is_deleted: false 
        };
        songs.splice(insertPos, 0, newSong);
        renderReview();
      });
    }
    container.appendChild(node);
  });

  const enableGlobalActions = (activeSongs.length > 0) && allConfirmed;
  
  btnGenerate.disabled = !enableGlobalActions;
  if(btnPayments) btnPayments.disabled = !enableGlobalActions;

  updateUndoButton();
  syncReviewNotes();

  const btnBackRev = $("#btn-back-review");
  if(btnBackRev) btnBackRev.onclick = () => { setRoute("review"); showView("#view-review"); };
}

// --- LOGICA DIVISIONE 24ESIMI ---
function openRoyaltiesView(song) {
    state.currentRoyaltySong = song;
    setRoute("royalties");
    showView("#view-royalties");
    
    $("#roy-song-title").textContent = song.title;
    $("#roy-total-revenue").textContent = formatMoney(state.orgRevenue);
    
    const activeSongs = songs.filter(s => !s.is_deleted);
    const totalSongs = activeSongs.length || 1;
    const pot = state.orgRevenue * 0.10; 
    const songValue = pot / totalSongs;
    
    $("#roy-song-value").textContent = formatMoney(songValue);
    
    const compList = $("#roy-composers-list");
    compList.innerHTML = "";
    
    let composers = [];
    if (song.composer && song.composer !== "Sconosciuto" && song.composer !== "—") {
        composers = song.composer.split(",").map(c => c.trim());
    } else {
        composers = ["Mario Rossi", "Giuseppe Verdi"];
    }
    
    const share = Math.floor(24 / composers.length);
    const remainder = 24 % composers.length;
    
    composers.forEach((comp, i) => {
        const myShare = share + (i === 0 ? remainder : 0);
        const amount = (songValue * myShare) / 24;
        
        const row = document.createElement("div");
        row.className = "row";
        
        row.innerHTML = `
            <span>${comp}</span>
            <span>${myShare}/24</span>
            <span class="amount-cell" style="width: 100%; text-align: right;">${formatMoney(amount)}</span>
            <span class="col-center" style="font-size:0.8rem; color:#9fb0c2;">(Incluso nel totale)</span>
        `;
        
        compList.appendChild(row);
    });

    let isEur = true;
    const btnCur = $("#btn-toggle-currency");
    const newBtn = btnCur.cloneNode(true);
    btnCur.parentNode.replaceChild(newBtn, btnCur);
    
    newBtn.onclick = () => {
        isEur = !isEur;
        const rate = isEur ? 1 : 1.1; 
        const cur = isEur ? "EUR" : "USD";
        newBtn.textContent = isEur ? "Cambia ($)" : "Cambia (€)";
        
        $("#roy-song-value").textContent = formatMoney(songValue * rate, cur);
        document.querySelectorAll(".amount-cell").forEach((cell, i) => {
             const myShare = share + (i === 0 ? remainder : 0);
             const amount = (songValue * myShare) / 24;
             cell.textContent = formatMoney(amount * rate, cur);
        });
    };
}

// --- LOGICA PAGAMENTI GLOBALI ---

function initGlobalPayments() {
  const btnPayments = $("#btn-global-payments");
  const btnBack = $("#btn-back-from-payments");
  
  if(btnPayments) {
    btnPayments.onclick = () => {
       calculateAndShowPayments();
       setRoute("payments");
       showView("#view-payments");
    };
  }
  
  if(btnBack) {
    btnBack.onclick = () => {
       setRoute("review");
       showView("#view-review");
    };
  }
}

function calculateAndShowPayments() {
  const listContainer = $("#global-payment-rows");
  const totalDisplay = $("#total-distributed-amount");
  if(!listContainer) return;
  listContainer.innerHTML = "";

  const activeSongs = songs.filter(s => !s.is_deleted);
  const totalRevenue = state.orgRevenue || 0;
  const totalSongs = activeSongs.length || 1;
  const potPerSong = (totalRevenue * 0.10) / totalSongs; 
  
  let composerTotals = {};
  let globalSum = 0;

  activeSongs.forEach(song => {
     let comps = [];
     if(song.composer && song.composer !== "—") {
       comps = song.composer.split(",").map(c => c.trim());
     } else {
       comps = ["Sconosciuto"];
     }
     
     const valPerComp = potPerSong / comps.length;
     
     comps.forEach(c => {
       if(!composerTotals[c]) composerTotals[c] = 0;
       composerTotals[c] += valPerComp;
       globalSum += valPerComp;
     });
  });

  const sortedComposers = Object.entries(composerTotals).sort((a,b) => b[1] - a[1]); 
  
  let chartLabels = [];
  let chartData = [];
  let chartColors = [];

  sortedComposers.forEach(([comp, amount], index) => {
     const row = document.createElement("div");
     row.className = "row";
     row.style.display = "flex";
     row.style.justifyContent = "space-between";
     
     row.innerHTML = `
        <span style="flex:1; font-weight:500;">${comp}</span>
        <span style="width: 100px; text-align:right; font-family:monospace;">${formatMoney(amount)}</span>
        <div style="width: 100px; text-align:center;">
           <button class="btn btn--small btn--primary btn-pay-global">Paga</button>
        </div>
     `;
     
     const btn = row.querySelector(".btn-pay-global");
     btn.onclick = () => {
        btn.textContent = "Inviato ✔";
        btn.disabled = true;
        btn.style.background = "#22c55e";
        btn.style.borderColor = "#22c55e";
     };

     listContainer.appendChild(row);

     chartLabels.push(comp);
     chartData.push(amount);
     const hue = (index * 137.508) % 360; 
     chartColors.push(`hsla(${hue}, 70%, 60%, 0.7)`);
  });

  if(totalDisplay) totalDisplay.textContent = formatMoney(globalSum);
  renderPaymentChart(chartLabels, chartData, chartColors);
}

let paymentChartInstance = null;

function renderPaymentChart(labels, data, colors) {
  const ctx = document.getElementById('paymentsChart');
  if(!ctx) return;

  if(paymentChartInstance) paymentChartInstance.destroy();

  paymentChartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: data,
        backgroundColor: colors,
        borderColor: '#12151a',
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#e6eef8', font: { size: 11 } }
        }
      }
    }
  });
}

// --- BOOTSTRAP WELCOME ---
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
      // Ignora le carte ruolo se siamo nella pagina welcome
      if(card.classList.contains("role-card")) return;

      state.mode = card.dataset.mode;
      if (state.mode === "dj") { state.concertArtist = ""; state.bandArtist = ""; }
      applyTheme();
      syncWelcomeModeRadios();
      if (state.mode === "concert" && artistInput) setTimeout(() => artistInput.focus(), 10);
      if (state.mode === "band" && bandInput) setTimeout(() => bandInput.focus(), 10);
    });
  });

  if (artistConfirmBtn) {
    artistConfirmBtn.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      const name = artistInput.value.trim();
      if (!name) return alert("Inserisci nome artista");
      state.concertArtist = name;
      saveStateToLocal();
      goToSession();
    };
  }

  if (bandConfirmBtn) {
    bandConfirmBtn.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      state.bandArtist = bandInput ? bandInput.value.trim() : "";
      saveStateToLocal();
      goToSession();
    };
  }

  if (djConfirmBtn) {
    djConfirmBtn.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      state.concertArtist = ""; state.bandArtist = "";
      saveStateToLocal();
      goToSession();
    };
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
          // [MOD] Controlliamo se ci sono brani ATTIVI
          const activeSongs = songs.filter(s => !s.is_deleted);
          if(activeSongs.length === 0) return alert("Nessun brano attivo.");
          exportModal.classList.remove("modal--hidden");
      };
  }

  async function downloadReport(fmt) {
      exportModal.classList.add("modal--hidden");
      
      let exportArtist = "Various";
      if (state.mode === "concert") exportArtist = state.concertArtist;
      if (state.mode === "band") exportArtist = state.bandArtist;
      if (state.mode === "dj") exportArtist = "DJ_Set";

      try {
          const res = await fetch("/api/generate_report", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              // Passiamo TUTTA la playlist (inclusi cancellati/manuali)
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

  // Altri bottoni standard
  const btnUndo = $("#btn-undo");
  if(btnUndo) btnUndo.onclick = (e) => { e.preventDefault(); undoLast(); };
  
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
    // Admin: Inizia da Scelta Ruolo (Page 0)
    initRoleSelection();
    initGlobalPayments();
    setRoute("roles");
    showView("#view-roles");
    
    checkRestoreSession();
    syncReviewNotes();
  }
});