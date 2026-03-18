import os
import glob
import wave
import json
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template

app = Flask(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────
OUTPUT_DIR  = os.path.expanduser("~/piper-outputs")
MODELS_DIR  = os.path.expanduser("~/piper-models")
PIPER_CACHE = os.path.expanduser("~/.cache/piper")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

# ─── Helpers ──────────────────────────────────────────────────────────────────
def find_all_onnx(search_dirs):
    found = []
    for d in search_dirs:
        d = os.path.expanduser(d)
        if os.path.isdir(d):
            for f in glob.glob(os.path.join(d, "**", "*.onnx"), recursive=True):
                found.append(f)
    return found

LANG_NAMES = {
    "af":"Afrikaans","ar":"Arabic","bn":"Bengali","ca":"Catalan",
    "cs":"Czech","cy":"Welsh","da":"Danish","de":"German",
    "el":"Greek","en":"English","es":"Spanish","fa":"Persian",
    "fi":"Finnish","fr":"French","gu":"Gujarati","hi":"Hindi",
    "hr":"Croatian","hu":"Hungarian","hy":"Armenian","id":"Indonesian",
    "is":"Icelandic","it":"Italian","ja":"Japanese","ka":"Georgian",
    "kk":"Kazakh","kn":"Kannada","ko":"Korean","lb":"Luxembourgish",
    "lt":"Lithuanian","lv":"Latvian","mk":"Macedonian","ml":"Malayalam",
    "mr":"Marathi","ms":"Malay","mt":"Maltese","ne":"Nepali",
    "nl":"Dutch","no":"Norwegian","pa":"Punjabi","pl":"Polish",
    "pt":"Portuguese","ro":"Romanian","ru":"Russian","sk":"Slovak",
    "sl":"Slovenian","sq":"Albanian","sr":"Serbian","sv":"Swedish",
    "sw":"Swahili","ta":"Tamil","te":"Telugu","th":"Thai","tr":"Turkish",
    "uk":"Ukrainian","ur":"Urdu","vi":"Vietnamese","zh":"Chinese"
}

def parse_voice(onnx_path):
    name       = Path(onnx_path).stem
    parts      = name.split("-")
    lang_code  = parts[0].lower()
    lang_short = lang_code.split("_")[0]
    region     = lang_code.split("_")[1].upper() if "_" in lang_code else ""
    speaker    = parts[1] if len(parts) > 1 else name
    quality    = parts[2] if len(parts) > 2 else "medium"
    lang_display = LANG_NAMES.get(lang_short, lang_short.upper())
    if region:
        lang_display += f" ({region})"
    return {
        "id": name, "path": onnx_path, "name": name,
        "speaker": speaker, "quality": quality,
        "language": lang_short, "language_display": lang_display,
        "has_config": os.path.exists(onnx_path + ".json")
    }

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config")
def get_config():
    return jsonify({"default_output_dir": OUTPUT_DIR, "default_models_dir": MODELS_DIR})

@app.route("/api/voices")
def list_voices():
    custom_dir = request.args.get("models_dir", MODELS_DIR)
    dirs = [custom_dir, PIPER_CACHE, MODELS_DIR]
    seen, voices = set(), []
    for path in find_all_onnx(dirs):
        if path not in seen:
            seen.add(path)
            voices.append(parse_voice(path))
    voices.sort(key=lambda v: (v["language"], v["name"]))
    return jsonify(voices)

@app.route("/api/generate", methods=["POST"])
def generate():
    data         = request.get_json()
    text         = data.get("text", "").strip()
    model_path   = data.get("model_path", "")
    out_dir      = os.path.expanduser(data.get("output_dir", OUTPUT_DIR))
    length_scale = float(data.get("length_scale", 1.0))
    noise_scale  = float(data.get("noise_scale", 0.667))
    noise_w      = float(data.get("noise_w", 0.8))
    speaker_id   = data.get("speaker_id", None)

    if not text:
        return jsonify({"error": "Text is empty"}), 400
    if not model_path or not os.path.exists(model_path):
        return jsonify({"error": f"Model not found: {model_path}"}), 400

    os.makedirs(out_dir, exist_ok=True)
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name    = f"{Path(model_path).stem}_{timestamp}.wav"
    out_path    = os.path.join(out_dir, out_name)
    config_path = model_path + ".json"

    try:
        from piper import PiperVoice
        voice = PiperVoice.load(
            model_path,
            config_path=config_path if os.path.exists(config_path) else None,
            use_cuda=False
        )
        with wave.open(out_path, "w") as wav_file:
            voice.synthesize(
                text, wav_file,
                length_scale=length_scale,
                noise_scale=noise_scale,
                noise_w=noise_w,
                speaker_id=int(speaker_id) if speaker_id is not None else None
            )
    except ImportError:
        import subprocess
        cmd = [
            "python", "-m", "piper",
            "--model", model_path,
            "--output_file", out_path,
            "--length_scale", str(length_scale),
            "--noise_scale", str(noise_scale),
            "--noise_w", str(noise_w),
        ]
        if os.path.exists(config_path):
            cmd += ["--config", config_path]
        if speaker_id is not None:
            cmd += ["--speaker", str(speaker_id)]
        try:
            r = subprocess.run(cmd, input=text.encode(), capture_output=True, timeout=180)
            if r.returncode != 0:
                return jsonify({"error": r.stderr.decode("utf-8", errors="replace")}), 500
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Timed out. Try shorter text."}), 500
        except FileNotFoundError:
            return jsonify({"error": "piper not found. Run: pip install piper-tts"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"success": True, "filename": out_name,
                    "path": out_path, "size": os.path.getsize(out_path)})

@app.route("/api/outputs")
def list_outputs():
    out_dir = os.path.expanduser(request.args.get("output_dir", OUTPUT_DIR))
    files = []
    if os.path.isdir(out_dir):
        for f in sorted(glob.glob(os.path.join(out_dir, "*.wav")), reverse=True):
            st = os.stat(f)
            files.append({"filename": os.path.basename(f), "size": st.st_size,
                           "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
    return jsonify(files)

@app.route("/api/audio/<filename>")
def serve_audio(filename):
    out_dir = os.path.expanduser(request.args.get("output_dir", OUTPUT_DIR))
    return send_from_directory(out_dir, filename)

@app.route("/api/delete/<filename>", methods=["DELETE"])
def delete_audio(filename):
    out_dir  = os.path.expanduser(request.args.get("output_dir", OUTPUT_DIR))
    filepath = os.path.join(out_dir, filename)
    if not os.path.abspath(filepath).startswith(os.path.abspath(out_dir)):
        return jsonify({"error": "Invalid path"}), 403
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({"success": True})
    return jsonify({"error": "File not found"}), 404

if __name__ == "__main__":
    print("\n🎙️  Piper TTS Studio")
    print(f"   Models : {MODELS_DIR}  +  ~/.cache/piper")
    print(f"   Output : {OUTPUT_DIR}")
    print(f"   Open   : http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
