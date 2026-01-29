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
let notesModalContext = "session";

// Gestione Hover Luci (Page 1)
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

// --- NAVIGAZIONE ---
function setRoute(route) {
  state.route = route;
  const body = document.body;
  if (body) {
    // IMPORTANTE: Imposta attributo su body per gestire visibilità luci globali via CSS
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
// GESTIONE RUOLI (PAGINA 0 - SVG INTERACTION)
// ============================================================================
function initRoleSelection() {
  const roleSpots = document.querySelectorAll(".spotlight-group");
  const modalRevenue = $("#revenue-modal");
  const inputRevenue = $("#revenue-input");
  const btnRevConfirm = $("#revenue-confirm");
  const btnRevCancel = $("#revenue-cancel");
  const backBtn = $("#btn-back-roles");

  roleSpots.forEach(spot => {
    spot.addEventListener("mouseenter", () => {
      hoveredRole = spot.dataset.role;
    });
    spot.addEventListener("mouseleave", () => {
      hoveredRole = null;
    });
    spot.addEventListener("click", () => {
      const role = spot.dataset.role;
      state.role = role;
      if (role === "composer") {
        showView("#view-composer");
        initComposerDashboard();
      } else if (role === "org") {
        modalRevenue.classList.remove("modal--hidden");
      } else {
        showView("#view-welcome");
        initWelcome();
      }
    });
  });

  if(btnRevConfirm) {
    btnRevConfirm.onclick = () => {
      const val = parseFloat(inputRevenue.value);
      if(isNaN(val) || val < 0) return alert("Inserisci un importo valido");
      state.orgRevenue = val;
      modalRevenue.classList.add("modal--hidden");
      const badgeRev = $("#org-revenue-badge");
      if(badgeRev) {
        badgeRev.textContent = `Incasso: ${formatMoney(state.orgRevenue)}`;
        badgeRev.classList.remove("hidden");
      }
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

  if(backBtn) {
    backBtn.onclick = () => {
      showView("#view-roles");
      state.role = null;
      state.orgRevenue = 0;
      const br = $("#org-revenue-badge");
      if(br) br.classList.add("hidden");
    };
  }
  
  const logoutComp = $("#btn-comp-logout");
  if(logoutComp) {
    logoutComp.onclick = () => showView("#view-roles");
  }
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
// LOGICA ORIGINALE (POLLING, SESSIONE)
// ============================================================================

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
          confirmed: false
        };
        songs.push(track);

        if (!isDeleted && id > lastMaxSongId) {
            currentSongId = track.id;
            setNow(track.title, track.composer);
            pushLog({ id: track.id, index: track.order, title: track.title, composer: track.composer, artist: track.artist, cover: track.cover });
        }
      } else {
        if (!existing.confirmed) {
            existing.title = song.title || existing.title;
            existing.composer = song.composer || existing.composer;
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
  
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
  
  if (btnStart) btnStart.disabled = false;
  if (btnPause) btnPause.disabled = true;
  if (btnStop) btnStop.disabled = true;
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
    if (state.role === "org") {
        btn24.classList.remove("hidden");
        btn24.onclick = () => { openRoyaltiesView(song); };
    }

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
  if(btnPayments) btnPayments.disabled = !enableGlobalActions;

  updateUndoButton();
  syncReviewNotes();
}

function openRoyaltiesView(song) {
    state.currentRoyaltySong = song;
    showView("#view-royalties");
    
    $("#roy-song-title").textContent = song.title;
    $("#roy-total-revenue").textContent = formatMoney(state.orgRevenue);
    
    const activeSongs = songs.filter(s => !s.is_deleted);
    const songValue = (state.orgRevenue * 0.10) / (activeSongs.length || 1);
    
    $("#roy-song-value").textContent = formatMoney(songValue);
    
    const compList = $("#roy-composers-list");
    compList.innerHTML = "";
    
    const composers = (song.composer && song.composer !== "—") ? song.composer.split(",").map(c => c.trim()) : ["Mario Rossi", "Giuseppe Verdi"];
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
            <span>(Incluso)</span>
        `;
        
        compList.appendChild(row);
    });
}

function initGlobalPayments() {
  const btnPayments = $("#btn-global-payments");
  const btnBack = $("#btn-back-from-payments");
  
  if(btnPayments) {
    btnPayments.onclick = () => {
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

  // Palette di colori distinti per il grafico a torta
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
      
      // Assegna un colore distinto dalla palette
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

    if (state.mode === "dj") {
      $("#djConfirmWrapper").classList.add("visible");
    } else if (state.mode === "band") {
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

  document.querySelectorAll(".mode-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if(e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      state.mode = card.dataset.mode;
      applyTheme();
      syncWelcomeModeRadios();
    });
  });

  const goToSession = () => {
    hydrateSessionHeader();
    showView("#view-session");
  };

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

  $("#djConfirmBtn").onclick = (e) => {
    e.preventDefault();
    state.concertArtist = "";
    state.bandArtist = "";
    saveStateToLocal();
    goToSession();
  };
}

function wireSessionButtons() {
  $("#btn-session-start").onclick = (e) => { e.preventDefault(); sessionStart(); };
  $("#btn-session-pause").onclick = (e) => { e.preventDefault(); sessionPause(); };
  $("#btn-session-stop").onclick = async (e) => { 
    e.preventDefault(); 
    if(await showConfirm("Passare alla review?")) sessionStop(); 
  };
  $("#btn-session-reset").onclick = async (e) => {
    e.preventDefault();
    if(await showConfirm("Resettare tutto?")) sessionReset();
  };
  
  $("#btn-undo").onclick = (e) => { e.preventDefault(); undoLast(); };
  
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
          if(activeSongs.length === 0) return alert("Nessun brano attivo.");
          exportModal.classList.remove("modal--hidden");
      };
  }

  $("#btn-export-close").onclick = () => exportModal.classList.add("modal--hidden");
}

async function checkRestoreSession() {
  try {
    const res = await fetch("/api/get_playlist");
    if (!res.ok) return;
    const data = await res.json();
    if (!data.playlist || data.playlist.length === 0) return;

    const modal = document.getElementById("restore-modal");
    modal.classList.remove("modal--hidden");

    document.getElementById("restore-new").onclick = async () => {
      await fetch("/api/reset_session", { method: "POST" });
      modal.classList.add("modal--hidden");
      songs = [];
    };

    document.getElementById("restore-ok").onclick = () => {
      modal.classList.add("modal--hidden");
      const savedMode = localStorage.getItem("appMode");
      if (savedMode) {
        state.mode = savedMode;
        state.concertArtist = localStorage.getItem("concertArtist") || "";
        state.bandArtist = localStorage.getItem("bandArtist") || "";
        sessionStart();
      }
    };
  } catch (err) { console.error(err); }
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
// ANIMAZIONE PALCO (JS PHYSICS - Page 1) - SVG Interaction
// ============================================================================
const lightsState = [
    { 
        id: 'left', // User
        role: 'user',
        vertex: { x: 250, y: -150 },
        baseY: 540,
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
        vertex: { x: 600, y: -150 },
        baseY: 580,
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
        vertex: { x: 950, y: -150 },
        baseY: 540,
        originalBaseX: 950,
        originalAmplitude: 150,
        currentAmp: 150,
        currentOp: 0.7,
        phase: 4,
        speed: 0.75,
        rx: 160
    }
];

function animateStageLights() {
    const time = Date.now() * 0.00195;

    lightsState.forEach(light => {
        const beam = document.getElementById(`beam-${light.id}`);
        const spot = document.getElementById(`spot-${light.id}`);
        const group = document.querySelector(`.spotlight-group[data-role="${light.role}"]`);
        const maskPath = document.getElementById(`mask-path-${light.id}`);

        if (!beam || !spot || !group) return;

        // 1. Calcolo Target Ampiezza & Target Opacità basato su Hover
        let targetAmp = light.originalAmplitude;
        let targetOp = (light.id === 'center') ? 1.0 : 0.7; // Default base

        if (hoveredRole) {
            // Se c'è un hover attivo, TUTTI si fermano (targetAmp = 0)
            targetAmp = 0;

            if (hoveredRole === light.role) {
                targetOp = (light.id === 'center') ? 1.0 : 0.7;
            } else {
                targetOp = 0.0;
            }
        }

        // 2. Interpolazione (Lerp) per movimento fluido
        light.currentAmp = lerp(light.currentAmp, targetAmp, 0.05);
        light.currentOp = lerp(light.currentOp, targetOp, 0.05);

        // Applica Opacità al gruppo
        group.style.opacity = light.currentOp.toFixed(3);

        // 3. Calcolo Posizione Fisica
        const sway = Math.sin(time * light.speed + light.phase);
        const offsetX = sway * light.currentAmp;
        
        const currentX = light.originalBaseX + offsetX;
        const currentRx = light.rx;

        // Aggiorna cerchio a terra
        spot.setAttribute('cx', currentX);
        spot.setAttribute('rx', currentRx);

        // 4. Costruisco il path del fascio
        const xLeft = currentX - currentRx;
        const xRight = currentX + currentRx;
        const curveDepth = 40; 
        
        const d = `M${light.vertex.x},${light.vertex.y} L${xLeft},${light.baseY} Q${currentX},${light.baseY + curveDepth} ${xRight},${light.baseY} Z`;

        beam.setAttribute('d', d);
        if(maskPath) maskPath.setAttribute('d', d);
    });

    requestAnimationFrame(animateStageLights);
}

// --- BOOTSTRAP ---
document.addEventListener("DOMContentLoaded", () => {
  const app = document.getElementById("app");
  const isViewer = app.dataset.viewer === "true";

  wireSessionButtons();

  // AVVIO ANIMAZIONE LUCI PAGE 1
  animateStageLights();

  if (isViewer) {
    showView("#view-session");
    hydrateSessionHeader();
    startPlaylistPolling();
    const rm = document.getElementById("restore-modal");
    if(rm) rm.classList.add("modal--hidden");
  } else {
    // Admin: Inizia da Scelta Ruolo (Page 0)
    initRoleSelection();
    initGlobalPayments();
    showView("#view-roles");
    
    checkRestoreSession();
    syncReviewNotes();
  }
});