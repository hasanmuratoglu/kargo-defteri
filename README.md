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

## Günü kapatma (otomatik Excel + mail + temizlik)

Her gece belirlenen saatte tüm kayıtları bir Excel dosyasına dökup mail atan,
sonra veritabanını temizleyen bir özellik. Bu sayede Render'ın ücretsiz planındaki
"disk kalıcı değil" riski önemsizleşiyor — her günün verisi zaten o gün mail
olarak arşivleniyor.

### 1) Gmail'den "Uygulama Şifresi" (App Password) al

Bu, normal Gmail şifren DEĞİL — özel, sadece bu uygulamanın kullanacağı bir şifre.

1. https://myaccount.google.com/security adresine git.
2. "2 Adımlı Doğrulama" (2-Step Verification) kapalıysa önce onu aç (zorunlu ön koşul).
3. Aynı sayfada veya https://myaccount.google.com/apppasswords adresinden
   "Uygulama Şifreleri" bölümüne gir.
4. Bir isim yaz (örn. "Kargo Defteri"), oluştur.
5. Google sana 16 haneli bir şifre verecek (boşluksuz kopyala) — bunu
   `GMAIL_APP_PASSWORD` olarak kullanacağız.

### 2) Render'a ortam değişkenlerini ekle

Render Dashboard > servisin > Environment Variables kısmına ekle:

| Key | Value |
|---|---|
| `GMAIL_ADDRESS` | `h.muratoglu97@gmail.com` |
| `GMAIL_APP_PASSWORD` | (Google'dan aldığın 16 haneli şifre) |
| `REPORT_TO_EMAIL` | `h.muratoglu97@gmail.com` |
| `CRON_SECRET` | `ATQcf3bVkyDs5Lo0-pkiID9X_bVqMboC` (bu rastgele üretildi, aynen kullanabilirsin ya da kendi rastgele metnini yaz) |

### 3) Render'da bir Cron Job oluştur

1. Render Dashboard'da **"New +" > "Cron Job"** seç.
2. **Environment:** Docker
3. **Image:** `curlimages/curl:latest`
4. **Command:**
   ```
   curl -s -X POST "https://kargo-defteri.onrender.com/api/close-day?secret=ATQcf3bVkyDs5Lo0-pkiID9X_bVqMboC"
   ```
   (kendi Render linkini ve kendi CRON_SECRET'ını kullan)
5. **Schedule:** `0 20 * * *`
   - Bu, **UTC saatine göre 20:00** demek — Türkiye UTC+3 olduğu için bu, **Türkiye saatiyle gece 23:00**'a denk geliyor.
6. Oluştur.

Artık her gece saat 23:00'te (Türkiye saati) otomatik olarak: tüm kayıtlar Excel'e
dökülüp `h.muratoglu97@gmail.com` adresine mail atılacak, sonra veritabanı
temizlenecek.

### Elle test etmek istersen

Tarayıcıdan ya da bir HTTP isteğiyle şu adrese POST isteği atarsan (GET ile
tarayıcıya yapıştırman da işe yarar, sadece POST beklediği için bazı
tarayıcılarda "method not allowed" diyebilir — Postman/curl ile dene):

```
https://kargo-defteri.onrender.com/api/close-day?secret=ATQcf3bVkyDs5Lo0-pkiID9X_bVqMboC
```

Kayıt yoksa mail atmaz, "kayıt yok" der. Mail gönderimi başarısız olursa
kayıtlar SİLİNMEZ (güvenlik için) — hatayı görürsün, tekrar denenebilir.
