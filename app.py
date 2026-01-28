from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
from pathlib import Path
import json

app = Flask(__name__)
CORS(app)

DATA_FILE = Path("datos_actuales.json")
HIST_FILE = Path("historial.jsonl")

def now_utc():
    return datetime.utcnow().isoformat()

@app.get("/")
def home():
    return "API OK. Usa /api/datos y /api/historial"

@app.get("/api/datos")
def get_datos():
    if DATA_FILE.exists():
        return jsonify(json.loads(DATA_FILE.read_text(encoding="utf-8")))
    return jsonify({"status": "sin_datos"}), 404

@app.get("/api/historial")
def get_historial():
    n = int(request.args.get("n", "200"))
    if not HIST_FILE.exists():
        return jsonify([])

    lines = HIST_FILE.read_text(encoding="utf-8").splitlines()
    data = [json.loads(x) for x in lines[-n:] if x.strip()]
    return jsonify(data)

@app.post("/api/datos")
def post_datos():
    data = request.get_json(force=True)
    data["ts_server"] = now_utc()

    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    with HIST_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

    return jsonify({"status": "ok"})

