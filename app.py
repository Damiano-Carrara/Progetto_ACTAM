from flask import Flask, render_template, jsonify, request, send_file
from audio_manager import AudioManager
from session_manager import SessionManager
from report_generator import ReportGenerator
import threading
import atexit
import io
import qrcode
import time
from pyngrok import ngrok, conf
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# Configurazione Ngrok
conf.get_default().auth_token = "36h1RSKg2jFomjrnvz9iLqTmvXx_dR6mu6AVwxAzjquwYyZE"

public_url = None

# --- Inizializzazione Firebase (Versione Safe del Collega) ---
try:
    cred = credentials.Certificate("firebase_credentials.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("🔥 Firebase Connesso!")
except FileNotFoundError:
    print("⚠️ AVVISO: 'firebase_credentials.json' non trovato. Modalità OFFLINE (Solo RAM).")
    db = None
except ValueError:
    print("⚠️ AVVISO: App Firebase già inizializzata.")
    db = firestore.client()

# Inizializziamo i nostri "robot"
audio_bot = AudioManager()
# Passiamo il db al session manager
session_bot = SessionManager(db_instance=db)
report_bot = ReportGenerator()

def start_ngrok():
    """Avvia il tunnel Ngrok sulla porta 5000"""
    global public_url
    try:
        # Chiudiamo tunnel precedenti per sicurezza
        ngrok.kill()

        # Apriamo un tunnel HTTP sulla porta 5000
        tunnel = ngrok.connect(5000)
        public_url = tunnel.public_url
        print(f"🌍 Tunnel Ngrok Attivo! URL Pubblico: {public_url}")
    except Exception as e:
        print(f"⚠️ Errore avvio Ngrok: {e}")
        public_url = None


@app.route("/")
def home():
    # Gestione Modalità "Spettatore"
    mode = request.args.get("mode", "admin")
    return render_template("index.html", viewer_mode=(mode == "viewer"))


@app.route("/api/get_qr_image")
def get_qr_image():
    """Genera il QR Code per lo streaming remoto"""
    if not public_url:
        return jsonify({"error": "Tunnel non attivo"}), 404

    # Creiamo l'URL per lo spettatore (aggiungiamo ?mode=viewer)
    viewer_link = f"{public_url}?mode=viewer"

    # Generiamo il QR
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(viewer_link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Salviamo in memoria (RAM)
    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)

    return send_file(img_io, mimetype="image/png")

# --- API: PRE-CARICAMENTO CONTESTO (PREFETCH) ---
# ✅ REINSERITA (Il collega l'aveva tolta, ma serve per le performance)
@app.route("/api/prepare_session", methods=["POST"])
def prepare_session():
    data = request.get_json() or {}
    target_artist = data.get("targetArtist")
    
    print(f"📡 Prefetch richiesto per: {target_artist}")
    
    # Avvia il download in background
    audio_bot.update_target_artist(target_artist)
    
    return jsonify({"status": "prefetching", "message": "Download contesto avviato."})


# --- API: AVVIA IL MONITORAGGIO CONTINUO ---
@app.route("/api/start_recognition", methods=["POST"])
def start_recognition():
    data = request.get_json() or {}
    target_artist = data.get("targetArtist") # L'artista scritto nella input box

    print(f"🚀 Richiesta avvio monitoraggio. Bias: {target_artist}")

    # Aggiorniamo il target (anche se fatto dal prefetch, è safe richiamarlo)
    audio_bot.update_target_artist(target_artist)

    started = audio_bot.start_continuous_recognition(
        callback_function=session_bot.add_song,
        target_artist=target_artist
    )

    if started:
        return jsonify({"status": "started", "message": "Monitoraggio continuo avviato."})
    return jsonify({"status": "error", "message": "Già in esecuzione."})

# --- API: FERMA IL MONITORAGGIO ---
@app.route("/api/stop_recognition", methods=["POST"])
def stop_recognition():
    audio_bot.stop_continuous_recognition()
    return jsonify({"status": "stopped"})


# --- API: OTTIENI LA LISTA ---
@app.route("/api/get_playlist", methods=["GET"])
def get_playlist():
    playlist = session_bot.get_playlist()
    return jsonify({"playlist": playlist})


# --- API: CANCELLA BRANO ---
@app.route("/api/delete_song", methods=["POST"])
def delete_song():
    data = request.get_json()
    if session_bot.delete_song(data.get("id")):
        return jsonify({"status": "deleted"})
    return jsonify({"status": "error"})


# --- API: RESET TOTALE SESSIONE ---
@app.route("/api/reset_session", methods=["POST"])
def reset_session():
    if session_bot.clear_session():
        return jsonify({"status": "cleared", "message": "Sessione resettata."})
    return jsonify({"status": "error", "message": "Errore nel reset DB."})

# --- API: STATISTICHE COMPOSITORE ---
@app.route("/api/composer_stats", methods=["POST"])
def get_composer_stats():
    data = request.get_json()
    # Il frontend invia il nome d'arte dell'utente loggato
    stage_name = data.get("stage_name")
    
    if not stage_name:
        return jsonify({"error": "Nome d'arte mancante"}), 400
        
    stats = session_bot.get_composer_stats(stage_name)
    return jsonify(stats)

# --- API: RECUPERA ULTIMA SESSIONE ---
@app.route("/api/recover_session", methods=["POST"])
def recover_session():
    # Chiama il metodo del session_manager
    result = session_bot.recover_last_session()
    
    if result["success"]:
        return jsonify(result)
    else:
        return jsonify(result), 404


# --- API: GENERAZIONE REPORT (EXCEL / PDF) ---
@app.route("/api/generate_report", methods=["POST"])
def generate_report():
    data = request.get_json()
    playlist_data = data.get("songs", [])
    mode = data.get("mode", "session")
    artist_name = data.get("artist", "Unknown")
    fmt = data.get("format", "excel")  # 'excel', 'pdf_official', 'pdf_raw'

    # Prepariamo i metadati per il report generator
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

        # Nome file dinamico
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

# --- API PER AUTH (AGGIUNTE DAL COLLEGA) ---
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json()
    # NOTA: Richiede aggiornamento session_manager.py
    if hasattr(session_bot, 'register_user'):
        res = session_bot.register_user(data)
        return jsonify(res)
    return jsonify({"error": "Backend updating..."}), 503

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")
    
    # NOTA: Richiede aggiornamento session_manager.py
    if hasattr(session_bot, 'login_user'):
        res = session_bot.login_user(username, password, role)
        return jsonify(res)
    return jsonify({"error": "Backend updating..."}), 503

# --------------------------------

def cleanup_on_exit():
    """Pulizia alla chiusura dell'app"""
    print("🛑 Chiusura Applicazione...")
    audio_bot.stop_continuous_recognition()
    ngrok.kill()


atexit.register(cleanup_on_exit)

if __name__ == "__main__":
    start_ngrok()
    app.run(debug=False, use_reloader=False)