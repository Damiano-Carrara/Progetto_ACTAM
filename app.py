from flask import Flask, render_template, jsonify
from audio_manager import AudioManager

app = Flask(__name__)
audio_bot = AudioManager()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/start_recognition', methods=['POST'])
def start_recognition():
    # Chiamiamo la funzione vera!
    result = audio_bot.recognize_song()
    
    # Stampiamo il risultato nel terminale per debug
    print("Risultato API:", result)
    
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)