/* CONFIGURAZIONE FIREBASE

   Questa sezione inizializza la connessione con Firebase. 
   Usiamo le librerie "compat" (v8 style) per mantenere la compatibilità 
   con eventuali script legacy presenti nel progetto. (tipo compilatore di
   linguaggio)
 */
const firebaseConfig = {
  apiKey: "AIzaSyDPtkUaiTQSxUB9x7x1xWF9XHdVqBXLb-s",
  authDomain: "actam-project-8f9de.firebaseapp.com",
  projectId: "actam-project-8f9de",
  storageBucket: "actam-project-8f9de.firebasestorage.app",
  messagingSenderId: "116409170757",
  appId: "1:116409170757:web:0b2aba5b9aa133bb15dc2c",
  measurementId: "G-RHPHMPTPDE"
};

// Controllo di sicurezza: se le librerie non sono caricate nell'HTML, avvisa in console.
if (typeof firebase !== 'undefined') {
  firebase.initializeApp(firebaseConfig);
  console.log("🔥 Firebase Client inizializzato!");
} else {
  console.error("❌ Librerie Firebase non trovate. Controlla index.html");
}

/* STATO GLOBALE DELL'APPLICAZIONE (State Management)

   Per evitare ricaricamenti di pagina (SPA simulation), manteniamo tutto lo 
   stato dell'app in questo oggetto 'state'. È la nostra "Single Source of Truth".
 */
const state = {
  role: null,               // Ruolo corrente (user, org, composer)
  orgRevenue: 0,            // Incasso dell'evento (solo per Org)
  orgRevenueConfirmed: false, // Se l'organizzatore ha confermato l'incasso
  currentRoyaltySong: null,// Brano che si sta analizzando nella vista dettagli
  mode: null,               // Modalità sessione: 'band' (generica) o 'concert' (specifica)
  route: "roles",           // Vista attualmente visualizzata nel DOM
  concertArtist: "",        // Nome artista target (modo Concerto)
  // bandArtist rimosso come richiesto
  notes: "",                // Note testuali della sessione
  user: null,               // Oggetto utente completo ricevuto dal backend dopo il login
  stage_name: ""            // Nome d'arte (usato per le query statistiche del compositore)
};

// Variabili di supporto al runtime 
let pendingRole = null;    // Ruolo cliccato dall'utente ma in attesa di login
let songs = [];            // Array locale che contiene la lista dei brani (copia del backend)
let lastMaxSongId = 0;     // ID più alto visto finora (serve a capire se sono arrivati nuovi brani)
let currentSongId = null;  // ID del brano attualmente in riproduzione/rilevamento
let currentCoverUrl = null;// URL della copertina corrente (per aggiornare lo sfondo senza flicker)
let explicitRestore = false;// Flag per impedire il reset automatico quando si recupera una sessione crashata

// Timer e Polling 
let playlistPollInterval = null; // ID dell'intervallo per la richiesta periodica della playlist (polling)
let sessionStartMs = 0;          // Timestamp di inizio sessione (per il cronometro)
let sessionAccumulatedMs = 0;    // Tempo accumulato prima della pausa
let sessionTick = null;          // ID dell'intervallo che aggiorna il timer a schermo

// User Experience e Navigazione
let undoStack = [];        // Stack per gestire la funzione "Annulla" (Ctrl+Z)
let notesModalContext = "session"; // Contesto note: 'session' (editabili) o 'review' (solo lettura)
let hoveredRole = null;    // Serve per l'animazione fisica dei faretti nella home

// Helper per selezionare elementi DOM più velocemente
const $ = (sel) => document.querySelector(sel);

/* FUNZIONI DI UTILITÀ (Helpers)
   
   Funzioni pure per formattazione, matematica e gestione UI generica.
 */

// Aggiunge zero iniziale ai numeri < 10 (es. 9 -> "09")
function pad2(n) { return n.toString().padStart(2, "0"); }

