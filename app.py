import os
import re
import sqlite3
import base64
import uuid
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

DB_PATH = os.path.join(os.path.dirname(__file__), "kargo.db")
OCR_SPACE_API_KEY = os.environ.get("OCR_SPACE_API_KEY", "").strip()

PHONE_RE = re.compile(r"0?5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shipments (
            id TEXT PRIMARY KEY,
            name TEXT,
            address TEXT,
            phone TEXT,
            content TEXT,
            carrier TEXT,
            date TEXT,
            entered_by TEXT,
            photo TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/ocr", methods=["POST"])
def ocr():
    if not OCR_SPACE_API_KEY:
        return jsonify({"error": "OCR yapilandirilmamis (OCR_SPACE_API_KEY eksik)"}), 500

    file = request.files.get("photo")
    if not file:
        return jsonify({"error": "Fotograf gelmedi"}), 400

    image_bytes = file.read()
    if len(image_bytes) > 1024 * 1024:
        return jsonify({"error": "Fotograf cok buyuk (1MB limiti), lutfen tekrar dene"}), 400

    try:
        resp = requests.post(
            "https://api.ocr.space/parse/image",
            headers={"apikey": OCR_SPACE_API_KEY},
            files={"file": ("label.jpg", image_bytes, file.mimetype or "image/jpeg")},
            data={
                "language": "tur",
                "OCREngine": "2",
                "isOverlayRequired": "false",
                "scale": "true",
                "detectOrientation": "true",
            },
            timeout=30,
        )
    except Exception as e:
        app.logger.error("OCR.space istegine baglanilamadi: %s", e)
        return jsonify({"error": f"OCR servisine ulasilamadi: {e}"}), 502

    try:
        data = resp.json()
    except ValueError:
        app.logger.error("OCR.space gecersiz yanit dondu: %s", resp.text[:500])
        return jsonify({"error": "OCR servisi beklenmeyen bir yanit dondu"}), 502

    if data.get("IsErroredOnProcessing"):
        msg = data.get("ErrorMessage") or ["Bilinmeyen OCR hatasi"]
        msg = msg[0] if isinstance(msg, list) else msg
        app.logger.error("OCR.space hata: %s", msg)
        return jsonify({"error": msg}), 502

    parsed_results = data.get("ParsedResults") or []
    full_text = parsed_results[0].get("ParsedText", "") if parsed_results else ""
    full_text = full_text.strip()

    phone_match = PHONE_RE.search(full_text)
    phone = phone_match.group(0) if phone_match else ""

    return jsonify({"raw_text": full_text, "phone": phone})


@app.route("/api/shipments", methods=["GET"])
def list_shipments():
    conn = get_db()
    rows = conn.execute(
        "SELECT id,name,address,phone,content,carrier,date,entered_by,photo,created_at "
        "FROM shipments ORDER BY created_at DESC LIMIT 300"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/shipments", methods=["POST"])
def create_shipment():
    f = request.form
    photo_file = request.files.get("photo")
    photo_data_url = None
    if photo_file and photo_file.filename:
        mime = photo_file.mimetype or "image/jpeg"
        photo_data_url = f"data:{mime};base64," + base64.b64encode(photo_file.read()).decode("utf-8")

    record = {
        "id": str(uuid.uuid4()),
        "name": f.get("name", "").strip(),
        "address": f.get("address", "").strip(),
        "phone": f.get("phone", "").strip(),
        "content": f.get("content", "").strip(),
        "carrier": f.get("carrier", "").strip(),
        "date": f.get("date", "").strip(),
        "entered_by": f.get("entered_by", "").strip(),
        "photo": photo_data_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if not record["content"] or not record["carrier"]:
        return jsonify({"error": "Kargo icerigi ve kargo firmasi zorunlu"}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO shipments (id,name,address,phone,content,carrier,date,entered_by,photo,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            record["id"], record["name"], record["address"], record["phone"],
            record["content"], record["carrier"], record["date"], record["entered_by"],
            record["photo"], record["created_at"],
        ),
    )
    conn.commit()
    conn.close()
    return jsonify(record), 201


@app.route("/api/shipments/<shipment_id>", methods=["DELETE"])
def delete_shipment(shipment_id):
    conn = get_db()
    conn.execute("DELETE FROM shipments WHERE id=?", (shipment_id,))
    conn.commit()
    conn.close()
    return "", 204


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
