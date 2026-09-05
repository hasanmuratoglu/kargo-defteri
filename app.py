import os
import re
import sqlite3
import base64
import uuid
from io import BytesIO
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, request, jsonify, send_from_directory
from openpyxl import Workbook

from tr_locations import TR_LOCATIONS, TR_PROVINCES

app = Flask(__name__, static_folder="static", static_url_path="")

DB_PATH = os.path.join(os.path.dirname(__file__), "kargo.db")
OCR_SPACE_API_KEY = os.environ.get("OCR_SPACE_API_KEY", "").strip()
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
REPORT_TO_EMAIL = os.environ.get("REPORT_TO_EMAIL", "").strip()
CRON_SECRET = os.environ.get("CRON_SECRET", "").strip()


def tr_lower(s):
    """Turkce I/i karakterlerini dogru sekilde kucult (Python'un varsayilan
    .lower() metodu Turkce'de yanlis sonuc verir: 'İstanbul' -> 'i̇stanbul')."""
    return s.replace("İ", "i").replace("I", "ı").lower()


# Telefon: basinda 0 varsa toplam 11 hane (0 + 5xx xxx xx xx),
# yoksa toplam 10 hane (5xx xxx xx xx). Bosluk/tire serbest.
PHONE_CANDIDATE_RE = re.compile(r"0?5[\d\s.\-]{8,14}")

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
STARTS_UPPER_RE = re.compile(r"^[A-ZÇĞİÖŞÜ]")

# Isim ararken sadece metnin en basindaki bu kadar satira bakiyoruz - isim
# pratikte hemen hemen hep en ustte oluyor, adresin ortasindaki buyuk harfli
# bir kelimeyi (semt/sokak adi gibi) isim sanma riskini azaltir.
NAME_SEARCH_WINDOW = 3


def extract_phone(raw_text):
    """0 ile basliyorsa 11 hane, baslamiyorsa 10 hane kuralina gore telefon bulur."""
    for m in PHONE_CANDIDATE_RE.finditer(raw_text):
        candidate = m.group(0)
        digits = re.sub(r"\D", "", candidate)
        if digits.startswith("05") and len(digits) == 11:
            return candidate.strip()
        if digits.startswith("5") and len(digits) == 10:
            return candidate.strip()
    return ""


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
    # Isim buyuk harfle baslar (Title Case ya da TAMAMEN BUYUK olabilir).
    if not STARTS_UPPER_RE.match(line):
        return False
    # Her kelime alfabetik olmali (Unicode-uyumlu: OCR'in bazen yanlis okudugu
    # aksanli harfleri de - 'Fevrí' gibi - kabul eder, rakam/sembol icermez).
    for w in words:
        core = w.strip(".,'’-")
        if core and not core.isalpha():
            return False
    # Bilinen bir il/ilce adiyla eslesen kelime iceren satirlar isim degildir.
    if any(tr_lower(w.strip(".,")) in TR_LOCATIONS for w in words):
        return False
    return True


def guess_fields(raw_text):
    """Ham OCR metninden isim/adres/telefonu KURAL TABANLI tahmin eder.
    Yapay zeka degil - basit satir/kelime eslesmesi. Kullanici her zaman
    duzeltebilir, bu yuzden yanlis tahmin ciddi bir sorun degil.

    Kurallar:
    - Telefon: 0 ile basliyorsa 11, baslamiyorsa 10 haneli rakam dizisi.
    - Isim: metnin en basinda (ilk birkac satirda), buyuk harfle baslayan,
      rakamsiz, adres kelimesi/il-ilce adi icermeyen 1-4 kelimelik satir.
      "Alici" gibi bir anahtar kelime varsa o kesin oncelikli.
    - Adres: isim ve telefon satirlari haric, metnin basindan ilk IL adi
      gecen satira kadar (o satir dahil) olan her sey - cunku adreste il
      adi normalde en sonda yazilir.
    """
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    phone = extract_phone(raw_text)

    def is_phone_line(line):
        return bool(extract_phone(line)) and len(line.replace(" ", "")) <= 15

    def is_id_line(line):
        return bool(ID_LINE_RE.match(line.replace(" ", "")))

    # Isim/adres icin degerlendirilecek satirlar: telefon ve TC-kimlik gibi
    # sadece rakamdan olusan satirlari disarida birakiyoruz.
    content_lines = [l for l in lines if not is_phone_line(l) and not is_id_line(l)]

    name = ""
    name_index = None

    # 1. yol: "alici" gibi bir anahtar kelime var mi? (tum metinde aranir)
    for i, line in enumerate(content_lines):
        low = line.lower()
        matched_kw = next((k for k in NAME_KEYWORDS if k in low), None)
        if matched_kw:
            idx = low.find(matched_kw)
            after = line[idx + len(matched_kw):].strip(" :.-")
            if after:
                name = after
                name_index = i
            elif i + 1 < len(content_lines):
                name = content_lines[i + 1]
                name_index = i + 1
            break

    # 2. yol (yedek): anahtar kelime yoksa, isim genelde telefon numarasindan
    # ONCE yazilir (Isim -> Telefon -> Adres siralamasi yaygin). Once telefonun
    # orijinal metindeki konumunu bul, isim aramasini o noktadan oncesiyle
    # sinirla; telefon bulunamadiysa metnin en basindaki birkac satira bak.
    if not name:
        phone_line_index = None
        if phone:
            for i, line in enumerate(lines):
                if extract_phone(line) == phone:
                    phone_line_index = i
                    break

        if phone_line_index is not None:
            search_lines = [l for l in lines[:phone_line_index] if not is_id_line(l)]
        else:
            search_lines = content_lines[:NAME_SEARCH_WINDOW]

        for line in search_lines:
            if looks_like_name(line):
                name = line
                # content_lines icindeki karsilik gelen indeksi bul (adres
                # olusturma asamasinda bu satiri haric tutabilmek icin).
                if line in content_lines:
                    name_index = content_lines.index(line)
                break

    # Adres: basindan, ilk IL adi gecen satira kadar (dahil).
    province_index = None
    for i, line in enumerate(content_lines):
        if i == name_index:
            continue
        words = [w.strip(".,") for w in line.split()]
        if any(tr_lower(w) in TR_PROVINCES for w in words):
            province_index = i
            break

    address_lines = []
    for i, line in enumerate(content_lines):
        if i == name_index:
            continue
        if any(k in line.lower() for k in NAME_KEYWORDS):
            continue
        if "kart sahibi" in line.lower():
            continue
        if province_index is not None and i > province_index:
            break  # il satirindan sonrasini adres sayma
        address_lines.append(line)
        if i == province_index:
            break

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


