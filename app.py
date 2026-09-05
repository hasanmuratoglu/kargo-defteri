import os
import re
import io
import sqlite3
import base64
import uuid
from datetime import datetime, timezone

import numpy as np
from PIL import Image
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

DB_PATH = os.path.join(os.path.dirname(__file__), "kargo.db")

PHONE_RE = re.compile(r"0?5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}")

# EasyOCR okuyucusu ilk kullanımda yükleniyor (biraz zaman alabilir),
# sonraki her istekte hazır bulunuyor - her seferinde yeniden yüklenmiyor.
_reader = None


def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        app.logger.info("EasyOCR modeli yukleniyor (ilk calistirmada biraz surer)...")
        _reader = easyocr.Reader(["tr", "en"], gpu=False)
        app.logger.info("EasyOCR modeli hazir.")
    return _reader


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
    file = request.files.get("photo")
    if not file:
        return jsonify({"error": "Fotograf gelmedi"}), 400

    image_bytes = file.read()

    try:
        reader = get_reader()
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_np = np.array(img)
        lines = reader.readtext(img_np, detail=0, paragraph=True)
        full_text = "\n".join(lines)
    except Exception as e:
        app.logger.error("EasyOCR hatasi: %s", e)
        return jsonify({"error": f"OCR calisirken hata olustu: {e}"}), 500

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
