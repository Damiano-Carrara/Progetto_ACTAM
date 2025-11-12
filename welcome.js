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

// ===== VIEW (tocca il DOM) =====
const $ = (sel) => document.querySelector(sel);

function showView(sectionId) {
  ["#view-welcome", "#view-session", "#view-review"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    const active = id === sectionId;
    el.hidden = !active;
    el.classList.toggle("view--active", active);
  });
}

function init() {
  const form = $("#welcome-form");
  const startBtn = $("#btn-start-program");

  // aggiorna mode ogni volta che cambi radio
  form.onchange = (e) => {
    if (e.target.name === "mode") setMode(e.target.value);
  };

  // clic sul bottone "Start program"
  startBtn.onclick = (e) => {
    e.preventDefault(); // evita ricarica pagina
    setRoute("session"); // aggiorna stato
    showView("#view-session"); // mostra seconda facciata
  };
}
document.addEventListener("DOMContentLoaded", init);
// ===== CONTROLLER (collega eventi ↔ stato ↔ DOM) =====
/*function init() {
  const form = $("#welcome-form");
  const startBtn = $("#btn-start-program");

  // cambio radio → aggiorna MODE
  form.addEventListener("change", (e) => {
    if (e.target.name === "mode") setMode(e.target.value);
  });

  // submit → cambia ROUTE e mostra facciata 2
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    setRoute("session");
    showView("#view-session");
  });

  // facciata iniziale
  showView("#view-welcome");
}*/


// app.js

// ===== MODEL =====
/*const Model = {
  state: {
    mode: "dj",          // "dj" | "band"
    route: "welcome",    // "welcome" | "session" | "review"
  },

  setMode(newMode) {
    if (newMode !== "dj" && newMode !== "band") return;
    this.state.mode = newMode;
  },

  setRoute(newRoute) {
    this.state.route = newRoute;
  }
};

// ===== VIEW HELPERS (view layer utilities) =====
const View = {
  qs: (sel) => document.querySelector(sel),

  show(sectionId) {
    // nascondi tutte le view, mostra quella richiesta
    ["#view-welcome","#view-session","#view-review"].forEach(id => {
      const el = this.qs(id);
      if (!el) return;
      if (id === sectionId) { el.hidden = false; el.classList.add("view--active"); }
      else { el.hidden = true; el.classList.remove("view--active"); }
    });
  }
};

// ===== CONTROLLER =====
const Controller = {
  init() {
    // boot: imposta handlers e stato iniziale
    this.$form = View.qs("#welcome-form");
    this.$startBtn = View.qs("#btn-start-program");

    // radio change → aggiorna Model
    this.$form.addEventListener("change", (e) => {
      if (e.target.name === "mode") {
        Model.setMode(e.target.value);
      }
    });

    // submit form → valida e naviga
    this.$form.addEventListener("submit", (e) => {
      e.preventDefault();
      // (qui potresti validare, ma la scelta ha default checked)
      Model.setRoute("session");
      View.show("#view-session");
      // passaggio di contesto alla facciata 2 (es: mostrare la modalità)
      // window.SessionController?.hydrate(Model.state); // opzionale se separi controller per view
    });

    // mostra welcome all’avvio
    View.show("#view-welcome");
  }
};

// Avvio app
window.addEventListener("DOMContentLoaded", () => Controller.init());*/
