from flask import Flask, request, jsonify
import os, json
from flask_cors import CORS
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
CORS(app)

DATA_FILE = Path("datos_actuales.json")
HIST_FILE = Path("historial.jsonl")  # JSON Lines (1 registro por línea)

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
    # devuelve los últimos N registros (por defecto 200)
    n = int(request.args.get("n", "200"))
    if not HIST_FILE.exists():
        return jsonify([])

    lines = HIST_FILE.read_text(encoding="utf-8").splitlines()
    last = lines[-n:] if n > 0 else lines
    data = [json.loads(x) for x in last if x.strip()]
    return jsonify(data)

@app.post("/api/datos")
def post_datos():
    data = request.get_json(force=True)
    data.setdefault("ts_server", now_utc())

    # guarda el último
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # agrega al historial (1 línea)
    with HIST_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

    return jsonify({"status": "ok"})



