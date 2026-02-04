// --- 1. CONFIGURAZIONE FIREBASE (Incolla qui in cima) ---
const firebaseConfig = {
  apiKey: "AIzaSyDPtkUaiTQSxUB9x7x1xWF9XHdVqBXLb-s",
  authDomain: "actam-project-8f9de.firebaseapp.com",
  projectId: "actam-project-8f9de",
  storageBucket: "actam-project-8f9de.firebasestorage.app",
  messagingSenderId: "116409170757",
  appId: "1:116409170757:web:0b2aba5b9aa133bb15dc2c",
  measurementId: "G-RHPHMPTPDE"
};

// --- 2. INIZIALIZZAZIONE ---
// Controlliamo che firebase sia stato caricato (per evitare errori se manca internet)
if (typeof firebase !== 'undefined') {
  firebase.initializeApp(firebaseConfig);
  console.log("🔥 Firebase Client inizializzato!");
} else {
  console.error("❌ Librerie Firebase non trovate. Controlla index.html");
}
// --- STATO APP ---
const state = {
  role: null,            
  orgRevenue: 0,          
  orgRevenueConfirmed: false, 
  currentRoyaltySong: null, 
  mode: null,             
  route: "roles",         
  concertArtist: "",
  bandArtist: "",
  notes: ""
};

let pendingRole = null;
let songs = [];
let lastMaxSongId = 0;
let currentSongId = null;
let currentCoverUrl = null;
let explicitRestore = false; // Flag per capire se l'utente ha richiesto esplicitamente il ripristino

let playlistPollInterval = null;
let sessionStartMs = 0;
let sessionAccumulatedMs = 0;
let sessionTick = null;

let undoStack = [];
let lastSessionSnapshot = null;
let notesModalContext = "session";
let hoveredRole = null; 

const $ = (sel) => document.querySelector(sel);

// --- UTILS ---
function pad2(n) { return n.toString().padStart(2, "0"); }

