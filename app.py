from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
from zoneinfo import ZoneInfo

app = Flask(__name__)
CORS(app)

DATA_FILE = Path("datos_actuales.json")
HIST_FILE = Path("historial.jsonl")  # JSON Lines

# -----------------------------
# Config tabla 5 días
# -----------------------------
HORAS_2H = ["02:00","04:00","06:00","08:00","10:00","12:00","14:00","16:00","18:00","20:00","22:00","24:00"]
DOW_ES = ["Lun.", "Mar.", "Mié.", "Jue.", "Vie.", "Sáb.", "Dom."]

from datetime import datetime, timezone

def now_utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_ts(item: dict):
    """
    Intenta parsear timestamp en estos formatos comunes:
    - "YYYY-MM-DD HH:MM:SS"
    - ISO: "YYYY-MM-DDTHH:MM:SS(.micro)"
    """
    s = item.get("timestamp") or item.get("ts_server")
    if not s:
        return None

    s = str(s).strip()

    # "YYYY-MM-DD HH:MM:SS"
    try:
        if "T" not in s and len(s) >= 19 and s[10] == " ":
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except:
        pass

    # ISO
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except:
        return None

def get_local_tz():
    # En Render define TZ=America/Costa_Rica
    tzname = os.environ.get("TZ", "UTC")
    try:
        return ZoneInfo(tzname)
    except:
        return ZoneInfo("UTC")

def bucket_hora_2h(dt_local: datetime) -> str:
    """
    Agrupa por bloque de 2 horas usando floor.
    00:00-01:59 -> 24:00 (misma fecha, por cómo está tu tabla)
    """
    h2 = (dt_local.hour // 2) * 2
    if h2 == 0:
        return "24:00"
    return f"{h2:02d}:00"

def build_tabla_5dias(zona: str, days: int = 5, max_lines: int = 8000):
    tz = get_local_tz()
    today = datetime.now(tz).date()

    fechas = [today - timedelta(days=(days - 1 - i)) for i in range(days)]  # viejo->nuevo
    fechas_str = [d.isoformat() for d in fechas]

    celdas = {h: [None] * days for h in HORAS_2H}

    if not HIST_FILE.exists():
        return {
            "zona": zona,
            "fechas": fechas_str,
            "dias": [f"{DOW_ES[d.weekday()]} {d.day:02d}" for d in fechas],
            "horas": HORAS_2H,
            "celdas": celdas
        }

    lines = HIST_FILE.read_text(encoding="utf-8").splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]

    best = {}  # (fecha_str, bucket) -> (dt_local, item)

    for ln in lines:
        if not ln.strip():
            continue
        try:
            item = json.loads(ln)
        except:
            continue

        if item.get("zona", "Z1") != zona:
            continue

        dt = parse_ts(item)
        if not dt:
            continue

        # si dt viene sin tz: asumimos UTC y convertimos a local
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
        else:
            dt = dt.astimezone(tz)

        fecha_str = dt.date().isoformat()
        if fecha_str not in fechas_str:
            continue

        bucket = bucket_hora_2h(dt)
        key = (fecha_str, bucket)

        prev = best.get(key)
        if (prev is None) or (dt > prev[0]):
            best[key] = (dt, item)

    for (fecha_str, bucket), (dt, item) in best.items():
        d_index = fechas_str.index(fecha_str)
        t = item.get("temperatura")
        h = item.get("humedad")
        if t is None or h is None:
            continue

        celdas[bucket][d_index] = {
            "t": float(t),
            "h": float(h),
            "ts": dt.isoformat()
        }

    return {
        "zona": zona,
        "fechas": fechas_str,
        "dias": [f"{DOW_ES[d.weekday()]} {d.day:02d}" for d in fechas],
        "horas": HORAS_2H,
        "celdas": celdas
    }

# -----------------------------
# Rutas
# -----------------------------
@app.get("/")
def home():
    return "API OK. Usa /api/datos, /api/historial y /api/historicos"

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

@app.get("/api/historicos")
def get_historicos_5dias():
    zona = request.args.get("zona", "Z1")
    return jsonify(build_tabla_5dias(zona=zona, days=5))

@app.post("/api/datos")
def post_datos():
    # ✅ Seguridad: si existe API_KEY en Render, exige header X-API-KEY
    api_key = os.environ.get("API_KEY")
    if api_key:
        incoming = request.headers.get("X-API-KEY", "")
        if incoming != api_key:
            return jsonify({"status": "forbidden"}), 403

    data = request.get_json(force=True)

    # defaults y sello del server
    data.setdefault("zona", "Z1")
    data.setdefault("timestamp", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    data["ts_server"] = now_utc()

    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    with HIST_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)


