from flask import Flask, render_template, jsonify, request, send_file
from audio_manager import AudioManager
from session_manager import SessionManager
# [MERGE] Importiamo il generatore di report del collega
try:
    from report_generator import ReportGenerator
except ImportError:
    print("⚠️ AVVISO: 'report_generator.py' non trovato. Le funzioni di export PDF/Excel non funzioneranno.")
    ReportGenerator = None

import atexit
import io
import qrcode
import threading
import time
from pyngrok import ngrok, conf

app = Flask(__name__)

# Configurazione Ngrok
conf.get_default().auth_token = "36h1RSKg2jFomjrnvz9iLqTmvXx_dR6mu6AVwxAzjquwYyZE"

public_url = None

# Inizializziamo i nostri "robot"
audio_bot = AudioManager()
session_bot = SessionManager()

# [MERGE] Inizializziamo il ReportBot solo se la classe esiste
report_bot = ReportGenerator() if ReportGenerator else None

def start_ngrok():
    """Avvia il tunnel Ngrok sulla porta 5000"""
    global public_url
    try:
        # 1. Tentiamo di uccidere il processo ngrok gestito da pyngrok
        print("🔄 Pulizia tunnel precedenti...")
        ngrok.kill()
        
        # 2. Aspettiamo un attimo che il sistema liberi la risorsa
        time.sleep(1)
        
        # 3. Apriamo un tunnel HTTP sulla porta 5000
        # Nota: Se vuoi forzare quel dominio specifico che vedi nell'errore,
        # puoi aggiungerlo qui (opzionale, solo se hai un dominio statico configurato):
        # tunnel = ngrok.connect(5000, domain="glaciered-placoid-aimee.ngrok-free.dev")
        
        tunnel = ngrok.connect(5000)
        public_url = tunnel.public_url
        print(f"🌍 Tunnel Ngrok Attivo! URL Pubblico: {public_url}")
        
    except Exception as e:
        print(f"⚠️ Errore avvio Ngrok: {e}")
        print("💡 SUGGERIMENTO: Apri Task Manager e termina 'ngrok.exe' manualmente.")
        public_url = None

@app.route('/')
def home():
    # Gestione Modalità "Spettatore"
    mode = request.args.get('mode', 'admin')
    return render_template('index.html', viewer_mode=(mode == 'viewer'))

@app.route('/api/get_qr_image')
def get_qr_image():
    """Genera il QR Code per lo streaming remoto"""
    if not public_url:
        return jsonify({"error": "Tunnel non attivo"}), 404
    
    viewer_link = f"{public_url}?mode=viewer"
    
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(viewer_link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)

    return send_file(img_io, mimetype='image/png')

# --- API 1: AVVIA IL MONITORAGGIO CONTINUO ---
@app.route('/api/start_recognition', methods=['POST'])
def start_recognition():
    data = request.get_json() or {}
    target_artist = data.get('targetArtist')
    
    print(f"🚀 Richiesta avvio monitoraggio. Bias: {target_artist}")
    
    # Callback verso session_bot.add_song
    started = audio_bot.start_continuous_recognition(
        callback_function=session_bot.add_song,
        target_artist=target_artist
    )
    
    if started:
        return jsonify({"status": "started", "message": "Monitoraggio continuo avviato."})
    else:
        return jsonify({"status": "error", "message": "Già in esecuzione."})

# --- API 2: FERMA IL MONITORAGGIO (VERSIONE CON FIXER GENIUS) ---
@app.route('/api/stop_recognition', methods=['POST'])
def stop_recognition():
    # 1. Ferma l'audio in tempo reale
    audio_bot.stop_continuous_recognition()
    
    # 2. Avvia il "Fixer" in background per cercare i compositori mancanti su Genius
    #    (Usa un thread per non bloccare l'interfaccia utente mentre cerca)
    fixer_thread = threading.Thread(target=session_bot.trigger_post_process_enrichment)
    fixer_thread.daemon = True
    fixer_thread.start()
    
    return jsonify({
        "status": "stopped", 
        "message": "Monitoraggio fermato. Avvio ricerca approfondita compositori (Genius)..."
    })

# --- API 3: OTTIENI LA LISTA ---
@app.route('/api/get_playlist', methods=['GET'])
def get_playlist():
    # Ora questa playlist includerà il campo 'cover' grazie alle modifiche al backend
    playlist = session_bot.get_playlist()
    return jsonify({"playlist": playlist})

# --- API 4: CANCELLA BRANO ---
@app.route('/api/delete_song', methods=['POST'])
def delete_song():
    data = request.get_json()
    if session_bot.delete_song(data.get('id')):
        return jsonify({"status": "deleted"})
    return jsonify({"status": "error"})

@app.route('/api/get_fixer_status', methods=['GET'])
def get_fixer_status():
    """Restituisce true se Genius sta ancora lavorando in background"""
    return jsonify({"is_fixing": session_bot.is_fixing_actively})

# --- API 5: RESET TOTALE SESSIONE ---
@app.route('/api/reset_session', methods=['POST'])
def reset_session():
    if session_bot.clear_session():
        return jsonify({"status": "cleared", "message": "Sessione resettata."})
    else:
        return jsonify({"status": "error", "message": "Errore nel reset DB."})

# --- API 6: GENERAZIONE REPORT (Dal Codice del Collega) ---
@app.route("/api/generate_report", methods=["POST"])
def generate_report():
    if not report_bot:
        return jsonify({"error": "Modulo report non disponibile"}), 500

    data = request.get_json()
    playlist_data = data.get("songs", [])
    mode = data.get("mode", "session")
    artist_name = data.get("artist", "Unknown")
    fmt = data.get("format", "excel")  # 'excel', 'pdf_official', 'pdf_raw'

    meta = {"artist": f"{artist_name} ({mode.upper()})"}

    try:
        if fmt == "excel":
            output = report_bot.generate_excel(playlist_data, meta)
            mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ext = "xlsx"
        elif fmt == "pdf_official":
            output = report_bot.generate_pdf_official(playlist_data, meta)
            mimetype = "application/pdf"
            ext = "pdf"
        elif fmt == "pdf_raw":
            output = report_bot.generate_pdf_raw(playlist_data, meta)
            mimetype = "application/pdf"
            ext = "pdf"
        else:
            return jsonify({"error": "Formato non supportato"}), 400

        safe_artist = artist_name.replace(" ", "_").replace("/", "-")
        filename = f"Bordero_{mode}_{safe_artist}_{fmt}.{ext}"

        return send_file(
            output,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"Errore generazione report: {e}")
        return jsonify({"error": str(e)}), 500

def cleanup_on_exit():
    """Pulizia alla chiusura dell'app"""
    audio_bot.stop_continuous_recognition()
    ngrok.kill()

atexit.register(cleanup_on_exit)

if __name__ == '__main__':
    start_ngrok()
    app.run(debug=False, use_reloader=False)