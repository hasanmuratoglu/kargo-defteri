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
NAME_KEYWORDS = ["alıcı", "alici", "ad soyad", "isim soyisim", "gönderilen"]
ID_LINE_RE = re.compile(r"^[\d\s]{9,20}$")  # TC kimlik no gibi sadece rakamlardan olusan satirlar

# Bir satirin "adres" oldugunu dusundurten kelimeler - bunlardan biri gecen
# satir isim adayi olarak degerlendirilmez.
ADDRESS_KEYWORD_RE = re.compile(
    r"\b(mah|mahalle|mahallesi|cad|cadde|sokak|sok|kat|daire|apt|apartman|"
    r"blok|köy|belde|ilçe|sitesi|bulvar|bulvarı|no)\b",
    re.IGNORECASE,
)
NAME_LINE_RE = re.compile(r"^[A-Za-zÇĞİÖŞÜçğıöşü'’\-\. ]+$")


def looks_like_name(line):
    """Bir satirin isim-soyisim gibi gorunup gorunmedigini kaba kurallarla tahmin eder."""
    if re.search(r"\d", line):
        return False
    words = line.split()
    if not (1 <= len(words) <= 4):
        return False
    if ADDRESS_KEYWORD_RE.search(line):
        return False
    if "kart sahibi" in line.lower():
        return False
    if not NAME_LINE_RE.match(line):
        return False
    return True


def guess_fields(raw_text):
    """Ham OCR metninden isim/adres/telefonu KURAL TABANLI tahmin eder.
    Yapay zeka degil - basit satir/kelime eslesmesi. Kullanici her zaman
    duzeltebilir, bu yuzden yanlis tahmin ciddi bir sorun degil."""
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    phone_match = PHONE_RE.search(raw_text)
    phone = phone_match.group(0) if phone_match else ""

    name = ""
    name_line_index = None

    # 1. yol: "alici" gibi bir anahtar kelime var mi?
    for i, line in enumerate(lines):
        low = line.lower()
        matched_kw = next((k for k in NAME_KEYWORDS if k in low), None)
        if matched_kw:
            idx = low.find(matched_kw)
            after = line[idx + len(matched_kw):].strip(" :.-")
            if after:
                name = after
                name_line_index = i
            elif i + 1 < len(lines):
                name = lines[i + 1]
                name_line_index = i + 1
            break

    # 2. yol (yedek): anahtar kelime yoksa, "isim gibi gorunen" ilk satiri sec
    if not name:
        for i, line in enumerate(lines):
            if PHONE_RE.fullmatch(line.replace(" ", "")):
                continue
            if ID_LINE_RE.match(line.replace(" ", "")):
                continue
            if looks_like_name(line):
                name = line
                name_line_index = i
                break

    address_lines = []
    for i, line in enumerate(lines):
        low = line.lower()
        if i == name_line_index:
            continue
        if any(k in low for k in NAME_KEYWORDS):
            continue
        if "kart sahibi" in low:
            continue
        if PHONE_RE.fullmatch(line.replace(" ", "")):
            continue
        if ID_LINE_RE.match(line.replace(" ", "")):
            continue
        address_lines.append(line)

    address = "\n".join(address_lines).strip()
    return name, address, phone


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

    name_guess, address_guess, phone = guess_fields(full_text)

    return jsonify({
        "raw_text": full_text,
        "name": name_guess,
        "address": address_guess,
        "phone": phone,
    })


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


@app.route("/api/verify-address", methods=["POST"])
def verify_address():
    body = request.get_json(silent=True) or {}
    address = (body.get("address") or "").strip()
    if not address:
        return jsonify({"error": "Adres bos olamaz"}), 400

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": address,
                "format": "json",
                "addressdetails": 1,
                "limit": 1,
                "countrycodes": "tr",
            },
            headers={"User-Agent": "kargo-defteri-dukkan-uygulamasi/1.0"},
            timeout=15,
        )
        results = resp.json()
    except Exception as e:
        app.logger.error("Adres dogrulama hatasi: %s", e)
        return jsonify({"error": f"Adres dogrulama servisine ulasilamadi: {e}"}), 502

    if results:
        top = results[0]
        return jsonify({
            "found": True,
            "display_name": top.get("display_name", ""),
        })
    return jsonify({"found": False})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
