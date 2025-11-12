from flask import Flask, render_template, jsonify
from audio_manager import AudioManager # Importiamo il tuo modulo custom

app = Flask(__name__)

# Inizializziamo il gestore audio (che creeremo tra poco)
audio_bot = AudioManager()

@app.route('/')
def home():
    # Questa rotta serve la pagina HTML principale
    return render_template('index.html')

@app.route('/api/start_recognition', methods=['POST'])
def start_recognition():
    # Questa è l'API che il Frontend chiamerà via JavaScript
    result = audio_bot.recognize_song()
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)