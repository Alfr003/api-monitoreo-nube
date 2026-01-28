from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
from zoneinfo import ZoneInfo
import csv
import io

app = Flask(__name__)
CORS(app)

DATA_FILE = Path("datos_actuales.json")
HIST_FILE = Path("historial.jsonl")  # JSON Lines

# -----------------------------
# Config tabla 5 días (cada 2h)
# -----------------------------
HORAS_2H = ["02:00","04:00","06:00","08:00","10:00","12:00","14:00","16:00","18:00","20:00","22:00","24:00"]
DOW_ES = ["Lun.", "Mar.", "Mié.", "Jue.", "Vie.", "Sáb.", "Dom."]

# -----------------------------
# Helpers tiempo
# -----------------------------
def now_utc_iso_z():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def get_local_tz():
    # En Render define TZ=America/Costa_Rica
    tzname = os.environ.get("TZ", "UTC")
    try:
        return ZoneInfo(tzname)
    except:
        return ZoneInfo("UTC")

def parse_ts(item: dict):
    """
    Intenta parsear timestamp en estos formatos:
    - "YYYY-MM-DD HH:MM:SS"
    - ISO: "YYYY-MM-DDTHH:MM:SS(.micro)(Z opcional)"
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

    # ISO (acepta Z al final)
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except:
        return None

def to_local_dt(item: dict):
    tz = get_local_tz()
    dt = parse_ts(item)
    if not dt:
        return None

    # si viene sin tz, asume UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    else:
        dt = dt.astimezone(tz)

    return dt

def bucket_hora_2h(dt_local: datetime) -> str:
    """
    Agrupa por bloque de 2 horas usando floor.
    00:00-01:59 -> 24:00 (misma fecha, por cómo está tu tabla)
    """
    h2 = (dt_local.hour // 2) * 2
    if h2 == 0:
        return "24:00"
    return f"{h2:02d}:00"

# -----------------------------
# Lectura eficiente JSONL
# -----------------------------
def iter_historial():
    """Itera historial.jsonl línea por línea."""
    if not HIST_FILE.exists():
        return
    with HIST_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except:
                continue

# -----------------------------
# Tabla 5 días (último dato de cada bloque 2h)
# -----------------------------
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

        dt_local = to_local_dt(item)
        if not dt_local:
            continue

        fecha_str = dt_local.date().isoformat()
        if fecha_str not in fechas_str:
            continue

        bucket = bucket_hora_2h(dt_local)
        key = (fecha_str, bucket)

        prev = best.get(key)
        if (prev is None) or (dt_local > prev[0]):
            best[key] = (dt_local, item)

    for (fecha_str, bucket), (dt_local, item) in best.items():
        d_index = fechas_str.index(fecha_str)
        t = item.get("temperatura")
        h = item.get("humedad")
        if t is None or h is None:
            continue

        celdas[bucket][d_index] = {
            "t": float(t),
            "h": float(h),
            "ts": dt_local.isoformat()
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
    return "API OK. Usa /api/datos, /api/historial, /api/historial_resumen, /api/historial_filtro, /api/historial_export y /api/historicos"

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
    out = []
    for x in lines[-n:]:
        x = x.strip()
        if not x:
            continue
        try:
            out.append(json.loads(x))
        except:
            continue
    return jsonify(out)

@app.get("/api/historial_resumen")
def historial_resumen():
    """
    Devuelve meses/días disponibles para filtros.
    """
    meses = set()
    dias_por_mes = {}  # "YYYY-MM" -> set("YYYY-MM-DD")

    for item in iter_historial():
        dt = to_local_dt(item)
        if not dt:
            continue
        ym = dt.strftime("%Y-%m")
        ymd = dt.strftime("%Y-%m-%d")

        meses.add(ym)
        dias_por_mes.setdefault(ym, set()).add(ymd)

    meses = sorted(list(meses))
    dias_por_mes_out = {k: sorted(list(v)) for k, v in dias_por_mes.items()}

    return jsonify({
        "meses": meses,
        "dias_por_mes": dias_por_mes_out
    })

@app.get("/api/historial_filtro")
def historial_filtro():
    """
    Filtros:
      - zona=Z1
      - mes=YYYY-MM (opcional)
      - dia=YYYY-MM-DD (opcional)
      - hora=HH (opcional, 00-23)
      - n=5000 (límite opcional)
    """
    zona = request.args.get("zona", "Z1")
    mes = request.args.get("mes")        # "2026-01"
    dia = request.args.get("dia")        # "2026-01-28"
    hora = request.args.get("hora")      # "11"
    n = int(request.args.get("n", "5000"))

    out = []
    for item in iter_historial():
        if item.get("zona", "Z1") != zona:
            continue

        dt = to_local_dt(item)
        if not dt:
            continue

        if mes and dt.strftime("%Y-%m") != mes:
            continue
        if dia and dt.strftime("%Y-%m-%d") != dia:
            continue
        if hora and dt.strftime("%H") != hora.zfill(2):
            continue

        out.append({
            "fecha": dt.strftime("%Y-%m-%d"),
            "hora": dt.strftime("%H:%M"),
            "temperatura": item.get("temperatura"),
            "humedad": item.get("humedad"),
            "zona": item.get("zona", "Z1"),
            "ts": dt.isoformat()
        })

        if len(out) >= n:
            break

    # Más reciente arriba
    out.sort(key=lambda x: x["ts"], reverse=True)
    return jsonify(out)

@app.get("/api/historial_export")
def historial_export():
    """
    Exporta CSV (Excel compatible). Params:
      - zona=Z1
      - mes=YYYY-MM (opcional)
    Si no mandas mes => exporta TODO.
    """
    zona = request.args.get("zona", "Z1")
    mes = request.args.get("mes")  # opcional

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["fecha", "hora", "temperatura", "humedad", "zona"])

    for item in iter_historial():
        if item.get("zona", "Z1") != zona:
            continue

        dt = to_local_dt(item)
        if not dt:
            continue

        if mes and dt.strftime("%Y-%m") != mes:
            continue

        writer.writerow([
            dt.strftime("%Y-%m-%d"),
            dt.strftime("%H:%M"),
            item.get("temperatura", ""),
            item.get("humedad", ""),
            item.get("zona", "Z1")
        ])

    filename = f"historial_{zona}_{mes if mes else 'TODO'}.csv"
    resp = Response(output.getvalue(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

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
    data["ts_server"] = now_utc_iso_z()

    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    with HIST_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    # En Render NO se usa normalmente esto; Render usa gunicorn.
    # Pero local sí sirve:
    app.run(host="0.0.0.0", port=5000, debug=True)
