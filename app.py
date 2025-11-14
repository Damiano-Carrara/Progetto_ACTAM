from flask import Flask, render_template, jsonify
from audio_manager import AudioManager
import atexit # Per fermare il monitoraggio all'uscita

app = Flask(__name__)
# Creiamo l'istanza globale
audio_bot = AudioManager()

@app.route('/')
def home():
    # Il file index.html non è stato modificato
    return render_template('index.html')

@app.route('/api/start_monitoring', methods=['POST'])
def start_monitoring():
    """
    AVVIA il processo di monitoraggio in background.
    Usa 8 secondi di registrazione e 5 di cooldown.
    """
    # Passiamo 8 (durata registrazione) e 5 (cooldown)
    result = audio_bot.start_monitoring(duration=8, cooldown=5)
    return jsonify(result)

@app.route('/api/stop_monitoring', methods=['POST'])
def stop_monitoring():
    """
    FERMA il processo di monitoraggio e restituisce l'elenco COMPLETO
    dei brani unici rilevati.
    """
    result = audio_bot.stop_monitoring()
    return jsonify(result)

@app.route('/api/get_results', methods=['GET'])
def get_results():
    """
    Controlla i risultati PARZIALI mentre il monitoraggio è attivo.
    """
    result = audio_bot.get_current_results()
    return jsonify(result)

# Funzione di pulizia:
# Se chiudiamo l'app (es. Ctrl+C), ferma il thread
def cleanup_on_exit():
    print("Uscita dall'app... Fermo il monitoraggio se attivo.")
    if audio_bot.is_monitoring:
        audio_bot.stop_monitoring()

atexit.register(cleanup_on_exit)

if __name__ == '__main__':
    # Disabilitiamo il reloader di debug
    # (il reloader può causare problemi con i thread)
    app.run(debug=False, use_reloader=False)