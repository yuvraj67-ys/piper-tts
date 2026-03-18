import os
import subprocess
import time
from flask import Flask, render_template, request, jsonify, send_from_directory

app = Flask(__name__)
OUTPUT_DIR = "static/outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Yahan humne languages aur unke models define kiye hain (Piper ke default models)
MODELS = {
    "English": ["en_US-lessac-medium", "en_US-amy-medium", "en_GB-alan-medium"],
    "Hindi": ["hi_IN-swara-medium", "hi_IN-amit-medium"],
    "Spanish": ["es_ES-carlota-x_low"],
    "French": ["fr_FR-siwis-medium"]
}

@app.route('/')
def index():
    return render_template('index.html', models=MODELS)

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    text = data.get('text', '')
    model = data.get('model', 'en_US-lessac-medium')
    
    if not text:
        return jsonify({'error': 'Text is empty!'}), 400

    # File ka naam generate karna
    filename = f"audio_{int(time.time())}.wav"
    filepath = os.path.join(OUTPUT_DIR, filename)

    try:
        # Piper ko call karne ki command (Text limit nahi hai kyunki stdin se bhej rahe hain)
        process = subprocess.Popen(
            ['piper', '-m', model, '-f', filepath],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        process.communicate(input=text.encode('utf-8'))
        
        return jsonify({'success': True, 'filename': filename, 'path': f'/{filepath}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/files', methods=['GET'])
def list_files():
    files = sorted(os.listdir(OUTPUT_DIR), reverse=True)
    return jsonify({'files': files})

@app.route('/delete', methods=['POST'])
def delete_file():
    filename = request.json.get('filename')
    filepath = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404

if __name__ == '__main__':
    # Localhost par run karega (Phone ke browser ke liye)
    app.run(host='0.0.0.0', port=5000, debug=True)