def build_excel(records):
    """Kayitlardan bir .xlsx dosyasi (bytes) uretir."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Kargolar"
    headers = ["Tarih", "Alici", "Adres", "Telefon", "Icerik", "Kargo Firmasi", "Giren Kisi", "Kayit Zamani"]
    ws.append(headers)
    for r in records:
        ws.append([
            r.get("date", ""),
            r.get("name", ""),
            r.get("address", ""),
            r.get("phone", ""),
            r.get("content", ""),
            r.get("carrier", ""),
            r.get("entered_by", ""),
            r.get("created_at", ""),
        ])
    widths = [12, 20, 40, 15, 28, 16, 14, 22]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def send_report_email(excel_bytes, record_count, day_str):
    """Resend'in HTTPS API'si uzerinden mail gonderir (SMTP portlari Render'in
    ucretsiz planinda engelli oldugu icin klasik SMTP calismiyor)."""
    payload = {
        "from": f"Kargo Defteri <{RESEND_FROM_EMAIL}>",
        "to": [REPORT_TO_EMAIL],
        "subject": f"Kargo Defteri - {day_str} Gunluk Rapor ({record_count} kayit)",
        "text": (
            f"{day_str} tarihine ait {record_count} kargo kaydi ektedir.\n\n"
            "Bu e-posta Kargo Defteri uygulamasi tarafindan otomatik gonderilmistir."
        ),
        "attachments": [
            {
                "filename": f"kargo-defteri-{day_str}.xlsx",
                "content": base64.b64encode(excel_bytes).decode("ascii"),
            }
        ],
    }
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Resend API hatasi ({resp.status_code}): {resp.text[:300]}")


@app.route("/api/close-day", methods=["POST"])
def close_day():
    """Gunu kapatir: tum kayitlari Excel'e dokup mail atar, sonra veritabanini
    temizler. Sadece dogru 'secret' (CRON_SECRET) ile cagrilabilir - bu uc
    nokta veri silen bir islem yaptigi icin herkese acik birakilmamali."""
    secret = request.args.get("secret", "")
    if not CRON_SECRET or secret != CRON_SECRET:
        return jsonify({"error": "Yetkisiz"}), 403

    if not RESEND_API_KEY or not REPORT_TO_EMAIL:
        return jsonify({"error": "E-posta ayarlari eksik (RESEND_API_KEY / REPORT_TO_EMAIL)"}), 500

    conn = get_db()
    rows = conn.execute(
        "SELECT date,name,address,phone,content,carrier,entered_by,created_at "
        "FROM shipments ORDER BY created_at ASC"
    ).fetchall()
    records = [dict(r) for r in rows]

    # Sunucu saati UTC oluyor (Render), Turkiye sabit UTC+3 (2016'dan beri
    # yaz saati uygulamiyor) - tarihi buna gore hesapla.
    turkey_time = datetime.now(timezone.utc) + timedelta(hours=3)
    day_str = turkey_time.strftime("%d.%m.%Y")

    if not records:
        conn.close()
        return jsonify({"message": "Kayit yok, mail gonderilmedi.", "count": 0})

    try:
        excel_bytes = build_excel(records)
        send_report_email(excel_bytes, len(records), day_str)
    except Exception as e:
        conn.close()
        app.logger.error("Gun kapatma - mail gonderilemedi: %s", e)
        return jsonify({"error": f"Mail gonderilemedi, kayitlar SILINMEDI: {e}"}), 502

    conn.execute("DELETE FROM shipments")
    conn.commit()
    conn.close()

    return jsonify({"message": "Gun kapatildi, mail gonderildi, kayitlar silindi.", "count": len(records)})


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
