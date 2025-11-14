let isRecording = false;

// Funzione chiamata dal bottone START
function startSession() {
    isRecording = true;
    document.getElementById("btn-start").disabled = true;
    document.getElementById("btn-stop").disabled = false;
    updateStatus("🔴 In ascolto...", "recording");
    
    // Avvia il loop
    runRecognitionLoop();
}

// Funzione chiamata dal bottone STOP
function stopSession() {
    isRecording = false;
    document.getElementById("btn-start").disabled = false;
    document.getElementById("btn-stop").disabled = true;
    updateStatus("⏹️ Sessione terminata", "idle");
}

// IL CUORE DEL SISTEMA: Il Loop ricorsivo
async function runRecognitionLoop() {
    if (!isRecording) return;

    console.log("🎙️ Inizio ciclo di riconoscimento...");
    
    try {
        // 1. Chiama la TUA API Python
        const response = await fetch('/api/start_recognition', {
            method: 'POST'
        });
        
        const data = await response.json();
        console.log("Risultato API:", data);

        // 2. Se il brano è stato aggiunto (non è duplicato), aggiorniamo la tabella
        // Nota: session_update viene dal tuo return in app.py
        if (data.session_update && data.session_update.added) {
            addSongToTable(data.session_update.song);
            highlightRow(data.session_update.song.id); // Effetto visivo
        } else {
            console.log("Brano ignorato o duplicato:", data.session_update?.reason);
        }

    } catch (error) {
        console.error("Errore di comunicazione:", error);
        updateStatus("⚠️ Errore API", "error");
    }

    // 3. Riavvia il ciclo se siamo ancora in recording (dopo una piccola pausa)
    if (isRecording) {
        setTimeout(runRecognitionLoop, 1000); // Aspetta 1 secondo tra un brano e l'altro
    }
}

// Funzione per aggiungere una riga alla tabella HTML
function addSongToTable(song) {
    const tbody = document.querySelector("#playlist-table tbody");
    
    // Calcolo minuti:secondi dalla durata in ms
    const minutes = Math.floor(song.duration_ms / 60000);
    const seconds = ((song.duration_ms % 60000) / 1000).toFixed(0);
    const durationStr = minutes + ":" + (seconds < 10 ? '0' : '') + seconds;

    const row = `
        <tr id="row-${song.id}">
            <td>${song.timestamp}</td>
            <td><strong>${song.title}</strong></td>
            <td>${song.artist}</td>
            <td>${durationStr}</td>
            <td><span class="badge">${song.type}</span></td>
            <td>
                <button onclick="deleteSong(${song.id})" class="btn-delete">🗑️</button>
            </td>
        </tr>
    `;
    
    // Inserisce la nuova riga IN CIMA alla tabella
    tbody.insertAdjacentHTML('afterbegin', row);
}

// Funzione per chiamare l'API di cancellazione
async function deleteSong(id) {
    if(!confirm("Vuoi eliminare questo brano dal borderò?")) return;

    await fetch('/api/delete_song', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: id })
    });

    // Rimuovi la riga dalla tabella visiva
    document.getElementById(`row-${id}`).remove();
}

// Helper per aggiornare lo stato grafico
function updateStatus(text, className) {
    const el = document.getElementById("status-indicator");
    document.getElementById("status-text").innerText = text;
    el.className = "status-box " + className;
}

function highlightRow(id) {
    const row = document.getElementById(`row-${id}`);
    if(row) {
        row.style.backgroundColor = "#2e7d32"; // Verde scuro per un attimo
        setTimeout(() => row.style.backgroundColor = "", 2000);
    }
}