// Converte millisecondi in formato stringa "MM:SS" per il timer
function fmt(ms) {
  const sec = Math.floor(ms / 1000);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${pad2(m)}:${pad2(s)}`;
}

// Formatta un numero come valuta Euro usando le impostazioni locali italiane
function formatMoney(amount, currency = "EUR") {
  return new Intl.NumberFormat('it-IT', { style: 'currency', currency: currency }).format(amount);
}

// Interpolazione Lineare (Linear Interpolation)
// Usata per rendere fluidi i movimenti dei faretti (fisica smorzata)
function lerp(start, end, amt) {
    return (1 - amt) * start + amt * end;
}

// Sostituisce l'alert() nativo del browser con una modale stilizzata HTML
function showCustomAlert(msg) {
    const m = $("#alert-modal");
    if (!m) { alert(msg); return; } // Fallback se il DOM non è pronto
    $("#alert-message").textContent = msg;
    m.classList.remove("modal--hidden");
    const btn = $("#alert-ok");
    // Cloniamo il bottone per rimuovere vecchi event listener ed evitare click multipli
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.onclick = () => { m.classList.add("modal--hidden"); };
}

// Salva lo stato volatile nel LocalStorage del browser.
// Utile se l'utente ricarica la pagina per sbaglio durante una sessione.
function saveStateToLocal() {
  if (!state.mode) return;
  localStorage.setItem("appMode", state.mode);
  if (state.concertArtist) localStorage.setItem("concertArtist", state.concertArtist);
  else localStorage.removeItem("concertArtist");
  // bandArtist rimossa da localStorage
  localStorage.removeItem("bandArtist");
}

/* ROUTING E GESTIONE VISTE (SPA Simulation)
   
   Queste funzioni gestiscono la navigazione simulata nascondendo e mostrando
   sezioni HTML e applicando le classi CSS corrette al body.
 */

// Applica il tema colore corretto (Verde, Rosa, Ciano) in base alla modalità corrente
function applyTheme() {
  const app = document.getElementById("app");
  if (!app) return;
  app.classList.remove("theme-dj", "theme-band", "theme-concert");
  if (state.mode === "band") app.classList.add("theme-band");
  else if (state.mode === "concert") app.classList.add("theme-concert");
  else if (state.mode === "dj") app.classList.add("theme-dj");
}

// Imposta l'attributo data-active-view sul body.
// Il CSS usa questo attributo per decidere se mostrare o nascondere le luci globali.
function setRoute(route) {
  state.route = route;
  const body = document.body;
  if (body) {
    body.setAttribute("data-active-view", route);
    // Blocca lo scroll su viste fisse (es. Home), lo abilita su report lunghi
    if (["welcome", "session", "roles", "register", "profile"].includes(route)) body.classList.add("no-scroll");
    else body.classList.remove("no-scroll");
  }
}

// Funzione principale per cambiare schermata
function showView(id) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("view--active"));
  const el = document.querySelector(id);
  if (el) el.classList.add("view--active");
  const viewName = id.replace("#view-", "");
  setRoute(viewName);
}

/* LOGICA DI AUTENTICAZIONE E SELEZIONE RUOLO
   
   Gestisce l'interazione con i 3 faretti iniziali, l'apertura della modale
   di login e la chiamata alle API di autenticazione.
 */

function initRoleSelection() {
  const roleSpots = document.querySelectorAll(".spotlight-group");
  const authModal = $("#auth-modal");
  const btnLogin = $("#btn-auth-login");
  const btnGuest = $("#btn-auth-guest");
  const linkRegister = $("#link-register");
  const btnCloseAuth = $("#btn-auth-close");
  const btnCompBack = $("#btn-comp-back");
  const app = document.getElementById("app");

  if (btnCompBack) {
      btnCompBack.onclick = () => showView("#view-welcome");
  }
   
  // Listener sui "faretti" (le aree cliccabili SVG)
  roleSpots.forEach(spot => {
    spot.addEventListener("mouseenter", () => { hoveredRole = spot.dataset.role; });
    spot.addEventListener("mouseleave", () => { hoveredRole = null; });
    spot.addEventListener("click", () => {
      const role = spot.dataset.role;
      pendingRole = role;
      
      // Imposta il colore del tema della modale in base al ruolo cliccato
      let themeColor = "var(--c-cyan)"; 
      if (role === "org") themeColor = "var(--c-green)";
      else if (role === "composer") themeColor = "var(--c-pink)";
      
      // Rimuove classi vecchie per evitare conflitti di stile
      app.classList.remove("theme-band", "theme-concert", "theme-dj");
      authModal.style.setProperty("--primary", themeColor);

      // Pulisce i campi input
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

  // Esegue il login chiamando l'API /api/login
  const performLogin = async () => {
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
                    username: identifier,
                    password: pass,
                    role: pendingRole
                })
            });
            const data = await res.json();

            if(data.success) {
                // Login OK: salviamo utente nello stato e procediamo
                state.user = data.user;
                state.stage_name = data.user.stage_name || data.user.username;
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

  if (btnLogin) btnLogin.onclick = performLogin;

  // Supporto tasto Invio nei campi login
  const inputs = [$("#auth-email"), $("#auth-pass")];
  inputs.forEach(input => {
      if(input) {
          input.addEventListener("keyup", (event) => {
              if (event.key === "Enter") {
                  performLogin();
              }
          });
      }
  });

  // Login Ospite (Bypass Database)
  if (btnGuest) btnGuest.onclick = async () => {
      state.user = null;
      state.stage_name = "";
      
      // Resetta la sessione server per sicurezza
      try {
          await fetch("/api/logout", { method: "POST" });
      } catch(e) {
          console.error("Errore logout guest", e);
      }

      completeAuth();
  };

  // Navigazione verso la registrazione
  if (linkRegister) {
    linkRegister.onclick = (e) => {
        e.preventDefault();
        $("#auth-modal").classList.add("modal--hidden");
        showView("#view-register");
    };
  }
}

// Gestione del form di registrazione
function initRegistration() {
    const btnReg = $("#btn-do-register");
    const btnCancel = $("#btn-cancel-register");
    const roleSelect = $("#reg-role");
    const stageNameWrapper = $("#reg-stage-name-wrapper");

    // Mostra il campo "Nome d'arte" solo se si seleziona "Compositore"
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
        btnCancel.onclick = () => {
            pendingRole = null;
            hoveredRole = null;
            showView("#view-roles");
        };
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
                    pendingRole = null;
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

// Finalizza il processo di autenticazione e porta alla Dashboard (page 2)
function completeAuth() {
    const authModal = $("#auth-modal");
    authModal.classList.add("modal--hidden");
    state.role = pendingRole;
    state.orgRevenueConfirmed = false;
    state.orgRevenue = 0;
    showView("#view-welcome");
    initWelcome();
    initUserProfile(); // Inizializza il bottone profilo nell'header
}

/* PROFILO UTENTE E STATISTICHE
   
   Gestisce la visualizzazione dei dati utente, il caricamento asincrono
   delle statistiche e la modifica delle credenziali.
 */

function initUserProfile() {
    const btnProfile = $("#btn-user-profile");
    if(!btnProfile) return;

    // Mostra il pulsante solo se l'utente è loggato (non ospite)
    if(state.user && state.user.username) {
        btnProfile.classList.remove("hidden");
    } else {
        btnProfile.classList.add("hidden");
        return;
    }

    btnProfile.onclick = () => {
        showView("#view-profile");
        populateProfileView();
    };

    const btnBackProfile = $("#btn-profile-back");
    if(btnBackProfile) {
        btnBackProfile.onclick = () => {
            showView("#view-welcome");
        };
    }

    // Gestione Tabs (Stats, History, Settings)
    const tabs = document.querySelectorAll(".tab-btn");
    tabs.forEach(t => {
        t.onclick = () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
            
            t.classList.add("active");
            const target = t.dataset.tab;
            const pane = document.getElementById(`tab-${target}`);
            if(pane) pane.classList.add("active");
        };
    });

    // Salvataggio Modifiche Profilo
    const btnSave = $("#btn-save-profile");
    if(btnSave) {
        btnSave.onclick = async () => {
            const newUsername = $("#edit-username").value.trim();
            const newPassword = $("#edit-password").value.trim();

            if(!newUsername && !newPassword) return showCustomAlert("Nessuna modifica inserita");
            if(newUsername && newUsername.length < 3) return showCustomAlert("Username troppo corto");

            if(await showConfirm("Confermi le modifiche all'account?")) {
                try {
                    btnSave.textContent = "Salvataggio...";
                    btnSave.disabled = true;

                    const res = await fetch("/api/update_user", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({
                            old_username: state.user.username,
                            new_data: {
                                new_username: newUsername,
                                new_password: newPassword
                            }
                        })
                    });
                    const data = await res.json();

                    if(data.success) {
                        showCustomAlert("Profilo aggiornato con successo!");
                        if(data.new_username) {
                            state.user.username = data.new_username;
                            $("#profile-username-display").textContent = data.new_username;
                        }
                        $("#edit-username").value = "";
                        $("#edit-password").value = "";
                    } else {
                        showCustomAlert("Errore: " + data.error);
                    }

                } catch(e) {
                    console.error(e);
                    showCustomAlert("Errore di connessione");
                } finally {
                    btnSave.textContent = "Salva Modifiche";
                    btnSave.disabled = false;
                }
            }
        };
    }

    // Cancellazione Account (Irreversibile)
    const btnDel = $("#btn-delete-account");
    if(btnDel) {
        btnDel.onclick = async () => {
            if(await showConfirm("ATTENZIONE: Questa azione cancellerà definitivamente il tuo account e tutte le sessioni salvate. Procedere?")) {
                try {
                    btnDel.textContent = "Cancellazione...";
                    btnDel.disabled = true;

                    const res = await fetch("/api/delete_account", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({ username: state.user.username })
                    });
                    const data = await res.json();

                    if(data.success) {
                        state.role = null;
                        state.user = null;
                        sessionReset(); // Pulisce lo stato
                        window.location.reload(); // Ricarica la pagina da zero
                    } else {
                        showCustomAlert("Errore eliminazione: " + data.error);
                        btnDel.textContent = "Elimina Account";
                        btnDel.disabled = false;
                    }
                } catch(e) {
                    showCustomAlert("Errore di rete");
                    btnDel.textContent = "Elimina Account";
                    btnDel.disabled = false;
                }
            }
        };
    }
}

// Caricamento dati asincrono per la vista profilo
// Usa endpoint separati per statistiche e storico sessioni
async function populateProfileView() {
    console.log("🔄 populateProfileView avviato...");
    if(!state.user) {
        console.warn("Nessun utente loggato nello state.");
        return;
    }
    
    // UI Setup
    $("#profile-username-display").textContent = state.user.username;
    
    const roleMap = { 'user': 'Utente Base', 'composer': 'Compositore', 'org': 'Organizzatore', 'band': 'Band' };
    $("#profile-role-display").textContent = roleMap[state.user.role] || state.user.role.toUpperCase();

    const tracksContainer = document.querySelector(".mock-bar-chart");
    const historyList = document.querySelector(".history-list-mockup");

    // Placeholder di caricamento
    if(tracksContainer) tracksContainer.innerHTML = "<div style='padding:10px; opacity:0.6;'>Caricamento stats...</div>";
    if(historyList) historyList.innerHTML = "<div style='padding:10px; opacity:0.6;'>Caricamento storico...</div>";

    // 1. FETCH STATISTICHE (KPI + Top Tracks)
    try {
        console.log("📡 Fetching /api/user_profile_stats...");
        const resStats = await fetch("/api/user_profile_stats");
        if(!resStats.ok) throw new Error("Errore HTTP Stats");
        const stats = await resStats.json();
        console.log("✅ Stats ricevute:", stats);
        
        $("#mock-sessions-count").textContent = stats.total_sessions || 0;
        $("#mock-songs-count").textContent = stats.total_songs || 0;
        $("#mock-top-artist").textContent = stats.top_artist || "—";
        
        if(tracksContainer) {
            tracksContainer.innerHTML = ""; 
            if(stats.top_tracks && stats.top_tracks.length > 0) {
                // Costruisci le barre percentuali
                stats.top_tracks.forEach((t, idx) => {
                    const maxPlays = stats.top_tracks[0].play_count;
                    const percent = Math.round((t.play_count / maxPlays) * 100);
                    
                    const row = document.createElement("div");
                    row.className = "bar-row";
                    row.innerHTML = `
                        <span class="label" style="width: 20px;">${idx + 1}</span>
                        <div style="flex:1; display:flex; flex-direction:column; gap:2px;">
                            <div style="display:flex; justify-content:space-between; font-size:0.85rem;">
                                <span>${t.title} <span style="opacity:0.6">- ${t.artist}</span></span>
                                <span>${t.play_count}</span>
                            </div>
                            <div class="bar" style="width: ${percent}%;"></div>
                        </div>
                    `;
                    tracksContainer.appendChild(row);
                });
            } else {
                tracksContainer.innerHTML = "<span style='opacity:0.5; font-size:0.9rem;'>Nessun dato di ascolto disponibile.</span>";
            }
        }
    } catch(e) {
        console.error("❌ Errore stats:", e);
        if(tracksContainer) tracksContainer.innerHTML = "<span style='color:#f87171'>Errore caricamento dati.</span>";
    }

    // 2. FETCH STORICO SESSIONI
    try {
        console.log("📡 Fetching /api/user_session_history...");
        const resHist = await fetch("/api/user_session_history");
        if(!resHist.ok) throw new Error("Errore HTTP History");
        const dataHist = await resHist.json();
        
        if(historyList) {
            historyList.innerHTML = ""; 
            
            const validSessions = (dataHist.history || []).filter(s => s.song_count > 0);

            if(validSessions.length > 0) {
                validSessions.forEach(sess => {
                    const item = document.createElement("div");
                    item.className = "history-item";
                    
                    const title = `Live Session (${sess.song_count} brani)`;

                    item.innerHTML = `
                        <div class="h-info">
                            <strong>${title}</strong>
                            <span>${sess.date} • ID: ${sess.id.substring(8, 16)}</span>
                        </div>
                        <button class="btn btn--xs btn--primary" onclick="downloadHistorySession('${sess.id}')">
                            Scarica PDF
                        </button>
                    `;
                    historyList.appendChild(item);
                });
            } else {
                historyList.innerHTML = "<div style='padding:20px; text-align:center; opacity:0.5;'>Nessuna sessione valida trovata.</div>";
            }
        }
    } catch(e) {
        console.error("❌ Errore history:", e);
        if(historyList) historyList.innerHTML = "<span style='color:#f87171'>Errore caricamento storico.</span>";
    }
}

// Inizializzazione Dashboard Compositore (Vista Grafici)
// Calcola trend mensili e disegna il grafico con Chart.js
async function initComposerDashboard() {
  let currentStageName = state.stage_name;
  if (!currentStageName) {
      const storedUser = localStorage.getItem("kyma_user");
      if(storedUser) {
          const u = JSON.parse(storedUser);
          currentStageName = u.stage_name || u.username;
      } else {
          currentStageName = "Vasco Rossi"; // Demo fallback
      }
  }

  // Reset UI
  $("#comp-total-plays").textContent = "...";
  $("#comp-est-revenue").textContent = "...";
  const trendEl = document.getElementById("comp-trend-plays");
  if(trendEl) trendEl.innerHTML = `<span style="opacity:0.5">Calcolo...</span>`;
   
  try {
      const res = await fetch("/api/composer_stats", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ stage_name: currentStageName })
      });
      
      const data = await res.json();
      if(data.error) throw new Error(data.error);

      // Statistiche Compositore
      const totalPlays = data.total_plays || 0;
      $("#comp-total-plays").textContent = totalPlays;
      
      const realRevenue = data.total_revenue || 0.0;
      $("#comp-est-revenue").textContent = formatMoney(realRevenue);

      // Calcolo Trend Mensile
      const today = new Date();
      const currentKey = `${today.getFullYear()}-${pad2(today.getMonth()+1)}`;
      const prevDate = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      const prevKey = `${prevDate.getFullYear()}-${pad2(prevDate.getMonth()+1)}`;

      const currentCount = data.history[currentKey] || 0;
      const prevCount = data.history[prevKey] || 0;
      
      let trendHtml = `<span style="opacity:0.5">Dati insufficienti</span>`;
      
      if (prevCount > 0) {
          const diff = currentCount - prevCount;
          const pct = Math.round((diff / prevCount) * 100);
          const symbol = pct >= 0 ? "↑" : "↓";
          const color = pct >= 0 ? "#4ade80" : "#f87171";
          trendHtml = `<span style="color:${color}">${symbol} ${Math.abs(pct)}% questo mese</span>`;
      } else if (currentCount > 0) {
          trendHtml = `<span style="color:#4ade80">↑ 100% questo mese</span>`;
      } else {
          trendHtml = `<span style="opacity:0.5">Nessuna variazione</span>`;
      }
      
      if(trendEl) trendEl.innerHTML = trendHtml;

      // Popolazione Tabella Brani Top
      const statList = document.querySelector(".stat-list");
      if(statList) {
          statList.innerHTML = "";
          if(data.top_tracks && data.top_tracks.length > 0) {
              data.top_tracks.forEach(t => {
                  const li = document.createElement("li");
                  li.style.display = "grid";
                  li.style.gridTemplateColumns = "2fr 1fr";
                  li.style.padding = "10px 14px";
                  li.style.borderBottom = "1px solid var(--border)";
                  li.innerHTML = `<span>${t.title}</span> <span style="text-align:right;">${t.count}</span>`;
                  statList.appendChild(li);
              });
          } else {
              statList.innerHTML = "<li style='padding:10px; opacity:0.5'>Nessun brano rilevato.</li>";
          }
      }

      // Configurazione e Rendering Chart.js
      const ctx = document.getElementById('composerChart');
      if(ctx && window.Chart) {
        if(window.compChartInstance) window.compChartInstance.destroy();
        
        const labels = [];
        const chartData = [];
        
        // Ultime 6 mensilità
        for(let i=5; i>=0; i--) {
            const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
            const key = `${d.getFullYear()}-${pad2(d.getMonth()+1)}`;
            const monthName = d.toLocaleString('it-IT', { month: 'short' });
            
            labels.push(monthName);
            chartData.push(data.history[key] || 0);
        }

        window.compChartInstance = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [{
              label: 'Esecuzioni',
              data: chartData,
              borderColor: "#EC368D",
              backgroundColor: "rgba(236, 54, 141, 0.2)",
              tension: 0.4,
              fill: true,
              pointBackgroundColor: "#fff",
              pointBorderColor: "#EC368D",
              pointRadius: 4
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              y: {
                  grid: { color: 'rgba(255,255,255,0.05)' },
                  ticks: { color: '#9fb0c2', precision:0 },
                  beginAtZero: true
              },
              x: { grid: { display: false }, ticks: { color: '#9fb0c2' } }
            }
          }
        });
      }

  } catch(e) {
      console.error("Errore stats dashboard:", e);
      showCustomAlert("Impossibile caricare le statistiche: " + e.message);
  }
}

/* LOGICA SESSIONE LIVE E PLAYLIST
   
   Questa parte gestisce il cuore dell'applicazione:
   1. Avvio/Stop della registrazione audio (chiamate al backend Python)
   2. Polling continuo per ottenere i brani rilevati
   3. Aggiornamento in tempo reale della UI (Log e Sfondo)
 */

// Aggiorna l'header con il nome della modalità o dell'incasso (per Org)
function hydrateSessionHeader() {
  const badge = $("#mode-badge");
  const revInputContainer = $("#org-revenue-input-container");
  const revDisplay = $("#org-revenue-display");
  const btnStart = $("#btn-session-start");
   
  if (!badge) return;

  if (state.mode === "band") {
    // MODIFICA: Rimosso nome artista per Live Band, testo fisso
    badge.textContent = "LIVE BAND";
  } else if (state.mode === "concert") {
    const artistName = state.concertArtist ? state.concertArtist.toUpperCase() : "";
    badge.textContent = artistName ? `CONCERTO - ${artistName}` : "CONCERTO";
  } else {
    badge.textContent = "SESSIONE";
  }

  // Se l'utente è un Organizzatore, gestisce la logica di inserimento incasso
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

// Aggiunge una riga al log visivo (append in cima alla lista)
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

// Timer: Gestione start, stop e reset del cronometro
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

// Gestione Stack UNDO (Ctrl+Z)
// Salva uno snapshot dell'intera lista brani prima di ogni modifica distruttiva
function pushUndoState() {
  const snapshot = JSON.parse(JSON.stringify(songs));
  undoStack.push(snapshot);
  if (undoStack.length > 5) undoStack.shift(); // Max 5 step
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

// Chiamata API per avviare il processo Python di ascolto
async function startBackendRecognition() {
  const body = {};
  if (state.mode === "concert" && state.concertArtist) body.targetArtist = state.concertArtist;
  // MODIFICA: Rimosso invio bandArtist poiché rimosso

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

// Aggiorna lo sfondo radiale con l'ultima copertina trovata
function updateBackground(url) {
    // MODIFICA: Funzionalità rimossa. Manteniamo lo sfondo di default.
    // Forziamo l'overlay dinamico a rimanere nascosto.
    const bgEl = document.getElementById("app-background");
    if (!bgEl) return;
    
    // Resetta eventuali stili precedenti e nasconde il layer
    bgEl.style.opacity = "0";
    bgEl.style.backgroundImage = "none";
}

//  FUNZIONALITà PRINCIPALE
// Funzione di Polling: Richiede al server lo stato della playlist ogni X secondi.
// Esegue un "update" intelligente tra i dati locali e quelli remoti per evitare
// di sovrascrivere modifiche manuali.
async function pollPlaylistOnce() {
  try {
    // timestamp per evitare cache browser
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
        // Nuovo brano rilevato dal server!
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

        // Se è nuovo e non cancellato, aggiorniamo il log a schermo
        if (!isDeleted && id > lastMaxSongId) {
            currentSongId = track.id;
            setNow(track.title, track.composer);
            pushLog({ id: track.id, index: track.order, title: track.title, composer: track.composer, artist: track.artist, cover: track.cover });
        }
      } else {
        // Brano già esistente: aggiorniamo i metadati se il server li ha raffinati
        if (song.composer && song.composer !== existing.composer) {
            existing.composer = song.composer;
            const rowEl = document.querySelector(`.log-row[data-id="${id}"] .col-composer`);
            if (rowEl) rowEl.textContent = existing.composer;
            if (currentSongId === id) setNow(existing.title, existing.composer);
        }
        if (song.original_composer && song.original_composer !== existing.original_composer) {
            existing.original_composer = song.original_composer;
        }
        // Aggiorniamo titoli solo se non sono stati confermati manualmente
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
     
    // Aggiornamento sfondo con l'ultima cover disponibile
    const activeSongs = songs.filter(s => !s.is_deleted);
    const lastSongWithCover = [...activeSongs].reverse().find(s => s.cover);
     
    if (lastSongWithCover && lastSongWithCover.cover !== currentCoverUrl) {
        currentCoverUrl = lastSongWithCover.cover;
        updateBackground(currentCoverUrl);
    }

    // Se siamo nella vista Review, ridisegniamo la tabella
    if (updatedExisting && state.route === "review") renderReview();
  } catch (err) { console.error(err); }
}

function startPlaylistPolling() {
  if (playlistPollInterval) return;
  pollPlaylistOnce();
  playlistPollInterval = setInterval(pollPlaylistOnce, 2000); // 2 secondi
}

function stopPlaylistPolling() {
  if (!playlistPollInterval) return;
  clearInterval(playlistPollInterval);
  playlistPollInterval = null;
}

// Avvio sessione: Attiva tutti i listener e timer
async function sessionStart() {
  showView("#view-session");
  hydrateSessionHeader();
  const btnStart = $("#btn-session-start");
  const btnPause = $("#btn-session-pause");
  const btnStop = $("#btn-session-stop");
   
  if (btnStart) btnStart.disabled = true;
  if (btnPause) btnPause.disabled = false;
  if (btnStop) btnStop.disabled = false;

  // Attiva l'animazione pulsante del LED
  const led = $(".led-rect");
  if(led) {
      led.classList.remove("led-paused", "led-fading-out");
      led.classList.add("led-active");
  }

  // Se non è un ripristino post-crash, cancella (reset) i dati vecchi
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

// Stop sessione: Ferma tutto e porta alla vista di Revisione
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
  await pollPlaylistOnce(); // Ultimo fetch di sicurezza
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

// Rendering della Tabella di Revisione (Page 4)
function renderReview() {
  const container = $("#review-rows");
  const template = $("#review-row-template");
  const btnGenerate = $("#btn-generate");
  const btnPayments = $("#btn-global-payments");
  const btnSplits = $("#btn-global-splits");

  if (!container || !template || !btnGenerate) return;

  container.innerHTML = "";
  const activeSongs = songs.filter(s => !s.is_deleted);
   
  let allConfirmed = activeSongs.length > 0;
  if (activeSongs.length === 0) allConfirmed = false;

  activeSongs.forEach((song, visualIndex) => {
    if (typeof song.confirmed !== "boolean") song.confirmed = false;
    if (!song.confirmed) allConfirmed = false;

    // Clona il template HTML per ogni riga
    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".review-index").textContent = visualIndex + 1;
     
    const inputComposer = node.querySelector('[data-field="composer"]');
    const inputTitle = node.querySelector('[data-field="title"]');
    inputComposer.value = song.composer || "";
    inputTitle.value = song.title || "";
     
    if (song.manual) node.classList.add("row--manual");
    // Se confermato, blocca input e cambia stile
    if(song.confirmed) {
        inputComposer.readOnly = true;
        inputTitle.readOnly = true;
        node.classList.add("row--confirmed");
    }

    // Listener per sbloccare la riga cliccando
    const unlockHandler = () => {
        if(song.confirmed) {
            song.confirmed = false;
            renderReview();
        }
    };
    inputComposer.onclick = unlockHandler;
    inputTitle.onclick = unlockHandler;

    const enterHandler = (e) => {
        if(e.key === "Enter") {
            node.querySelector(".btn-confirm").click();
            e.target.blur();
        }
    };
    inputComposer.addEventListener("keyup", enterHandler);
    inputTitle.addEventListener("keyup", enterHandler);

    const btn24 = node.querySelector(".btn-24ths");
    btn24.classList.remove("hidden");
    btn24.onclick = () => { openRoyaltiesView(song); };

    // Azione Conferma
    node.querySelector(".btn-confirm").addEventListener("click", (e) => {
        e.preventDefault();
        pushUndoState();
        song.composer = inputComposer.value || "";
        song.title = inputTitle.value || "";
        song.confirmed = true;
        renderReview();
    });

    // Azione Elimina
    node.querySelector(".btn-delete").addEventListener("click", async (e) => {
        e.preventDefault();
        if(await showConfirm("Sei sicuro?")) {
            pushUndoState();
            song.is_deleted = true;
            try {
                // Notifica al backend la cancellazione (opzionale)
                await fetch("/api/delete_song", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: song.id }) });
            } catch(err){console.error(err);}
            renderReview();
        }
    });

    // Azione Aggiungi riga manuale
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
   
  // Abilitazione bottoni export solo se tutto è confermato
  const enableGlobalActions = (activeSongs.length > 0) && allConfirmed;
  btnGenerate.disabled = !enableGlobalActions;
   
  if(state.role === 'org') {
      if(btnPayments) {
          btnPayments.classList.remove("hidden");
          btnPayments.disabled = !enableGlobalActions;
      }
      if(btnSplits) btnSplits.classList.add("hidden");
  } else {
      if(btnPayments) btnPayments.classList.add("hidden");
      if(btnSplits) {
          btnSplits.classList.remove("hidden");
          btnSplits.disabled = !enableGlobalActions;
      }
  }

  updateUndoButton();
  syncReviewNotes();
}

// Vista Dettaglio Brano (Calcolo 24esimi)
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
    
    // Calcolo stimato quota: 10% del totale diviso per numero brani (Logica semplificata)
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
        // Distribuisci il resto al primo compositore
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

// Inizializza pulsanti vista Pagamenti
function initGlobalPayments() {
  const btnPayments = $("#btn-global-payments");
  const btnSplits = $("#btn-global-splits");
  const btnBack = $("#btn-back-from-payments");
  const btnHome = $("#btn-home-restart");
   
  if(btnPayments) {
    btnPayments.onclick = async () => {
        if(state.role !== 'org') return;

        if (!state.orgRevenue || state.orgRevenue <= 0) {
            showCustomAlert("Attenzione: Incasso non inserito o pari a zero.");
            return;
        }

        if (!await showConfirm("Confermi il borderò? Questa azione distribuirà le royalties ai compositori.")) {
            return;
        }

        try {
            const originalText = btnPayments.textContent;
            btnPayments.textContent = "Elaborazione...";
            btnPayments.disabled = true;

            // Invia conferma pagamento al backend
            const res = await fetch("/api/finalize_revenue", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ revenue: state.orgRevenue })
            });
            const data = await res.json();

           if (data.success) {
                showCustomAlert("✅ Royalties distribuite con successo!");
                calculateAndShowPayments(true);
                showView("#view-payments");
                btnPayments.disabled = true; 
                btnPayments.textContent = "Pagamento Completato";
            } else {
                if (data.message && data.message.includes("già stata pagata")) {
                    showCustomAlert("ℹ️ " + data.message);
                    calculateAndShowPayments(true);
                    showView("#view-payments");
                } else {
                    showCustomAlert("Errore distribuzione: " + data.message);
                }
            }
        } catch (e) {
            console.error(e);
            showCustomAlert("Errore di rete durante il pagamento.");
        } finally {
            btnPayments.textContent = "Vai ai Pagamenti";
            btnPayments.disabled = false;
        }
    };
  }
   
  if(btnSplits) {
      btnSplits.onclick = () => {
          calculateAndShowPayments(false); 
          showView("#view-payments");
      };
  }

  if(btnBack) btnBack.onclick = () => showView("#view-review");

  if(btnHome) {
      btnHome.onclick = async () => {
          if(await showConfirm("Tornare alla Home e terminare sessione?")) {
              await sessionReset(); 
              state.role = null;
              state.mode = null;
              state.user = null;
              pendingRole = null;
              hoveredRole = null;
              showView("#view-roles");
          }
      };
  }
}

// Calcolo ripartizione totale e grafico a torta
function calculateAndShowPayments(showPayActions) {
  const listContainer = $("#global-payment-rows");
  const totalDisplay = $("#total-distributed-amount");
  const headerAction = $("#header-pay-action");
   
  if(!listContainer) return;
  listContainer.innerHTML = "";
   
  if(headerAction) {
      headerAction.style.display = showPayActions ? "block" : "none";
  }

  const activeSongs = songs.filter(s => !s.is_deleted);
   
  const isOrg = (state.role === 'org');
  let potPerSong = 0;
   
  if (isOrg) {
     potPerSong = (state.orgRevenue * 0.10) / (activeSongs.length || 1);
  } else {
     potPerSong = 1.0;
  }
   
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
      
      const actionHtml = showPayActions
          ? `<div style="width: 100px; text-align:center;">
               <button class="btn btn--small btn--primary btn-pay-global">Paga</button>
             </div>`
          : `<div style="width: 100px;"></div>`;
      
      let amountDisplay = "";
      if (isOrg) {
          amountDisplay = formatMoney(amount);
      } else {
          amountDisplay = ((amount / globalSum) * 100).toFixed(1) + "%";
      }

      row.innerHTML = `
        <span style="flex:1;">${comp}</span>
        <span style="width: 100px; text-align:right;">${amountDisplay}</span>
        ${showPayActions ? actionHtml : ''}
      `;
      
      if(showPayActions) {
          const btn = row.querySelector(".btn-pay-global");
          if(btn) {
              btn.onclick = (e) => {
                e.target.textContent = "Inviato ✔";
                e.target.disabled = true;
                e.target.style.background = "#22c55e";
              };
          }
      }

      listContainer.appendChild(row);
      chartLabels.push(comp);
      chartData.push(amount);
      chartColors.push(palette[index % palette.length]);
  });

  if(totalDisplay) {
      if (isOrg) {
         totalDisplay.textContent = formatMoney(globalSum);
         totalDisplay.parentNode.style.display = "flex";
      } else {
         totalDisplay.textContent = "100%"; 
         totalDisplay.parentNode.style.display = "flex";
      }
  }
   
  renderPaymentChart(chartLabels, chartData, chartColors, isOrg);
}

// Renderizza il grafico a ciambella usando Chart.js
let paymentChartInstance = null;
function renderPaymentChart(labels, data, colors, isCurrency) {
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
      plugins: { 
          legend: { position: 'right', labels: { color: '#e6eef8', font: { size: 11 } } },
          tooltip: {
              callbacks: {
                  label: function(context) {
                      let label = context.label || '';
                      if (label) { label += ': '; }
                       
                      if (isCurrency) {
                           label += new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' }).format(context.raw);
                      } else {
                           let sum = context.chart._metasets[context.datasetIndex].total;
                           let val = context.raw;
                           let percentage = (val * 100 / sum).toFixed(1) + "%";
                           label += percentage;
                      }
                      return label;
                  }
              }
          }
      }
    }
  });
}

// Aggiorna lo stato dei selettori (Card) nella pagina 2
function syncWelcomeModeRadios() {
  document.querySelectorAll(".mode-card").forEach((card) => card.classList.remove("mode-card--selected", "active"));
  document.querySelectorAll(".artist-input-wrapper").forEach(w => w.classList.remove("visible"));

  if (state.mode) {
    const c = document.querySelector(`.mode-card[data-mode="${state.mode}"]`);
    if(c) c.classList.add("mode-card--selected");

    if (state.mode === "band") {
      $("#bandArtistWrapper").classList.add("visible");
      // Rimossa gestione bandArtistInput
    } else if (state.mode === "concert") {
      $("#artistInputWrapper").classList.add("visible");
      if($("#artistInput")) $("#artistInput").value = state.concertArtist || "";
    }
  }
}

// Inizializza logica pagina 2
function initWelcome() {
  state.mode = null;
  applyTheme();
  syncWelcomeModeRadios();
   
  const grid = $("#welcome-grid");
  const statCard = $("#card-stats");
   
  // Mostra card statistiche solo se compositore
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
      btnBackRoles.onclick = async () => {
          try {
             await fetch("/api/logout", { method: "POST" });
          } catch(e) { console.error(e); }

          state.role = null; 
          state.mode = null; 
          state.user = null; 
          state.stage_name = "";
          
          explicitRestore = false;
          hoveredRole = null; 
          pendingRole = null;

          showView("#view-roles");
      };
  }

  const triggerBackendPrefetch = (artistName) => {
      if (!artistName) return;
      console.log("🚀 Avvio prefetch dati per:", artistName);
      fetch("/api/prepare_session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ targetArtist: artistName })
      }).catch(err => console.warn("Errore prefetch:", err));
  };

  const confirmArtist = () => {
    const name = $("#artistInput").value.trim();
    if (!name) return showCustomAlert("Inserisci nome artista");
    state.concertArtist = name;
    saveStateToLocal();
    triggerBackendPrefetch(name);
    goToSession();
  };

  // MODIFICA: confirmBand semplificato, non cerca più input
  const confirmBand = () => {
    saveStateToLocal();
    triggerBackendPrefetch(null);
    goToSession();
  };

  $("#artistConfirmBtn").onclick = (e) => { e.preventDefault(); confirmArtist(); };
  $("#bandConfirmBtn").onclick = (e) => { e.preventDefault(); confirmBand(); };

  const artInput = $("#artistInput");
  if(artInput) {
      artInput.addEventListener("keyup", (e) => {
          if(e.key === "Enter") confirmArtist();
      });
  }
  
  // Rimosso listener per bandArtistInput

  // Gestione pulsante "Recupera Sessione" (in caso di crash browser)
  const btnRestore = $("#btn-manual-restore");
  if(btnRestore) {
      btnRestore.onclick = async (e) => {
        e.preventDefault();
        const originalText = btnRestore.innerHTML;
        btnRestore.innerHTML = "Recupero...";
        btnRestore.disabled = true;

        try {
            const resRecover = await fetch("/api/recover_session", {
                method: "POST"
            });
            const dataRecover = await resRecover.json();

            if (!dataRecover.success) {
                throw new Error(dataRecover.message || "Nessuna sessione trovata");
            }

            const resPlaylist = await fetch("/api/get_playlist");
            if (!resPlaylist.ok) throw new Error("Errore nel download playlist");
            const dataPlaylist = await resPlaylist.json();
            
            if (!dataPlaylist.playlist || dataPlaylist.playlist.length === 0) {
                  throw new Error("Sessione vuota");
            }

            showCustomAlert(`Bentornato! Recuperati ${dataPlaylist.playlist.length} brani.`);

            const savedMode = localStorage.getItem("appMode");
            if (savedMode) {
                  state.mode = savedMode;
                  state.concertArtist = localStorage.getItem("concertArtist") || "";
                  // bandArtist rimosso
            } else {
                  state.mode = "band";
            }
            
            explicitRestore = true;
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

// Download Report (Excel/PDF/Raw)
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
      // MODIFICA: Rimosso bandArtist, usa "Live Band" o concertArtist
      artist: (state.mode === 'concert' ? state.concertArtist : "Live Band") || "Sconosciuto",
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

      // Creazione Blob e link fittizio per download automatico
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

// Collega listener a tutti i bottoni della sessione
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

  const btnSessionBack = $("#btn-session-back");
  if(btnSessionBack) {
      btnSessionBack.onclick = async () => {
          showView("#view-welcome");
      };
  }
   
  $("#btn-undo").onclick = (e) => { e.preventDefault(); undoLast(); };
   
  const btnBackReview = $("#btn-back-review");
  if(btnBackReview) { btnBackReview.onclick = () => showView("#view-review"); }

  const confirmRevenue = () => {
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

  const btnConfirmRev = $("#btn-confirm-revenue");
  if(btnConfirmRev) {
      btnConfirmRev.onclick = confirmRevenue;
  }
   
  const revInput = $("#session-revenue-input");
  if(revInput) {
      revInput.addEventListener("keyup", (e) => {
          if(e.key === "Enter") confirmRevenue();
      });
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

async function downloadHistorySession(sessionId) {
    if(!sessionId) return;
    showCustomAlert("Generazione Borderò in corso...");
    
    const link = document.createElement('a');
    link.href = `/api/download_history_report?session_id=${sessionId}`;
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Modale Conferma (Promise based)
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

/* ANIMAZIONE "STAGE LIGHTS" (Physics Engine)
   
   Questa parte calcola frame-by-frame la posizione dei faretti SVG.
   Usa un oscillatore sinusoidale smorzato per simulare il movimento fisico.
 */

// Stato dei faretti interattivi (Selezione Ruoli)
const lightsState = [
    { id: 'left', role: 'user', vertex: { x: 250, y: 150 }, baseY: 680, originalBaseX: 250, originalAmplitude: 150, currentAmp: 150, currentOp: 0.7, phase: 0, speed: 0.8, rx: 200 },
    { id: 'center', role: 'org', vertex: { x: 600, y: 150 }, baseY: 720, originalBaseX: 600, originalAmplitude: 180, currentAmp: 180, currentOp: 1.0, phase: 2, speed: 0.6, rx: 200 },
    { id: 'right', role: 'composer', vertex: { x: 950, y: 150 }, baseY: 680, originalBaseX: 950, originalAmplitude: 150, currentAmp: 150, currentOp: 0.7, phase: 4, speed: 0.75, rx: 200 }
];

// Stato dei faretti globali (in overlay)
const globalLightsState = [
    { id: 'gl-beam-tl', vertex: { x: 0, y: 0 }, baseY: 800, baseX: 500, amp: 120, phase: 0, speed: 0.52 },
    { id: 'gl-beam-tr', vertex: { x: 1920, y: 0 }, baseY: 800, baseX: 1420, amp: 120, phase: 2, speed: 0.46 },
    { id: 'gl-beam-bl', vertex: { x: 0, y: 1080 }, baseY: 280, baseX: 500, amp: 100, phase: 1, speed: 0.40 },
    { id: 'gl-beam-br', vertex: { x: 1920, y: 1080 }, baseY: 280, baseX: 1420, amp: 100, phase: 3, speed: 0.52 }
];

function animateStageLights() {
    const time = Date.now() * 0.00195; // Fattore tempo per la velocità di oscillazione
    const isReviewMode = state.route === 'review';
    const isRegisterMode = state.route === 'register';
    const isProfileMode = state.route === 'profile';

    // 1. Animazione Luci Interattive (Schermata Ruoli)
    lightsState.forEach(light => {
        const beam = document.getElementById(`beam-${light.id}`);
        const spot = document.getElementById(`spot-${light.id}`);
        const group = document.querySelector(`.spotlight-group[data-role="${light.role}"]`);
        const maskPath = document.getElementById(`mask-path-${light.id}`);

        if (!beam || !spot || !group) return;

        // Logica di dimming: spegni gli altri se uno è selezionato
        let targetAmp = light.originalAmplitude;
        let targetOp = (light.id === 'center') ? 1.0 : 0.7;
        let targetRole = state.role || pendingRole || hoveredRole;

        if (targetRole) {
            targetAmp = 0; // Ferma oscillazione se selezionato
            if (targetRole === light.role) { targetOp = (light.id === 'center') ? 1.0 : 0.7; }
            else { targetOp = 0.0; }
        }

        if (isRegisterMode || isProfileMode) { targetAmp = 0; targetOp = 1.0; }

        // Interpolazione (Lerp) per transizioni fluide
        light.currentAmp = lerp(light.currentAmp, targetAmp, 0.05);
        light.currentOp = lerp(light.currentOp, targetOp, 0.05);

        group.style.opacity = light.currentOp.toFixed(3);
        
        // Calcolo oscillazione sinusoidale
        const sway = Math.sin(time * light.speed + light.phase);
        const offsetX = sway * light.currentAmp;
        
        let currentX;
        if (isRegisterMode || isProfileMode) { currentX = 600; } else { currentX = light.originalBaseX + offsetX; }
        
        const currentRx = light.rx;
        spot.setAttribute('cx', currentX);
        spot.setAttribute('rx', currentRx);

        // Disegna il path SVG (curva quadratica per il fondo del cono)
        const xLeft = currentX - currentRx;
        const xRight = currentX + currentRx;
        const curveDepth = 40;
        const d = `M${light.vertex.x},${light.vertex.y} L${xLeft},${light.baseY} Q${currentX},${light.baseY + curveDepth} ${xRight},${light.baseY} Z`;

        beam.setAttribute('d', d);
        if(maskPath) maskPath.setAttribute('d', d);
    });

    // 2. Animazione Luci Globali (Overlay sempre visibile in sessione)
    globalLightsState.forEach(gl => {
        const beam = document.getElementById(gl.id);
        if(!beam) return;
        let currentX;
        // Logica speciale posizionamento luci in base alla vista
        if (isProfileMode) {
            // Posizioni fisse angolate per il profilo
            if (gl.id === 'gl-beam-tl') currentX = 1385;        
            else if (gl.id === 'gl-beam-tr') currentX = 1920 - 1385; 
            else if (gl.id === 'gl-beam-bl') currentX = 1385;    
            else if (gl.id === 'gl-beam-br') currentX = 1920 - 1385; 
        }
        else if (isReviewMode) {
            // Posizioni per la revisione
            if (gl.id === 'gl-beam-tl') currentX = 380;
            else if (gl.id === 'gl-beam-tr') currentX = 1540;
            else if (gl.id === 'gl-beam-bl') currentX = 600;
            else if (gl.id === 'gl-beam-br') currentX = 1320;
        } else {
            // Oscillazione standard
            const sway = Math.sin(time * gl.speed + gl.phase);
            currentX = gl.baseX + (sway * gl.amp);
        }
        const width = 190;
        const xLeft = currentX - width;
        const xRight = currentX + width;
        const d = `M${gl.vertex.x},${gl.vertex.y} L${xLeft},${gl.baseY} L${xRight},${gl.baseY} Z`;
        beam.setAttribute('d', d);
    });
    // Loop
    requestAnimationFrame(animateStageLights);
}

// Avvio dell'applicazione al caricamento del DOM
document.addEventListener("DOMContentLoaded", () => {
  wireSessionButtons();
  animateStageLights();

  initRoleSelection();
  initGlobalPayments();
  initRegistration();
  showView("#view-roles"); // Parte sempre dalla selezione ruoli
  syncReviewNotes();
});