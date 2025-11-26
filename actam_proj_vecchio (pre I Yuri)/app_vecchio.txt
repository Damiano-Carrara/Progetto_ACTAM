from flask import Flask, render_template, jsonify, request
from audio_manager import AudioManager
from session_manager import SessionManager # <--- Importiamo il nuovo modulo

app = Flask(__name__)

# Inizializziamo i nostri "robot"
audio_bot = AudioManager()
session_bot = SessionManager()

@app.route('/')
def home():
    return render_template('index.html')

# --- API 1: Riconoscimento e Aggiunta Automatica ---
@app.route('/api/start_recognition', methods=['POST'])
def start_recognition():
    # 1. Riconosci il brano (ACRCloud)
    api_result = audio_bot.recognize_song()
    
    # 2. Passa il risultato al Session Manager (che gestisce i duplicati)
    session_result = session_bot.add_song(api_result)
    
    # 3. Restituisci al frontend sia il risultato dell'API sia se è stato aggiunto
    return jsonify({
        "recognition": api_result,
        "session_update": session_result
    })

# --- API 2: Ottieni tutta la lista (per aggiornare la tabella) ---
@app.route('/api/get_playlist', methods=['GET'])
def get_playlist():
    playlist = session_bot.get_playlist()
    return jsonify({"playlist": playlist})

# --- API 3: Cancella un brano (per il tasto "Cestino") ---
@app.route('/api/delete_song', methods=['POST'])
def delete_song():
    # Il frontend ci manda un JSON tipo {"id": 3}
    data = request.get_json()
    song_id = data.get('id')
    
    if song_id:
        session_bot.delete_song(song_id)
        return jsonify({"status": "deleted", "id": song_id})
    return jsonify({"status": "error", "message": "ID mancante"})

if __name__ == '__main__':
    app.run(debug=True)