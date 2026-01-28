from flask import Flask, request, jsonify
import os, json
from datetime import datetime

app = Flask(__name__)

# Guardado simple en archivo (para pruebas). Luego podemos pasar a DB.
DATA_FILE = "datos_actuales.json"

@app.get("/")
def home():
    return "API OK. Usa /api/datos"

@app.get("/api/datos")
def get_datos():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"status": "sin_datos"}), 404

@app.post("/api/datos")
def post_datos():
    data = request.get_json(force=True)
    # agrega timestamp servidor si no viene
    data.setdefault("ts_server", datetime.utcnow().isoformat())
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return jsonify({"status": "ok"})
