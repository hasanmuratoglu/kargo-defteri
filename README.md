# Kargo Defteri

Dükkan içi kargo takibi için bağımsız web uygulaması. Flask backend + SQLite veritabanı
+ OCR.space (ücretsiz, kart/faturalandırma gerektirmeyen bir OCR API'si).

## Nasıl çalışır

- Fotoğraf çekilir → backend, OCR.space API'ye gönderir → etikette geçen yazı okunup
  ekrana dökülür (telefon numarası otomatik yakalanmaya çalışılır).
- Bu bir ham metin dökümüdür — "bu isim, bu adres" diye akıllı ayrıştırma yapmaz.
  Okunan metinden ilgili kısmı isim/adres kutularına kopyalarsın.
- Kayıtlar SQLite veritabanında (`kargo.db`) tutulur, herkes aynı listeyi görür.
- Liste sayfası her 4 saniyede bir kendini yeniler (gerçek zamanlı değil ama pratikte
  yeterince hızlı).

## Neden OCR.space?

- **Kart/faturalandırma hesabı istemiyor** — sadece e-posta ile ücretsiz anahtar alınıyor.
- **Ücretsiz kota:** ayda 25.000 istek (dükkanının ihtiyacının çok üzerinde).
- **Hafif:** Google Vision kadar akıllı değil, EasyOCR gibi kendi sunucunda ağır bir
  yapay zeka modeli çalıştırmıyor (bu yüzden Render'ın ücretsiz/düşük RAM'li planında
  sorunsuz çalışır — EasyOCR'da yaşadığımız "out of memory" sorunu burada olmaz).

## 1) OCR.space ücretsiz API anahtarı alma

1. https://ocr.space/ocrapi/freekey adresine git.
2. E-posta adresini gir, **"Get free api key"** de.
3. Anahtarı e-postana gönderecek (birkaç saniye içinde), kopyala.
4. Kart bilgisi istemez.

## 2) Yerelde deneme (opsiyonel)

```bash
cd kargo-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export OCR_SPACE_API_KEY="senin-anahtarin"
python3 app.py
```

Tarayıcıda `http://localhost:5000` adresini aç.

## 3) Render.com'a yayınlama

1. render.com'da hesap aç, GitHub reponu bağla.
2. Ayarlar:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** Free
3. **Environment Variables** kısmına ekle:
   - Key: `OCR_SPACE_API_KEY`
   - Value: (OCR.space'ten aldığın anahtar)
4. **Create Web Service** (ya da mevcut serviste Environment Variables'ı güncelleyip
   Manual Deploy yap).

### Dosya boyutu notu

OCR.space'in ücretsiz planı fotoğraf başına 1MB sınırı koyuyor. Uygulama fotoğrafı
göndermeden önce otomatik olarak sıkıştırıyor, bu yüzden normal şartlarda sorun
yaşamazsın; çok yüksek çözünürlüklü bir fotoğraf yine de limiti aşarsa uygulama
"fotoğraf çok büyük" uyarısı verip tekrar denemeni ister.

### Veri kalıcılığı notu

Render'ın ücretsiz planında disk kalıcı değildir — servis yeniden başlarsa `kargo.db`
sıfırlanabilir. Küçük ölçekli kullanım için sorun değildir; kalıcı olması kritikse
ilerde bir veritabanı eklentisine taşınabilir.

## Dosyalar

- `app.py` — Flask backend (API + OCR.space entegrasyonu + veritabanı)
- `static/index.html` — arayüz (fotoğraf çekme, form, liste)
- `requirements.txt` — Python bağımlılıkları
- `Procfile` — Render/Heroku için başlatma komutu