function fmt(ms) {
  const sec = Math.floor(ms / 1000);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${pad2(m)}:${pad2(s)}`;
}

function formatMoney(amount, currency = "EUR") {
  return new Intl.NumberFormat('it-IT', { style: 'currency', currency: currency }).format(amount);
}

function lerp(start, end, amt) {
    return (1 - amt) * start + amt * end;
}

function saveStateToLocal() {
  if (!state.mode) return;
  localStorage.setItem("appMode", state.mode);
  if (state.concertArtist) localStorage.setItem("concertArtist", state.concertArtist);
  else localStorage.removeItem("concertArtist");
  if (state.bandArtist) localStorage.setItem("bandArtist", state.bandArtist);
  else localStorage.removeItem("bandArtist");
}

function applyTheme() {
  const app = document.getElementById("app");
  if (!app) return;
  app.classList.remove("theme-dj", "theme-band", "theme-concert");
  if (state.mode === "band") app.classList.add("theme-band");
  else if (state.mode === "concert") app.classList.add("theme-concert");
  else if (state.mode === "dj") app.classList.add("theme-dj");
}

function setRoute(route) {
  state.route = route;
  const body = document.body;
  if (body) {
    body.setAttribute("data-active-view", route);
    if (["welcome", "session", "roles"].includes(route)) body.classList.add("no-scroll");
    else body.classList.remove("no-scroll");
  }
}

function showView(id) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("view--active"));
  const el = document.querySelector(id);
  if (el) el.classList.add("view--active");
  const viewName = id.replace("#view-", "");
  setRoute(viewName);
}

// ============================================================================
// GESTIONE RUOLI & AUTH
// ============================================================================
function initRoleSelection() {
  const roleSpots = document.querySelectorAll(".spotlight-group");
  const authModal = $("#auth-modal");
  const btnLogin = $("#btn-auth-login");
  const btnGuest = $("#btn-auth-guest");
  const linkRegister = $("#link-register");
  const btnCloseAuth = $("#btn-auth-close");

  const btnCompBack = $("#btn-comp-back");
  if (btnCompBack) {
      btnCompBack.onclick = () => {
          showView("#view-welcome");
      };
  }
  
  roleSpots.forEach(spot => {
    spot.addEventListener("mouseenter", () => {
      hoveredRole = spot.dataset.role;
    });
    spot.addEventListener("mouseleave", () => {
      hoveredRole = null;
    });
    spot.addEventListener("click", () => {
      const role = spot.dataset.role;
      pendingRole = role; 
      $("#auth-email").value = "";
      $("#auth-pass").value = "";
      authModal.classList.remove("modal--hidden");
    });
  });

  if(btnCloseAuth) {
      btnCloseAuth.onclick = () => {
          authModal.classList.add("modal--hidden");
          pendingRole = null; 
      };
  }

  if (btnLogin) {
    btnLogin.onclick = async () => {
        const email = $("#auth-email").value.trim();
        const pass = $("#auth-pass").value.trim();

        if(!email || !pass) {
            alert("Per favore inserisci email e password");
            return;
        }

        // --- INTEGRAZIONE FIREBASE ---
        try {
            // Cambio il testo del bottone per feedback visivo
            const originalText = btnLogin.textContent;
            btnLogin.textContent = "Accesso in corso...";
            btnLogin.disabled = true;

            // Chiamata reale a Firebase Auth
            // Assicurati che 'auth' sia importato/inizializzato nel tuo progetto
            // (es. import { auth } from './firebase-config.js' oppure window.auth)
            await firebase.auth().signInWithEmailAndPassword(email, pass);
            
            // Se non va in errore, l'observer onAuthStateChanged (se lo hai) 
            // o la funzione qui sotto gestirà il redirect.
            completeAuth(); 

        } catch (error) {
            console.error("Login error:", error);
            alert("Errore login: " + error.message);
        } finally {
            // Ripristino bottone
            btnLogin.textContent = "Accedi";
            btnLogin.disabled = false;
        }
        // -----------------------------
    };
  }

  if (btnGuest) {
    btnGuest.onclick = () => {
        completeAuth();
    };
  }

  if (linkRegister) {
    linkRegister.onclick = (e) => {
        e.preventDefault();
        alert("Redirect alla pagina di registrazione (non implementata)");
    };
  }
}

function completeAuth() {
    const authModal = $("#auth-modal");
    authModal.classList.add("modal--hidden"); 
    state.role = pendingRole; 
    state.orgRevenueConfirmed = false; 
    state.orgRevenue = 0;
    showView("#view-welcome");
    initWelcome();
}

function initComposerDashboard() {
  $("#comp-total-plays").textContent = Math.floor(Math.random() * 500) + 1000;
  $("#comp-est-revenue").textContent = formatMoney(Math.random() * 5000 + 12000);

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
          borderColor: "#EC368D",
          backgroundColor: "#EC368D33",
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
// LOGICA SESSIONE
// ============================================================================
function hydrateSessionHeader() {
  const badge = $("#mode-badge");
  const revInputContainer = $("#org-revenue-input-container");
  const revDisplay = $("#org-revenue-display");
  const btnStart = $("#btn-session-start");
  
  if (!badge) return;

  if (state.mode === "band") {
    const artistName = state.bandArtist ? state.bandArtist.toUpperCase() : "";
    badge.textContent = artistName ? `LIVE BAND: ${artistName}` : "LIVE BAND";
  } else if (state.mode === "concert") {
    const artistName = state.concertArtist ? state.concertArtist.toUpperCase() : "";
    badge.textContent = artistName ? `CONCERTO: ${artistName}` : "CONCERTO";
  } else {
    badge.textContent = "SESSIONE";
  }

  if (state.role === "org") {
      if(!state.orgRevenueConfirmed) {
          revInputContainer.classList.remove("hidden");
          revDisplay.classList.add("hidden");
          if(btnStart) {
              btnStart.disabled = true; 
              // MODIFICA: Aggiunto Tooltip per l'organizzatore quando non ha confermato
              btnStart.setAttribute("data-tooltip", "Indicare l'incasso dell'evento prima di avviare la sessione");
          }
      } else {
          revInputContainer.classList.add("hidden");
          revDisplay.classList.remove("hidden");
          revDisplay.textContent = `Incasso: ${formatMoney(state.orgRevenue)}`;
          if(btnStart) {
              btnStart.disabled = false;
              // Rimuovo il tooltip se tutto è ok
              btnStart.removeAttribute("data-tooltip");
          }
      }
  } else {
      revInputContainer.classList.add("hidden");
      revDisplay.classList.add("hidden");
      if(btnStart) {
          btnStart.disabled = false;
          // Rimuovo tooltip per ruoli non-organizzatore
          btnStart.removeAttribute("data-tooltip");
      }
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

function pushUndoState() {
  const snapshot = JSON.parse(JSON.stringify(songs));
  undoStack.push(snapshot);
  if (undoStack.length > 5) undoStack.shift();
  updateUndoButton();
}

function updateUndoButton() {
  const btnUndo = $("#btn-undo");
  if (btnUndo) btnUndo.disabled = undoStack.length === 0;
}

function undoLast() {
  if (!undoStack.length) return;
  songs = undoStack.pop();
  renderReview();
  updateUndoButton();
}

async function startBackendRecognition() {
  const body = {};
  if (state.mode === "concert" && state.concertArtist) body.targetArtist = state.concertArtist;
  else if (state.mode === "band" && state.bandArtist) body.targetArtist = state.bandArtist;

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
      const isDeleted = song.is_deleted; 

      if (!existing) {
        const track = {
          id, order: songs.length + 1, 
          title: song.title || "Titolo sconosciuto",
          composer: song.composer || "—", 
          artist: song.artist || "",
          cover: song.cover || null,
          manual: song.manual || false,
          is_deleted: isDeleted,
          confirmed: false,
          // MAPPIAMO I CAMPI ORIGINALI DAL DB
          original_title: song.original_title,
          original_artist: song.original_artist,
          original_composer: song.original_composer
        };
        songs.push(track);

        if (!isDeleted && id > lastMaxSongId) {
            currentSongId = track.id;
            setNow(track.title, track.composer);
            pushLog({ id: track.id, index: track.order, title: track.title, composer: track.composer, artist: track.artist, cover: track.cover });
        }
      } else {
        if (song.composer && song.composer !== existing.composer) {
            existing.composer = song.composer;
            const rowEl = document.querySelector(`.log-row[data-id="${id}"] .col-composer`);
            if (rowEl) rowEl.textContent = existing.composer;
            if (currentSongId === id) setNow(existing.title, existing.composer);
        }
        
        // Aggiorniamo anche i campi originali nel caso l'enrichment li abbia cambiati
        if (song.original_composer && song.original_composer !== existing.original_composer) {
            existing.original_composer = song.original_composer;
        }

        if (!existing.confirmed) {
            existing.title = song.title || existing.title;
            existing.artist = song.artist || existing.artist;
        }
        if (song.cover && song.cover !== existing.cover) existing.cover = song.cover;
        existing.is_deleted = isDeleted;
        updatedExisting = true;
      }
      if (id > maxIdSeen) maxIdSeen = id;
    });

    lastMaxSongId = maxIdSeen;
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
  showView("#view-session");
  hydrateSessionHeader();
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  
  if (btnStart) btnStart.disabled = true;
  if (btnPause) btnPause.disabled = false;
  if (btnStop) btnStop.disabled = false;

  const led = $(".led-rect");
  if(led) {
      led.classList.remove("led-paused", "led-fading-out");
      led.classList.add("led-active");
  }

  // LOGICA START/RESTORE
  // Se non ho richiesto esplicitamente il ripristino, forzo un reset del DB
  if (!explicitRestore) {
      try {
          await fetch("/api/reset_session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
          // Resetto anche localmente per sicurezza visiva immediata
          songs = [];
          $("#live-log").innerHTML = "";
      } catch (err) { console.error(err); }
      // Dopo il primo start forzato, consideriamo la sessione "avviata" (quindi se mette pausa e start non resetta più)
      explicitRestore = true; 
  }

  if (!sessionTick) startSessionTimer();
  await startBackendRecognition();
  startPlaylistPolling();
}

async function sessionPause() {
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  
  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = false;

  const led = $(".led-rect");
  if(led) {
      led.classList.add("led-paused");
  }
  
  pauseSessionTimer();
  await stopBackendRecognition();
  stopPlaylistPolling();
}

async function sessionStop() {
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  
  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = true;

  const led = $(".led-rect");
  if(led) {
      led.classList.add("led-paused");
  }

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
  showView("#view-review");
}

async function sessionReset() {
  await stopBackendRecognition();
  stopPlaylistPolling();
  pauseSessionTimer();
  resetSessionTimer();
  
  try {
    await fetch("/api/reset_session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
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
  
  state.orgRevenue = 0;
  state.orgRevenueConfirmed = false;
  explicitRestore = false; // Reset del flag, prossimo start sarà pulito

  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  
  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = true;

  // ANIMAZIONE LED (Fade in place)
  const led = $(".led-rect");
  if(led) {
      // Blocca l'animazione dov'è e imposta opacità a 0
      led.classList.add("led-fading-out");
      
      // Aspetta che la transizione CSS di 1s finisca prima di resettare le classi
      setTimeout(() => {
          led.classList.remove("led-active", "led-paused", "led-fading-out");
          // Rimuovere led-active resetta lo stroke-dashoffset, ma ora è invisibile (opacity 0)
      }, 1000);
  }
  hydrateSessionHeader();
}

function renderReview() {
  const container = $("#review-rows");
  const template = $("#review-row-template");
  const btnGenerate = $("#btn-generate");
  const btnPayments = $("#btn-global-payments");

  if (!container || !template || !btnGenerate) return;

  container.innerHTML = "";
  const activeSongs = songs.filter(s => !s.is_deleted);
  let allConfirmed = activeSongs.length > 0;
  if (activeSongs.length === 0) allConfirmed = false;

  activeSongs.forEach((song, visualIndex) => {
    if (typeof song.confirmed !== "boolean") song.confirmed = false;
    if (!song.confirmed) allConfirmed = false;

    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".review-index").textContent = visualIndex + 1;
    
    const inputComposer = node.querySelector('[data-field="composer"]');
    const inputTitle = node.querySelector('[data-field="title"]');
    inputComposer.value = song.composer || "";
    inputTitle.value = song.title || "";
    
    if (song.manual) node.classList.add("row--manual");

    if(song.confirmed) {
        inputComposer.readOnly = true;
        inputTitle.readOnly = true;
        node.classList.add("row--confirmed");
    }

    const unlockHandler = () => {
        if(song.confirmed) {
            song.confirmed = false;
            renderReview(); 
        }
    };
    inputComposer.onclick = unlockHandler;
    inputTitle.onclick = unlockHandler;

    const btn24 = node.querySelector(".btn-24ths");
    btn24.classList.remove("hidden");
    btn24.onclick = () => { openRoyaltiesView(song); };

    node.querySelector(".btn-confirm").addEventListener("click", (e) => {
        e.preventDefault();
        pushUndoState();
        song.composer = inputComposer.value || "";
        song.title = inputTitle.value || "";
        song.confirmed = true;
        renderReview(); 
    });

    node.querySelector(".btn-delete").addEventListener("click", async (e) => {
        e.preventDefault();
        if(await showConfirm("Sei sicuro?")) {
            pushUndoState();
            song.is_deleted = true; 
            try {
                await fetch("/api/delete_song", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: song.id }) });
            } catch(err){console.error(err);}
            renderReview();
        }
    });

    node.querySelector(".btn-add").addEventListener("click", (e) => {
        e.preventDefault();
        pushUndoState();
        const realIndex = songs.indexOf(song);
        const insertPos = realIndex === -1 ? songs.length : realIndex + 1;
        songs.splice(insertPos, 0, { id: null, title: "", composer: "", artist: "", confirmed: false, manual: true, is_deleted: false });
        renderReview();
    });

    container.appendChild(node);
  });
  
  const enableGlobalActions = (activeSongs.length > 0) && allConfirmed;
  
  btnGenerate.disabled = !enableGlobalActions;
  
  if(btnPayments) {
      if(state.role === 'org') {
          btnPayments.classList.remove("hidden");
          btnPayments.disabled = !enableGlobalActions;
      } else {
          btnPayments.classList.add("hidden");
      }
  }

  updateUndoButton();
  syncReviewNotes();
}

function openRoyaltiesView(song) {
    state.currentRoyaltySong = song;
    showView("#view-royalties");
    
    const isOrg = (state.role === 'org');

    const boxRevenue = $("#box-revenue");
    const boxQuota = $("#box-quota");
    
    // Aggiornamento Box Revenue
    if(boxRevenue) {
        if(isOrg) {
            boxRevenue.classList.remove("hidden");
            $("#roy-total-revenue").textContent = formatMoney(state.orgRevenue);
        } else {
            // Se non sei organizzatore, nascondi l'intero box o rendilo invisibile
            // Qui usiamo display:none tramite la classe hidden
            boxRevenue.classList.add("hidden");
        }
    }
    
    // Aggiornamento Box Quota
    if(boxQuota) {
        if(isOrg) {
            boxQuota.classList.remove("hidden");
            const activeSongs = songs.filter(s => !s.is_deleted);
            const songValue = (state.orgRevenue * 0.10) / (activeSongs.length || 1);
            $("#roy-song-value").textContent = formatMoney(songValue);
        } else {
            boxQuota.classList.add("hidden");
        }
    }
    
    $("#roy-song-title").textContent = song.title;
    
    const colHeaderAmount = $("#col-header-amount");
    if(colHeaderAmount) {
        colHeaderAmount.style.display = isOrg ? "block" : "none";
    }

    const compList = $("#roy-composers-list");
    compList.innerHTML = "";
    
    const composers = (song.composer && song.composer !== "—") ? song.composer.split(",").map(c => c.trim()) : ["Mario Rossi", "Giuseppe Verdi"];
    const share = Math.floor(24 / composers.length);
    const remainder = 24 % composers.length;
    
    let songValueBase = 0;
    if(isOrg) {
        const activeSongs = songs.filter(s => !s.is_deleted);
        songValueBase = (state.orgRevenue * 0.10) / (activeSongs.length || 1);
    }
    
    composers.forEach((comp, i) => {
        const myShare = share + (i === 0 ? remainder : 0);
        let amountText = "";
        
        if(isOrg) {
            const amount = (songValueBase * myShare) / 24;
            amountText = formatMoney(amount);
        }
        
        const row = document.createElement("div");
        row.className = "row";
        
        const displayStyle = isOrg ? "block" : "none";

        // MODIFICA: Rimossa colonna 'Nota' (span con 'Incluso')
        row.innerHTML = `
            <span class="col-left">${comp}</span>
            <span class="col-center">${myShare}/24</span>
            <span class="col-right" style="display: ${displayStyle};">${amountText}</span>
        `;
        
        compList.appendChild(row);
    });
}

function initGlobalPayments() {
  const btnPayments = $("#btn-global-payments");
  const btnBack = $("#btn-back-from-payments");
  
  if(btnPayments) {
    btnPayments.onclick = () => {
        if(state.role !== 'org') return; 
        calculateAndShowPayments();
        showView("#view-payments");
    };
  }
  
  if(btnBack) {
    btnBack.onclick = () => {
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
  const potPerSong = (state.orgRevenue * 0.10) / (activeSongs.length || 1); 
  
  let composerTotals = {};
  let globalSum = 0;

  activeSongs.forEach(song => {
      let comps = (song.composer && song.composer !== "—") ? song.composer.split(",").map(c => c.trim()) : ["Sconosciuto"];
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

  const palette = [
    "#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40", 
    "#C9CBCF", "#FFCD56", "#E7E9ED", "#76D7C4", "#1E8449", "#F1948A"
  ];

  sortedComposers.forEach(([comp, amount], index) => {
      const row = document.createElement("div");
      row.className = "row";
      row.style.display = "flex";
      row.style.justifyContent = "space-between";
      
      row.innerHTML = `
        <span style="flex:1;">${comp}</span>
        <span style="width: 100px; text-align:right;">${formatMoney(amount)}</span>
        <div style="width: 100px; text-align:center;">
           <button class="btn btn--small btn--primary btn-pay-global">Paga</button>
        </div>
      `;
      
      row.querySelector(".btn-pay-global").onclick = (e) => {
        e.target.textContent = "Inviato ✔";
        e.target.disabled = true;
        e.target.style.background = "#22c55e";
      };

      listContainer.appendChild(row);

      chartLabels.push(comp);
      chartData.push(amount);
      chartColors.push(palette[index % palette.length]);
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

function syncWelcomeModeRadios() {
  document.querySelectorAll(".mode-card").forEach((card) => card.classList.remove("mode-card--selected", "active"));
  document.querySelectorAll(".artist-input-wrapper").forEach(w => w.classList.remove("visible"));

  if (state.mode) {
    const c = document.querySelector(`.mode-card[data-mode="${state.mode}"]`);
    if(c) c.classList.add("mode-card--selected");

    if (state.mode === "band") {
      $("#bandArtistWrapper").classList.add("visible");
      if($("#bandArtistInput")) $("#bandArtistInput").value = state.bandArtist || "";
    } else if (state.mode === "concert") {
      $("#artistInputWrapper").classList.add("visible");
      if($("#artistInput")) $("#artistInput").value = state.concertArtist || "";
    }
  }
}

function initWelcome() {
  state.mode = null;
  applyTheme();
  syncWelcomeModeRadios();
  
  const grid = $("#welcome-grid");
  const statCard = $("#card-stats");
  
  if (state.role === "composer") {
      statCard.classList.remove("hidden");
      grid.classList.add("mode-grid--composer");
  } else {
      statCard.classList.add("hidden");
      grid.classList.remove("mode-grid--composer");
  }

  document.querySelectorAll(".mode-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if(e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      
      const mode = card.dataset.mode;
      
      if(mode === "stats") {
          showView("#view-composer");
          initComposerDashboard();
      } else {
          // Se cambio modalità, resetto la volontà di ripristino
          explicitRestore = false;
          state.mode = mode;
          applyTheme();
          syncWelcomeModeRadios();
      }
    });
  });
  
  const statsBtn = $("#statsConfirmBtn");
  if(statsBtn) {
      statsBtn.onclick = (e) => {
          e.stopPropagation(); 
          showView("#view-composer");
          initComposerDashboard();
      };
  }

  const goToSession = () => {
    hydrateSessionHeader();
    showView("#view-session");
  };

  // --- NUOVA LOGICA TASTO INDIETRO (PAGE 2 -> PAGE 1) ---
  const btnBackRoles = $("#btn-back-roles");
  if(btnBackRoles) {
      btnBackRoles.onclick = () => {
          // Reset completo stato
          state.role = null;
          state.mode = null;
          explicitRestore = false;
          
          hoveredRole = null;
          pendingRole = null;

          showView("#view-roles");
      };
  }

  $("#artistConfirmBtn").onclick = (e) => {
    e.preventDefault();
    const name = $("#artistInput").value.trim();
    if (!name) return alert("Inserisci nome artista");
    state.concertArtist = name;
    saveStateToLocal();
    goToSession();
  };

  $("#bandConfirmBtn").onclick = (e) => {
    e.preventDefault();
    state.bandArtist = $("#bandArtistInput") ? $("#bandArtistInput").value.trim() : "";
    saveStateToLocal();
    goToSession();
  };

  // --- NUOVA LOGICA DI RIPRISTINO MANUALE ---
  const btnRestore = $("#btn-manual-restore");
  if(btnRestore) {
      btnRestore.onclick = async (e) => {
          e.preventDefault();
          try {
              const res = await fetch("/api/get_playlist");
              if (!res.ok) throw new Error("Errore API");
              const data = await res.json();
              
              if (!data.playlist || data.playlist.length === 0) {
                   alert("Nessuna sessione interrotta trovata");
                   return;
              }

              // Se troviamo dati, proviamo a recuperare il contesto da localStorage
              const savedMode = localStorage.getItem("appMode");
              if (savedMode) {
                   state.mode = savedMode;
                   state.concertArtist = localStorage.getItem("concertArtist") || "";
                   state.bandArtist = localStorage.getItem("bandArtist") || "";
                   
                   // IMPORTANTE: Impostiamo il flag per dire "ok, stiamo ripristinando, non cancellare"
                   explicitRestore = true;

                   // Avvia direttamente la sessione recuperata
                   sessionStart();
              } else {
                   alert("Dati sessione trovati, ma impossibile determinare la modalità precedente. Riavviare una nuova sessione");
              }
          } catch(err) {
              console.error(err);
              alert("Errore durante il controllo della sessione");
          }
      };
  }
}

// === NUOVA FUNZIONE PER GESTIRE I DOWNLOAD EXPORT ===
// Questa funzione chiama l'endpoint unico /api/generate_report configurando correttamente il formato
async function downloadExport(uiType) {
  // MODIFICA IMPORTANTE: Se il tipo è 'raw', inviamo TUTTI i brani, anche i cancellati.
  // Per Excel e PDF Ufficiale, inviamo solo gli attivi.
  let songsPayload = songs;
  
  if (uiType !== 'raw') {
      songsPayload = songs.filter(s => !s.is_deleted);
  }

  if (!songsPayload.length) return alert("Nessun dato da esportare.");

  // Mappatura tipo UI -> formato Backend (app.py)
  let backendFormat = "excel";
  if (uiType === 'pdf') backendFormat = "pdf_official";
  else if (uiType === 'raw') backendFormat = "pdf_raw";
  
  // Dati da inviare al backend per generare il report
  const payload = {
      songs: songsPayload, 
      mode: state.mode || "session",
      artist: (state.mode === 'concert' ? state.concertArtist : state.bandArtist) || "Sconosciuto",
      format: backendFormat 
  };

  try {
      const btn = $(`#btn-export-${uiType}`);
      const originalText = btn.textContent;
      btn.textContent = "Generazione...";
      btn.disabled = true;

      // Endpoint confermato da app.py
      const res = await fetch("/api/generate_report", { 
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error("Errore durante l'export");

      // Gestione download blob
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      // Estensione file corretta
      const ext = (backendFormat === 'excel') ? 'xlsx' : 'pdf';
      a.download = `borderò_${backendFormat}_${Date.now()}.${ext}`;
      
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      btn.textContent = originalText;
      btn.disabled = false;
      $("#export-modal").classList.add("modal--hidden");

  } catch (err) {
      console.error(err);
      alert("Errore export: " + err.message);
      // Ripristina stato bottone
      const btn = $(`#btn-export-${uiType}`);
      if(btn) {
          btn.textContent = (uiType === 'excel' ? 'Excel (SIAE)' : (uiType === 'pdf' ? 'PDF Ufficiale' : 'Log Tecnico'));
          btn.disabled = false;
      }
  }
}
// ====================================================

function wireSessionButtons() {
  $("#btn-session-start").onclick = (e) => { e.preventDefault(); sessionStart(); };
  
  $("#btn-session-pause").onclick = (e) => { 
      e.preventDefault(); 
      sessionPause(); 
      const led = $(".led-rect");
      if(led) led.classList.add("led-paused");
  };
  
  $("#btn-session-stop").onclick = async (e) => { 
    e.preventDefault(); 
    
    const led = $(".led-rect");
    if(led) led.classList.add("led-paused");

    const confirmed = await showConfirm("Vuoi davvero stoppare la sessione?");

    if(confirmed) {
        sessionStop(); 
    } else {
        const btnStart = $("#btn-session-start");
        if (btnStart && btnStart.disabled) {
             if(led) led.classList.remove("led-paused");
        } 
    }
  };

  $("#btn-session-reset").onclick = async (e) => {
    e.preventDefault();
    if(await showConfirm("Resettare tutto?")) sessionReset();
  };
  
  $("#btn-undo").onclick = (e) => { e.preventDefault(); undoLast(); };
  
  const btnBackReview = $("#btn-back-review");
  if(btnBackReview) {
      btnBackReview.onclick = () => showView("#view-review");
  }

  const btnConfirmRev = $("#btn-confirm-revenue");
  if(btnConfirmRev) {
      btnConfirmRev.onclick = () => {
          const inp = $("#session-revenue-input");
          const val = parseFloat(inp.value);
          if(isNaN(val) || val <= 0) {
              alert("Inserisci un importo valido per iniziare");
              return;
          }
          state.orgRevenue = val;
          state.orgRevenueConfirmed = true;
          hydrateSessionHeader(); 
      };
  }

  $("#btn-session-notes").onclick = () => openNotesModal("session");
  $("#btn-review-notes").onclick = () => openNotesModal("review");
  
  $("#notes-cancel").onclick = () => closeNotesModal(false);
  $("#notes-save").onclick = () => closeNotesModal(true);
  
  const btnGenerate = $("#btn-generate");
  const exportModal = $("#export-modal");
  
  if (btnGenerate) {
      btnGenerate.onclick = (e) => {
          e.preventDefault();
          const activeSongs = songs.filter(s => !s.is_deleted);
          if(activeSongs.length === 0) return alert("Nessun brano attivo");
          exportModal.classList.remove("modal--hidden");
      };
  }

  $("#btn-export-close").onclick = () => exportModal.classList.add("modal--hidden");

  // === AGGIUNTA EVENTI BOTTONI EXPORT ===
  // Colleghiamo i pulsanti del modale alla funzione downloadExport corretta
  $("#btn-export-excel").onclick = () => downloadExport("excel");
  $("#btn-export-pdf").onclick = () => downloadExport("pdf");
  $("#btn-export-raw").onclick = () => downloadExport("raw");
  // ======================================
}

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
  if(ctx === "review") {
    ta.readOnly = true;
    save.classList.add("hidden");
  } else {
    ta.readOnly = false;
    save.classList.remove("hidden");
  }
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

// ============================================================================
// ANIMAZIONE PALCO (JS PHYSICS - Page 1 & Global)
// ============================================================================

const lightsState = [
    { 
        id: 'left', // User
        role: 'user',
        vertex: { x: 250, y: 150 }, 
        baseY: 680,
        originalBaseX: 250,
        originalAmplitude: 150,
        currentAmp: 150,
        currentOp: 0.7,
        phase: 0,
        speed: 0.8,
        rx: 160
    },
    { 
        id: 'center', // Org
        role: 'org',
        vertex: { x: 600, y: 150 }, 
        baseY: 720,
        originalBaseX: 600,
        originalAmplitude: 180,
        currentAmp: 180,
        currentOp: 1.0, 
        phase: 2,
        speed: 0.6,
        rx: 160
    },
    { 
        id: 'right', // Composer
        role: 'composer',
        vertex: { x: 950, y: 150 }, 
        baseY: 680,
        originalBaseX: 950,
        originalAmplitude: 150,
        currentAmp: 150,
        currentOp: 0.7,
        phase: 4,
        speed: 0.75,
        rx: 160
    }
];

const globalLightsState = [
    { id: 'gl-beam-tl', vertex: { x: 0, y: 0 },      baseY: 800, baseX: 500,  amp: 120, phase: 0, speed: 0.52 },
    { id: 'gl-beam-tr', vertex: { x: 1920, y: 0 },    baseY: 800, baseX: 1420, amp: 120, phase: 2, speed: 0.46 },
    { id: 'gl-beam-bl', vertex: { x: 0, y: 1080 },    baseY: 280, baseX: 500,  amp: 100, phase: 1, speed: 0.40 },
    { id: 'gl-beam-br', vertex: { x: 1920, y: 1080 }, baseY: 280, baseX: 1420, amp: 100, phase: 3, speed: 0.52 }
];

function animateStageLights() {
    const time = Date.now() * 0.00195;
    
    // --- MODIFICA: Logica statica vs dinamica per Page 3 vs Page 4 ---
    const isReviewMode = state.route === 'review';

    lightsState.forEach(light => {
        const beam = document.getElementById(`beam-${light.id}`);
        const spot = document.getElementById(`spot-${light.id}`);
        const group = document.querySelector(`.spotlight-group[data-role="${light.role}"]`);
        const maskPath = document.getElementById(`mask-path-${light.id}`);

        if (!beam || !spot || !group) return;

        let targetAmp = light.originalAmplitude;
        let targetOp = (light.id === 'center') ? 1.0 : 0.7; 

        // MODIFICA QUI: Aggiunto pendingRole (modal open) alla logica di priorità
        let targetRole = state.role || pendingRole || hoveredRole;

        if (targetRole) {
            targetAmp = 0; 
            if (targetRole === light.role) {
                targetOp = (light.id === 'center') ? 1.0 : 0.7;
            } else {
                targetOp = 0.0;
            }
        }

        light.currentAmp = lerp(light.currentAmp, targetAmp, 0.05);
        light.currentOp = lerp(light.currentOp, targetOp, 0.05);

        group.style.opacity = light.currentOp.toFixed(3);

        const sway = Math.sin(time * light.speed + light.phase);
        const offsetX = sway * light.currentAmp;
        
        const currentX = light.originalBaseX + offsetX;
        const currentRx = light.rx;

        spot.setAttribute('cx', currentX);
        spot.setAttribute('rx', currentRx);

        const xLeft = currentX - currentRx;
        const xRight = currentX + currentRx;
        const curveDepth = 40; 
        
        const d = `M${light.vertex.x},${light.vertex.y} L${xLeft},${light.baseY} Q${currentX},${light.baseY + curveDepth} ${xRight},${light.baseY} Z`;

        beam.setAttribute('d', d);
        if(maskPath) maskPath.setAttribute('d', d);
    });

    // GESTIONE LUCI GLOBALI (4 Angoli)
    globalLightsState.forEach(gl => {
        const beam = document.getElementById(gl.id);
        if(!beam) return;

        let currentX;
        
        if (isReviewMode) {
            // Coordinate statiche per Review Mode
            if (gl.id === 'gl-beam-tl') currentX = 380;   // Top Left
            else if (gl.id === 'gl-beam-tr') currentX = 1540; // Top Right (1920 - 380)
            else if (gl.id === 'gl-beam-bl') currentX = 600;  // Bottom Left
            else if (gl.id === 'gl-beam-br') currentX = 1320; // Bottom Right
        } else {
            // Oscillazione standard per Session Mode
            const sway = Math.sin(time * gl.speed + gl.phase);
            currentX = gl.baseX + (sway * gl.amp);
        }
        
        const width = 190; 
        const xLeft = currentX - width;
        const xRight = currentX + width;
        
        const d = `M${gl.vertex.x},${gl.vertex.y} L${xLeft},${gl.baseY} L${xRight},${gl.baseY} Z`;
        beam.setAttribute('d', d);
    });

    requestAnimationFrame(animateStageLights);
}

// --- BOOTSTRAP ---
document.addEventListener("DOMContentLoaded", () => {
  const app = document.getElementById("app");
  const isViewer = app.dataset.viewer === "true";

  wireSessionButtons();

  animateStageLights();

  if (isViewer) {
    showView("#view-session");
    hydrateSessionHeader();
    startPlaylistPolling();
    const rm = document.getElementById("restore-modal");
    if(rm) rm.classList.add("modal--hidden");
  } else {
    initRoleSelection();
    initGlobalPayments();
    showView("#view-roles");
    syncReviewNotes();
  }
});