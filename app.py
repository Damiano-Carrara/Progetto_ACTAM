from flask import Flask, render_template, jsonify, request, send_file
from audio_manager import AudioManager
from session_manager import SessionManager 
from report_generator import ReportGenerator
import atexit 
from datetime import datetime

app = Flask(__name__)

# Inizializziamo i nostri "robot"
audio_bot = AudioManager()
session_bot = SessionManager()
report_bot = ReportGenerator()

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
    playlist = session_bot.get_playlist()
    return jsonify({"playlist": playlist})

# --- API 4: CANCELLA ---
@app.route('/api/delete_song', methods=['POST'])
def delete_song():
    data = request.get_json()
    if session_bot.delete_song(data.get('id')):
        return jsonify({"status": "deleted"})
    return jsonify({"status": "error"})

# --- API 5: AGGIORNA/CREA BRANO (Review) ---
@app.route('/api/update_song', methods=['POST'])
def update_song():
    data = request.get_json()
    result = session_bot.update_song(data.get('id'), data)
    return jsonify(result)

# --- API 6: GENERA REPORT EXCEL ---
@app.route('/api/generate_report', methods=['GET'])
def generate_report():
    try:
        playlist = session_bot.get_playlist()
        excel_file = report_bot.generate_excel(playlist, metadata={"artist": "Export Borderò"})
        filename = f"Bordero_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return send_file(
            excel_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"❌ Errore generazione report: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- API 7: PDF UFFICIALE (stessi dati dell'Excel) ---
@app.route('/api/generate_pdf_official', methods=['GET'])
def generate_pdf_official():
    try:
        playlist = session_bot.get_playlist()
        pdf_file = report_bot.generate_pdf_official(
            playlist,
            metadata={"artist": "Export Borderò"}
        )
        filename = f"Bordero_ufficiale_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        return send_file(
            pdf_file,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"❌ Errore generazione PDF ufficiale: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- API 8: PDF LOG RICONOSCIUTO (raw) ---
@app.route('/api/generate_pdf_raw', methods=['GET'])
def generate_pdf_raw():
    try:
        playlist = session_bot.get_playlist()
        pdf_file = report_bot.generate_pdf_raw(
            playlist,
            metadata={"artist": "Export Borderò"}
        )
        filename = f"Bordero_log_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        return send_file(
            pdf_file,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"❌ Errore generazione PDF raw: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def cleanup_on_exit():
  audio_bot.stop_continuous_recognition()

atexit.register(cleanup_on_exit)

if __name__ == '__main__':
  app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)
