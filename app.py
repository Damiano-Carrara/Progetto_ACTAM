from flask import Flask, render_template, jsonify, request
from audio_manager import AudioManager
from session_manager import SessionManager 
import atexit 

app = Flask(__name__)

# Inizializziamo i nostri "robot"
audio_bot = AudioManager()
session_bot = SessionManager()

@app.route('/')
def home():
    return render_template('index.html')

# --- API 1: AVVIA IL MONITORAGGIO CONTINUO ---
@app.route('/api/start_recognition', methods=['POST'])
def start_recognition():
    # Riceviamo il target artist (Bias)
    data = request.get_json() or {}
    target_artist = data.get('targetArtist')
    
    print(f"🚀 Richiesta avvio monitoraggio. Bias: {target_artist}")
    
    # Passiamo a AudioBot la funzione add_song del SessionBot come "Callback"
    # Così quando AudioBot trova qualcosa, lo passa direttamente a SessionBot
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

# --- API 3: OTTIENI LA LISTA (Per il Frontend che deve fare polling) ---
@app.route('/api/get_playlist', methods=['GET'])
def get_playlist():
    # Restituisce la lista accumulata dal SessionManager
    playlist = session_bot.get_playlist()
    return jsonify({"playlist": playlist})

# --- API 4: CANCELLA ---
@app.route('/api/delete_song', methods=['POST'])
def delete_song():
    data = request.get_json()
    if session_bot.delete_song(data.get('id')):
        return jsonify({"status": "deleted"})
    return jsonify({"status": "error"})

def cleanup_on_exit():
    audio_bot.stop_continuous_recognition()

atexit.register(cleanup_on_exit)

if __name__ == '__main__':
    app.run(debug=False, use_reloader=False)