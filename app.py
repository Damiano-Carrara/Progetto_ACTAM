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
        # Chiudiamo tunnel precedenti per sicurezza
        ngrok.kill()
        
        # Apriamo un tunnel HTTP sulla porta 5000
        tunnel = ngrok.connect(5000)
        public_url = tunnel.public_url
        print(f"🌍 Tunnel Ngrok Attivo! URL Pubblico: {public_url}")
    except Exception as e:
        print(f"⚠️ Errore avvio Ngrok: {e}")
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

# --- API 2: FERMA IL MONITORAGGIO ---
@app.route('/api/stop_recognition', methods=['POST'])
def stop_recognition():
    audio_bot.stop_continuous_recognition()
    return jsonify({"status": "stopped"})

# --- API 3: OTTIENI LA LISTA ---
@app.route('/api/get_playlist', methods=['GET'])
def get_playlist():
    # [MODIFICA] IncludeDeleted=False per la UI Web (nasconde i cancellati)
    playlist = session_bot.get_playlist(include_deleted=False)
    return jsonify({"playlist": playlist})

# --- API 4: CANCELLA BRANO ---
@app.route('/api/delete_song', methods=['POST'])
def delete_song():
    data = request.get_json()
    if session_bot.delete_song(data.get('id')):
        return jsonify({"status": "deleted"})
    return jsonify({"status": "error"})

# --- API 5: RESET TOTALE SESSIONE ---
@app.route('/api/reset_session', methods=['POST'])
def reset_session():
    if session_bot.clear_session():
        return jsonify({"status": "cleared", "message": "Sessione resettata."})
    else:
        return jsonify({"status": "error", "message": "Errore nel reset DB."})

# --- API 6: GENERAZIONE REPORT (CORRETTO) ---
@app.route("/api/generate_report", methods=["POST"])
def generate_report():
    if not report_bot:
        return jsonify({"error": "Modulo report non disponibile"}), 500

    data = request.get_json()
    
    # 1. Recupera lista Backend ORIGINALE
    raw_backend_list = session_bot.get_playlist(include_deleted=True)
    
    # [FIX CRITICO] Creiamo una COPIA della lista e dei dizionari al suo interno.
    # Se non usiamo .copy(), le modifiche fatte qui sotto (es. .append o cambio titolo)
    # si riflettono sulla memoria permanente del programma, causando duplicati al prossimo click.
    playlist_for_report = [song.copy() for song in raw_backend_list]
    
    # 2. Recupera lista Frontend
    frontend_list = data.get("songs", [])
    frontend_map = {s['id']: s for s in frontend_list if s.get('id') is not None}
    
    # 3. Applica le modifiche del Frontend alla nostra COPIA per il report
    for song in playlist_for_report:
        if song['id'] in frontend_map:
            f_song = frontend_map[song['id']]
            song['title'] = f_song.get('title', song['title'])
            song['composer'] = f_song.get('composer', song['composer'])
            song['artist'] = f_song.get('artist', song['artist'])
            song['confirmed'] = f_song.get('confirmed', False)
    
    # 4. Aggiungi i brani MANUALI alla COPIA per il report
    # Questi non vengono salvati nel DB backend, esistono solo nel file generato.
    for f_song in frontend_list:
        if f_song.get('manual', False) or f_song.get('id') is None:
            new_manual_entry = {
                "id": "MANUAL", 
                "title": f_song.get('title', ''),
                "artist": f_song.get('artist', ''),
                "composer": f_song.get('composer', ''),
                "confirmed": f_song.get('confirmed', False),
                "manual": True,
                "is_deleted": False, 
                # Dati per il Report RAW
                "original_title": "(Inserimento Manuale)",
                "original_composer": "(Inserimento Manuale)",
                "original_artist": "—"
            }
            # Appendiamo SOLO alla lista temporanea del report
            playlist_for_report.append(new_manual_entry)

    mode = data.get("mode", "session")
    artist_name = data.get("artist", "Unknown")
    fmt = data.get("format", "excel")

    meta = {"artist": f"{artist_name} ({mode.upper()})"}

    try:
        # Passiamo la lista copiata e modificata al generatore
        if fmt == "excel":
            output = report_bot.generate_excel(playlist_for_report, meta)
            mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ext = "xlsx"
        elif fmt == "pdf_official":
            output = report_bot.generate_pdf_official(playlist_for_report, meta)
            mimetype = "application/pdf"
            ext = "pdf"
        elif fmt == "pdf_raw":
            output = report_bot.generate_pdf_raw(playlist_for_report, meta)
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