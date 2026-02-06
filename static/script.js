// --- 1. CONFIGURAZIONE FIREBASE ---
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
let explicitRestore = false;

let playlistPollInterval = null;
let sessionStartMs = 0;
let sessionAccumulatedMs = 0;
let sessionTick = null;

let undoStack = [];
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

// --- CUSTOM ALERT FUNCTION (Dal Collega) ---
function showCustomAlert(msg) {
    const m = $("#alert-modal");
    if (!m) { alert(msg); return; } // Fallback se non esiste il modale nel DOM
    $("#alert-message").textContent = msg;
    m.classList.remove("modal--hidden");
    const btn = $("#alert-ok");
    // Clone per rimuovere vecchi event listener
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.onclick = () => { m.classList.add("modal--hidden"); };
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
    if (["welcome", "session", "roles", "register"].includes(route)) body.classList.add("no-scroll");
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
// GESTIONE RUOLI & AUTH (MERGED: Collega Logic + Fix ID)
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
      btnCompBack.onclick = () => showView("#view-welcome");
  }
  
  roleSpots.forEach(spot => {
    spot.addEventListener("mouseenter", () => { hoveredRole = spot.dataset.role; });
    spot.addEventListener("mouseleave", () => { hoveredRole = null; });
    spot.addEventListener("click", () => {
      const role = spot.dataset.role;
      pendingRole = role; 
      // FIX ID: Il collega usava auth-user-email, ma l'HTML è auth-email
      if($("#auth-email")) $("#auth-email").value = "";
      if($("#auth-pass")) $("#auth-pass").value = "";
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
        // FIX ID qui
        const identifier = $("#auth-email").value.trim();
        const pass = $("#auth-pass").value.trim();
        
        if(!identifier || !pass) return showCustomAlert("Inserisci email/username e password");
        if(!pendingRole) return showCustomAlert("Errore ruolo non selezionato");

        try {
            btnLogin.textContent = "Verifica...";
            btnLogin.disabled = true;

            const res = await fetch("/api/login", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    username: identifier, // Backend gestisce Username o Email
                    password: pass,
                    role: pendingRole 
                })
            });
            const data = await res.json();

            if(data.success) {
                completeAuth(); 
            } else {
                showCustomAlert(data.error); 
            }
        } catch(e) {
            console.error(e);
            showCustomAlert("Errore server login");
        } finally {
            btnLogin.textContent = "Accedi";
            btnLogin.disabled = false;
        }
    };
  }

  if (btnGuest) btnGuest.onclick = () => completeAuth();

  if (linkRegister) {
    linkRegister.onclick = (e) => {
        e.preventDefault();
        $("#auth-modal").classList.add("modal--hidden");
        showView("#view-register");
    };
  }
}

