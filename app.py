import os
import subprocess
import json
import glob
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template, send_from_directory
from datetime import datetime

app = Flask(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/piper-outputs")
DEFAULT_MODELS_DIR = os.path.expanduser("~/piper-models")

os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
os.makedirs(DEFAULT_MODELS_DIR, exist_ok=True)

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/voices")
def list_voices():
    """Scan models directory for .onnx voice files"""
    models_dir = request.args.get("models_dir", DEFAULT_MODELS_DIR)
    models_dir = os.path.expanduser(models_dir)

    voices = []
    if os.path.isdir(models_dir):
        for onnx_file in glob.glob(os.path.join(models_dir, "**", "*.onnx"), recursive=True):
            name = Path(onnx_file).stem  # e.g. en_US-lessac-medium
            config_file = onnx_file + ".json"

            # Parse language from filename pattern: lang_REGION-speaker-quality
            parts = name.replace("-", "_", 1).split("-")
            lang_code = parts[0] if parts else "unknown"
            lang_region = lang_code.split("_")
            language = lang_region[0].upper() if lang_region else "Unknown"
            region = lang_region[1] if len(lang_region) > 1 else ""

            # Try to read config for more info
            speaker = parts[1] if len(parts) > 1 else name
            quality = parts[2] if len(parts) > 2 else "medium"

            # Language display names
            lang_names = {
                "en": "English", "de": "German", "es": "Spanish", "fr": "French",
                "it": "Italian", "nl": "Dutch", "pt": "Portuguese", "ru": "Russian",
                "zh": "Chinese", "ar": "Arabic", "cs": "Czech", "da": "Danish",
                "fi": "Finnish", "hu": "Hungarian", "ka": "Georgian", "lb": "Luxembourgish",
                "ne": "Nepali", "no": "Norwegian", "pl": "Polish", "sk": "Slovak",
                "sl": "Slovenian", "sr": "Serbian", "sv": "Swedish", "sw": "Swahili",
                "tr": "Turkish", "uk": "Ukrainian", "vi": "Vietnamese",
                "hi": "Hindi", "bn": "Bengali", "kn": "Kannada", "ml": "Malayalam",
                "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "gu": "Gujarati",
                "pa": "Punjabi", "ur": "Urdu"
            }

            lang_display = lang_names.get(language.lower(), language)
            if region:
                lang_display += f" ({region})"

            voices.append({
                "id": name,
                "path": onnx_file,
                "name": name,
                "speaker": speaker,
                "quality": quality,
                "language": language.lower(),
                "language_display": lang_display,
                "region": region,
                "has_config": os.path.exists(config_file)
            })

    voices.sort(key=lambda v: (v["language"], v["name"]))
    return jsonify(voices)


@app.route("/api/generate", methods=["POST"])
def generate():
    """Run piper TTS and save audio file"""
    data = request.get_json()
    text = data.get("text", "").strip()
    model_path = data.get("model_path", "")
    output_dir = data.get("output_dir", DEFAULT_OUTPUT_DIR)
    output_dir = os.path.expanduser(output_dir)
    speaker_id = data.get("speaker_id", None)
    length_scale = data.get("length_scale", 1.0)   # speech speed
    noise_scale = data.get("noise_scale", 0.667)
    noise_w = data.get("noise_w", 0.8)

    if not text:
        return jsonify({"error": "Text is empty"}), 400
    if not model_path or not os.path.exists(model_path):
        return jsonify({"error": f"Model not found: {model_path}"}), 400

    os.makedirs(output_dir, exist_ok=True)

    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_name = Path(model_path).stem
    out_filename = f"{model_name}_{timestamp}.wav"
    out_path = os.path.join(output_dir, out_filename)

    # Build piper command
    cmd = [
        "piper",
        "--model", model_path,
        "--output_file", out_path,
        "--length_scale", str(length_scale),
        "--noise_scale", str(noise_scale),
        "--noise_w", str(noise_w),
    ]

    config_path = model_path + ".json"
    if os.path.exists(config_path):
        cmd += ["--config", config_path]

    if speaker_id is not None:
        cmd += ["--speaker", str(speaker_id)]

    try:
        result = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=120
        )
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")
            return jsonify({"error": f"Piper error: {err}"}), 500

        file_size = os.path.getsize(out_path)
        return jsonify({
            "success": True,
            "filename": out_filename,
            "path": out_path,
            "size": file_size,
            "timestamp": timestamp
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Generation timed out (120s). Try shorter text."}), 500
    except FileNotFoundError:
        return jsonify({"error": "'piper' command not found. Make sure piper is installed and in PATH."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/outputs")
def list_outputs():
    """List generated audio files"""
    output_dir = request.args.get("output_dir", DEFAULT_OUTPUT_DIR)
    output_dir = os.path.expanduser(output_dir)

    files = []
    if os.path.isdir(output_dir):
        for f in sorted(glob.glob(os.path.join(output_dir, "*.wav")), reverse=True):
            stat = os.stat(f)
            files.append({
                "filename": os.path.basename(f),
                "path": f,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            })
    return jsonify(files)


@app.route("/api/audio/<path:filename>")
def serve_audio(filename):
    """Stream audio file for playback"""
    output_dir = request.args.get("output_dir", DEFAULT_OUTPUT_DIR)
    output_dir = os.path.expanduser(output_dir)
    return send_from_directory(output_dir, filename)


@app.route("/api/delete/<path:filename>", methods=["DELETE"])
def delete_audio(filename):
    """Delete an audio file"""
    output_dir = request.args.get("output_dir", DEFAULT_OUTPUT_DIR)
    output_dir = os.path.expanduser(output_dir)
    filepath = os.path.join(output_dir, filename)

    # Safety check — only delete from output dir
    if not os.path.abspath(filepath).startswith(os.path.abspath(output_dir)):
        return jsonify({"error": "Invalid path"}), 403

    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({"success": True})
    return jsonify({"error": "File not found"}), 404


@app.route("/api/config")
def get_config():
    return jsonify({
        "default_output_dir": DEFAULT_OUTPUT_DIR,
        "default_models_dir": DEFAULT_MODELS_DIR
    })


if __name__ == "__main__":
    print("\n🎙️  Piper TTS Web UI")
    print(f"   Models dir : {DEFAULT_MODELS_DIR}")
    print(f"   Output dir : {DEFAULT_OUTPUT_DIR}")
    print(f"   Open       : http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
