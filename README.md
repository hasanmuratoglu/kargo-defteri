# Kargo Defteri

Dükkan içi kargo takibi için bağımsız web uygulaması. Flask backend + SQLite veritabanı
+ Google Cloud Vision OCR. Kendi barındırdığın bir yerde çalışır, hiçbir Anthropic/Claude
hesabına bağlı değildir.

## Nasıl çalışır

- Fotoğraf çekilir → backend, Google Cloud Vision API'ye gönderir → etikette geçen tüm
  yazı okunup ekrana dökülür (telefon numarası otomatik yakalanmaya çalışılır).
- Bu bir ham metin dökümüdür — "bu isim, bu adres" diye akıllı ayrıştırma yapmaz.
  Okunan metinden ilgili kısmı isim/adres kutularına kopyalarsın.
- Kayıtlar SQLite veritabanında (`kargo.db`) tutulur, herkes aynı listeyi görür.
- Liste sayfası her 4 saniyede bir kendini yeniler (gerçek zamanlı değil ama pratikte
  yeterince hızlı).

## 1) Google Cloud Vision API anahtarı alma (ücretsiz kota: ayda 1000 görsel)

1. https://console.cloud.google.com adresine git, ücretsiz bir proje oluştur.
2. Sol menüden **APIs & Services > Library** kısmına gir, "Cloud Vision API" ara ve
   **Enable** de.
3. **APIs & Services > Credentials** kısmına gir, **Create Credentials > API key** seç.
4. Oluşan anahtarı kopyala (bu, aşağıda `GOOGLE_VISION_API_KEY` olarak kullanılacak).
5. Güvenlik için: bu anahtarı "Cloud Vision API" ile sınırlandırman (API restrictions)
   önerilir, aksi halde başka biri bulursa senin kotanı kullanabilir.

Not: Google Cloud Console kredi kartı isteyebilir ama ücretsiz kota içinde kaldığın
sürece ücretlendirme yapılmaz.

## 2) Yerelde deneme (opsiyonel)

```bash
cd kargo-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export GOOGLE_VISION_API_KEY="senin-api-anahtarin"
python3 app.py
```

Tarayıcıda `http://localhost:5000` adresini aç.

## 3) Ücretsiz olarak internete yayınlama (Render.com)

1. https://render.com adresine git, ücretsiz hesap aç (GitHub hesabınla giriş yapabilirsin).
2. Bu klasörü bir GitHub reposuna yükle (`git init`, `git add .`, `git commit`, GitHub'a push).
3. Render panelinde **New > Web Service** seç, GitHub reponu bağla.
4. Ayarlar:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** Free
5. **Environment > Add Environment Variable** kısmına gir:
   - Key: `GOOGLE_VISION_API_KEY`
   - Value: (Google'dan aldığın anahtar)
6. **Create Web Service** de. Birkaç dakika sonra sana `https://kargo-defteri-xxxx.onrender.com`
   gibi bir link verecek. Bu linki dükkandaki herkesle paylaş.

### Önemli kısıtlama: ücretsiz planda veri kalıcılığı

Render'ın ücretsiz planında disk **kalıcı değildir** — servis yeniden başlatılırsa
(uzun süre kullanılmadığında uykuya geçip tekrar uyanması dahil) `kargo.db` dosyası
sıfırlanabilir. Küçük ölçekli/deneme kullanımı için sorun değildir, ama kayıtların
kalıcı olması senin için kritikse iki seçeneğin var:

- Render'da ücretsiz bir **PostgreSQL** eklentisi ekleyip veritabanını oraya taşımak
  (biraz kod değişikliği gerekir, istersen bunu da hazırlarım), veya
- Render'da **Persistent Disk** özelliği olan ücretli bir plana geçmek (aylık birkaç dolar).

Alternatif olarak, dükkanda sürekli açık duran bir bilgisayarda (iş bilgisayarı değil,
ayrı bir eski bilgisayar/mini PC olabilir) bu uygulamayı yerelde 7/24 çalıştırıp yerel
ağ üzerinden (aynı wifi'daki telefonlar erişebilir) kullanmak da bir seçenek — bu durumda
veri hep o bilgisayarın diskinde kalır ve internete hiç çıkmaz.

## Dosyalar

- `app.py` — Flask backend (API + OCR + veritabanı)
- `static/index.html` — arayüz (fotoğraf çekme, form, liste)
- `requirements.txt` — Python bağımlılıkları
- `Procfile` — Render/Heroku için başlatma komutu
