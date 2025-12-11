from flask import Flask, render_template, jsonify, request, send_file
from audio_manager import AudioManager
from session_manager import SessionManager 
import atexit
import io 
import qrcode
from pyngrok import ngrok, conf

app = Flask(__name__)

# Configurazione Ngrok del collega
# Nota: Assicurati che questo token sia corretto, altrimenti ngrok non parte.
conf.get_default().auth_token = "36h1RSKg2jFomjrnvz9iLqTmvXx_dR6mu6AVwxAzjquwYyZE"

public_url = None

# Inizializziamo i nostri "robot"
audio_bot = AudioManager()
session_bot = SessionManager()

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
    # Gestione Modalità "Spettatore" (dal codice del collega)
    # Se scansioni il QR code, l'URL avrà ?mode=viewer
    mode = request.args.get('mode', 'admin')
    return render_template('index.html', viewer_mode=(mode == 'viewer'))

@app.route('/api/get_qr_image')
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
    
    # Salviamo in memoria (RAM) per non creare file inutili
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)

    return send_file(img_io, mimetype='image/png')

# --- API 1: AVVIA IL MONITORAGGIO CONTINUO ---
@app.route('/api/start_recognition', methods=['POST'])
def start_recognition():
    # Riceviamo il target artist (Bias)
    data = request.get_json() or {}
    target_artist = data.get('targetArtist')
    
    print(f"🚀 Richiesta avvio monitoraggio. Bias: {target_artist}")
    
    # Passiamo a AudioBot la funzione add_song del SessionBot come "Callback"
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
    playlist = session_bot.get_playlist()
    return jsonify({"playlist": playlist})

# --- API 4: CANCELLA BRANO ---
@app.route('/api/delete_song', methods=['POST'])
def delete_song():
    data = request.get_json()
    if session_bot.delete_song(data.get('id')):
        return jsonify({"status": "deleted"})
    return jsonify({"status": "error"})

# --- API 5: RESET TOTALE SESSIONE (Dal collega - Gestione DB) ---
@app.route('/api/reset_session', methods=['POST'])
def reset_session():
    # Chiama la funzione clear_session che abbiamo aggiunto in session_manager
    if session_bot.clear_session():
        return jsonify({"status": "cleared", "message": "Sessione resettata."})
    else:
        return jsonify({"status": "error", "message": "Errore nel reset DB."})

def cleanup_on_exit():
    """Pulizia alla chiusura dell'app"""
    audio_bot.stop_continuous_recognition()
    ngrok.kill() # Chiude il tunnel

atexit.register(cleanup_on_exit)

if __name__ == '__main__':
    # Avvia prima il tunnel, poi il server Flask
    start_ngrok()
    app.run(debug=False, use_reloader=False)