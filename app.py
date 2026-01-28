from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import os

from sqlalchemy import create_engine, text

app = Flask(__name__)
CORS(app)

# -------------------------
# Helpers
# -------------------------
def now_utc_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat()

def require_db_url():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("Falta DATABASE_URL en variables de entorno (Render).")
    return db_url

# -------------------------
# DB (Postgres)
# -------------------------
DATABASE_URL = require_db_url()

# pool_pre_ping ayuda a evitar conexiones muertas en Render
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Creamos tabla si no existe
# Guardamos: humedad, temperatura, timestamp (del sensor), ts_server (del servidor), zona
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lecturas (
  id SERIAL PRIMARY KEY,
  zona TEXT,
  temperatura DOUBLE PRECISION,
  humedad DOUBLE PRECISION,
  timestamp TEXT,
  ts_server TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

with engine.begin() as conn:
    conn.execute(text(CREATE_TABLE_SQL))

@app.get("/")
def home():
    return "API OK. Usa /api/datos y /api/historial"

# -------------------------
# GET último dato
# -------------------------
@app.get("/api/datos")
def get_datos():
    # Regresa la última lectura (la más reciente)
    sql = """
    SELECT zona, temperatura, humedad, timestamp, ts_server
    FROM lecturas
    ORDER BY id DESC
    LIMIT 1;
    """
    with engine.begin() as conn:
        row = conn.execute(text(sql)).mappings().first()

    if not row:
        return jsonify({"status": "sin_datos"}), 404

    return jsonify(dict(row))

# -------------------------
# GET historial (últimos N)
# -------------------------
@app.get("/api/historial")
def get_historial():
    n = int(request.args.get("n", "200"))

    sql = """
    SELECT zona, temperatura, humedad, timestamp, ts_server
    FROM lecturas
    ORDER BY id DESC
    LIMIT :n;
    """

    with engine.begin() as conn:
        rows = conn.execute(text(sql), {"n": n}).mappings().all()

    # lo devolvemos como lista de dicts
    return jsonify([dict(r) for r in rows])

# -------------------------
# POST guardar dato (inserta en BD)
# -------------------------
@app.post("/api/datos")
def post_datos():
    data = request.get_json(force=True) or {}

    # Normaliza campos esperados
    zona = data.get("zona", "Z1")
    temperatura = data.get("temperatura", None)
    humedad = data.get("humedad", None)
    timestamp = data.get("timestamp", None)   # lo que mande tu ESP32/script
    ts_server = data.get("ts_server", now_utc_iso())

    sql = """
    INSERT INTO lecturas (zona, temperatura, humedad, timestamp, ts_server)
    VALUES (:zona, :temperatura, :humedad, :timestamp, :ts_server)
    RETURNING id;
    """

    with engine.begin() as conn:
        new_id = conn.execute(
            text(sql),
            {
                "zona": zona,
                "temperatura": temperatura,
                "humedad": humedad,
                "timestamp": timestamp,
                "ts_server": ts_server,
            },
        ).scalar_one()

    return jsonify({"status": "ok", "id": new_id})