function initRegistration() {
    const btnReg = $("#btn-do-register");
    const btnCancel = $("#btn-cancel-register");
    const roleSelect = $("#reg-role");
    const stageNameWrapper = $("#reg-stage-name-wrapper");

    // Gestione visualizzazione campo Stage Name
    if(roleSelect) {
        roleSelect.addEventListener("change", () => {
            if(roleSelect.value === "composer") {
                stageNameWrapper.classList.remove("hidden");
            } else {
                stageNameWrapper.classList.add("hidden");
                $("#reg-stage-name").value = ""; 
            }
        });
    }

    if(btnCancel) {
        btnCancel.onclick = () => showView("#view-roles");
    }

    if(btnReg) {
        btnReg.onclick = async () => {
            const payload = {
                nome: $("#reg-name").value.trim(),
                cognome: $("#reg-surname").value.trim(),
                email: $("#reg-email").value.trim(),
                username: $("#reg-username").value.trim(),
                password: $("#reg-pass").value.trim(),
                birthdate: $("#reg-birthdate").value,
                role: $("#reg-role").value,
                stage_name: $("#reg-stage-name").value.trim()
            };

            if(!payload.username || !payload.password || !payload.role || !payload.email) {
                return showCustomAlert("Compila tutti i campi obbligatori");
            }

            try {
                btnReg.textContent = "Registrazione...";
                btnReg.disabled = true;

                const res = await fetch("/api/register", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify(payload)
                });
                const data = await res.json();

                if(data.success) {
                    showCustomAlert("Registrazione avvenuta con successo! Ora puoi accedere.");
                    showView("#view-roles");
                } else {
                    showCustomAlert("Errore: " + data.error);
                }
            } catch(e) {
                console.error(e);
                showCustomAlert("Errore di connessione");
            } finally {
                btnReg.textContent = "Registrati";
                btnReg.disabled = false;
            }
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
        responsive: true, maintainAspectRatio: false,
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
              btnStart.setAttribute("data-tooltip", "Indicare l'incasso dell'evento prima di avviare la sessione");
          }
      } else {
          revInputContainer.classList.add("hidden");
          revDisplay.classList.remove("hidden");
          revDisplay.textContent = `Incasso: ${formatMoney(state.orgRevenue)}`;
          if(btnStart) {
              btnStart.disabled = false;
              btnStart.removeAttribute("data-tooltip");
          }
      }
  } else {
      revInputContainer.classList.add("hidden");
      revDisplay.classList.add("hidden");
      if(btnStart) {
          btnStart.disabled = false;
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

  if (!explicitRestore) {
      try {
          await fetch("/api/reset_session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
          songs = [];
          $("#live-log").innerHTML = "";
      } catch (err) { console.error(err); }
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
  if(led) { led.classList.add("led-paused"); }
  
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
  if(led) { led.classList.add("led-paused"); }

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
  explicitRestore = false; 

  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  
  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = true;

  const led = $(".led-rect");
  if(led) {
      led.classList.add("led-fading-out");
      setTimeout(() => {
          led.classList.remove("led-active", "led-paused", "led-fading-out");
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
    
    if(boxRevenue) {
        if(isOrg) {
            boxRevenue.classList.remove("hidden");
            $("#roy-total-revenue").textContent = formatMoney(state.orgRevenue);
        } else {
            boxRevenue.classList.add("hidden");
        }
    }
    
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
  if(btnBack) btnBack.onclick = () => showView("#view-review");
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
  let chartLabels = [], chartData = [], chartColors = [];
  const palette = ["#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40", "#C9CBCF", "#FFCD56", "#E7E9ED", "#76D7C4", "#1E8449", "#F1948A"];

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
        data: data, backgroundColor: colors, borderColor: '#12151a', borderWidth: 2
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'right', labels: { color: '#e6eef8', font: { size: 11 } } } }
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

  const btnBackRoles = $("#btn-back-roles");
  if(btnBackRoles) {
      btnBackRoles.onclick = () => {
          state.role = null; state.mode = null; explicitRestore = false;
          hoveredRole = null; pendingRole = null;
          showView("#view-roles");
      };
  }

  // --- REINSERIMENTO PREFETCH (TUA LOGICA) ---
  const triggerBackendPrefetch = (artistName) => {
      if (!artistName) return;
      console.log("🚀 Avvio prefetch dati per:", artistName);
      // Chiamata "fire and forget"
      fetch("/api/prepare_session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ targetArtist: artistName })
      }).catch(err => console.warn("Errore prefetch:", err));
  };

  $("#artistConfirmBtn").onclick = (e) => {
    e.preventDefault();
    const name = $("#artistInput").value.trim();
    if (!name) return showCustomAlert("Inserisci nome artista");
    
    state.concertArtist = name;
    saveStateToLocal();
    
    // Attivo Prefetch
    triggerBackendPrefetch(name);
    
    goToSession();
  };

  $("#bandConfirmBtn").onclick = (e) => {
    e.preventDefault();
    const name = $("#bandArtistInput") ? $("#bandArtistInput").value.trim() : "";
    
    state.bandArtist = name;
    saveStateToLocal();
    
    // Attivo Prefetch
    triggerBackendPrefetch(name);
    
    goToSession();
  };

  const btnRestore = $("#btn-manual-restore");
  if(btnRestore) {
      btnRestore.onclick = async (e) => {
          e.preventDefault();
          const originalText = btnRestore.innerHTML;
          btnRestore.innerHTML = "Recupero...";
          btnRestore.disabled = true;

          try {
              // 1. Chiediamo al backend di ripescare i dati dal DB
              const resRecover = await fetch("/api/recover_session", { 
                  method: "POST" 
              });
              const dataRecover = await resRecover.json();

              if (!dataRecover.success) {
                  throw new Error(dataRecover.message || "Nessuna sessione trovata");
              }

              // 2. Se il backend ha ripristinato i dati, ora possiamo scaricarli
              const resPlaylist = await fetch("/api/get_playlist");
              if (!resPlaylist.ok) throw new Error("Errore nel download playlist");
              const dataPlaylist = await resPlaylist.json();
              
              if (!dataPlaylist.playlist || dataPlaylist.playlist.length === 0) {
                    throw new Error("Sessione vuota");
              }

              showCustomAlert(`Bentornato! Recuperati ${dataPlaylist.playlist.length} brani.`);

              // 3. Cerchiamo di ripristinare la modalità (Local Storage)
              // Se non c'è nel local storage, defaultiamo a "Band" per sicurezza
              const savedMode = localStorage.getItem("appMode");
              if (savedMode) {
                    state.mode = savedMode;
                    state.concertArtist = localStorage.getItem("concertArtist") || "";
                    state.bandArtist = localStorage.getItem("bandArtist") || "";
              } else {
                    // Fallback se l'utente ha cambiato browser
                    state.mode = "band"; 
              }
              
              // 4. Avviamo la sessione visuale
              explicitRestore = true;
              // Passiamo 'true' a sessionStart se vogliamo evitare che resetti di nuovo il DB
              // (Nota: sessionStart nel tuo codice attuale fa un reset_session se explicitRestore è false.
              // Avendo settato explicitRestore = true qui sopra, i dati non verranno cancellati).
              sessionStart();

          } catch(err) {
              console.warn(err);
              showCustomAlert(err.message);
          } finally {
              btnRestore.innerHTML = originalText;
              btnRestore.disabled = false;
          }
      };
  }
}

async function downloadExport(uiType) {
  let songsPayload = songs;
  if (uiType !== 'raw') {
      songsPayload = songs.filter(s => !s.is_deleted);
  }

  if (!songsPayload.length) return showCustomAlert("Nessun dato da esportare.");

  let backendFormat = "excel";
  if (uiType === 'pdf') backendFormat = "pdf_official";
  else if (uiType === 'raw') backendFormat = "pdf_raw";
  
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

      const res = await fetch("/api/generate_report", { 
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error("Errore durante l'export");

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
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
      showCustomAlert("Errore export: " + err.message);
      const btn = $(`#btn-export-${uiType}`);
      if(btn) {
          btn.textContent = (uiType === 'excel' ? 'Excel (SIAE)' : (uiType === 'pdf' ? 'PDF Ufficiale' : 'Log Tecnico'));
          btn.disabled = false;
      }
  }
}

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
    if(confirmed) { sessionStop(); } else {
        const btnStart = $("#btn-session-start");
        if (btnStart && btnStart.disabled) { if(led) led.classList.remove("led-paused"); } 
    }
  };

  $("#btn-session-reset").onclick = async (e) => {
    e.preventDefault();
    if(await showConfirm("Resettare tutto?")) sessionReset();
  };
  
  $("#btn-undo").onclick = (e) => { e.preventDefault(); undoLast(); };
  
  const btnBackReview = $("#btn-back-review");
  if(btnBackReview) { btnBackReview.onclick = () => showView("#view-review"); }

  const btnConfirmRev = $("#btn-confirm-revenue");
  if(btnConfirmRev) {
      btnConfirmRev.onclick = () => {
          const inp = $("#session-revenue-input");
          const val = parseFloat(inp.value);
          if(isNaN(val) || val <= 0) {
              showCustomAlert("Inserisci un importo valido per iniziare");
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
          if(activeSongs.length === 0) return showCustomAlert("Nessun brano attivo");
          exportModal.classList.remove("modal--hidden");
      };
  }

  $("#btn-export-close").onclick = () => exportModal.classList.add("modal--hidden");

  $("#btn-export-excel").onclick = () => downloadExport("excel");
  $("#btn-export-pdf").onclick = () => downloadExport("pdf");
  $("#btn-export-raw").onclick = () => downloadExport("raw");
  
  const btnQr = $("#btn-show-qr");
  const qrModal = $("#qr-modal");
  const qrImage = $("#qr-image");
  const qrClose = $("#qr-close");

  if (btnQr && qrModal) {
      btnQr.onclick = () => {
          qrImage.src = `/api/get_qr_image?t=${Date.now()}`;
          qrModal.classList.remove("modal--hidden");
      };
      qrClose.onclick = () => { qrModal.classList.add("modal--hidden"); };
  }
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
// ANIMAZIONE PALCO (JS PHYSICS)
// ============================================================================
const lightsState = [
    { id: 'left', role: 'user', vertex: { x: 250, y: 150 }, baseY: 680, originalBaseX: 250, originalAmplitude: 150, currentAmp: 150, currentOp: 0.7, phase: 0, speed: 0.8, rx: 160 },
    { id: 'center', role: 'org', vertex: { x: 600, y: 150 }, baseY: 720, originalBaseX: 600, originalAmplitude: 180, currentAmp: 180, currentOp: 1.0, phase: 2, speed: 0.6, rx: 160 },
    { id: 'right', role: 'composer', vertex: { x: 950, y: 150 }, baseY: 680, originalBaseX: 950, originalAmplitude: 150, currentAmp: 150, currentOp: 0.7, phase: 4, speed: 0.75, rx: 160 }
];

const globalLightsState = [
    { id: 'gl-beam-tl', vertex: { x: 0, y: 0 }, baseY: 800, baseX: 500, amp: 120, phase: 0, speed: 0.52 },
    { id: 'gl-beam-tr', vertex: { x: 1920, y: 0 }, baseY: 800, baseX: 1420, amp: 120, phase: 2, speed: 0.46 },
    { id: 'gl-beam-bl', vertex: { x: 0, y: 1080 }, baseY: 280, baseX: 500, amp: 100, phase: 1, speed: 0.40 },
    { id: 'gl-beam-br', vertex: { x: 1920, y: 1080 }, baseY: 280, baseX: 1420, amp: 100, phase: 3, speed: 0.52 }
];

function animateStageLights() {
    const time = Date.now() * 0.00195;
    const isReviewMode = state.route === 'review';
    const isRegisterMode = state.route === 'register';

    lightsState.forEach(light => {
        const beam = document.getElementById(`beam-${light.id}`);
        const spot = document.getElementById(`spot-${light.id}`);
        const group = document.querySelector(`.spotlight-group[data-role="${light.role}"]`);
        const maskPath = document.getElementById(`mask-path-${light.id}`);

        if (!beam || !spot || !group) return;

        let targetAmp = light.originalAmplitude;
        let targetOp = (light.id === 'center') ? 1.0 : 0.7; 
        let targetRole = state.role || pendingRole || hoveredRole;

        if (targetRole) {
            targetAmp = 0; 
            if (targetRole === light.role) { targetOp = (light.id === 'center') ? 1.0 : 0.7; } 
            else { targetOp = 0.0; }
        }

        if (isRegisterMode) { targetAmp = 0; targetOp = 1.0; }

        light.currentAmp = lerp(light.currentAmp, targetAmp, 0.05);
        light.currentOp = lerp(light.currentOp, targetOp, 0.05);

        group.style.opacity = light.currentOp.toFixed(3);
        const sway = Math.sin(time * light.speed + light.phase);
        const offsetX = sway * light.currentAmp;
        
        let currentX;
        if (isRegisterMode) { currentX = 600; } else { currentX = light.originalBaseX + offsetX; }
        
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

    globalLightsState.forEach(gl => {
        const beam = document.getElementById(gl.id);
        if(!beam) return;
        let currentX;
        if (isReviewMode) {
            if (gl.id === 'gl-beam-tl') currentX = 380;
            else if (gl.id === 'gl-beam-tr') currentX = 1540;
            else if (gl.id === 'gl-beam-bl') currentX = 600;
            else if (gl.id === 'gl-beam-br') currentX = 1320;
        } else {
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
    initRegistration();
    showView("#view-roles");
    syncReviewNotes();
  }
});