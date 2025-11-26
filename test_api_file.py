import os
import time
import hmac
import hashlib
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

# Configurazione
file_path = "debug_recording.wav" # Il file che hai detto che si sente bene
host = os.getenv('ACR_HOST')
access_key = os.getenv('ACR_ACCESS_KEY')
access_secret = os.getenv('ACR_ACCESS_SECRET')

def test_upload():
    http_method = "POST"
    http_uri = "/v1/identify"
    data_type = "audio"
    signature_version = "1"
    timestamp = str(int(time.time()))

    string_to_sign = (http_method + "\n" + http_uri + "\n" + access_key + "\n" + data_type + "\n" + signature_version + "\n" + timestamp)
    sign = base64.b64encode(hmac.new(access_secret.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()).decode('ascii')

    f = open(file_path, "rb")
    file_size = os.path.getsize(file_path)

    files = {'sample': (file_path, f, 'audio/wav')}
    data = {
        'access_key': access_key,
        'sample_bytes': file_size,
        'timestamp': timestamp,
        'signature': sign,
        'data_type': data_type,
        "signature_version": signature_version
    }

    print(f"📡 Invio {file_path} ({file_size} bytes) a {host}...")
    req = requests.post(f"https://{host}/v1/identify", files=files, data=data)
    
    print("\n--- RISPOSTA COMPLETA DAL SERVER ---")
    print(req.text) # Vediamo il JSON grezzo
    f.close()

if __name__ == "__main__":
    test_upload()