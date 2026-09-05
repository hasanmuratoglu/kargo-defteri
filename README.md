# Kargo Defteri

Dükkan içi kargo takibi için bağımsız web uygulaması. Flask backend + SQLite veritabanı
+ EasyOCR (açık kaynak, tamamen ücretsiz ve sınırsız, hiçbir dış API anahtarı gerektirmez).

## Nasıl çalışır

- Fotoğraf çekilir → backend, EasyOCR ile etiketteki yazıyı okur → ham metin ekrana dökülür
  (telefon numarası otomatik yakalanmaya çalışılır).
- Bu bir ham metin dökümüdür — "bu isim, bu adres" diye akıllı ayrıştırma yapmaz.
  Okunan metinden ilgili kısmı isim/adres kutularına kopyalarsın.
- Kayıtlar SQLite veritabanında (`kargo.db`) tutulur, herkes aynı listeyi görür.
- Liste sayfası her 4 saniyede bir kendini yeniler (gerçek zamanlı değil ama pratikte
  yeterince hızlı).

## Google hesabı / API anahtarı gerekmiyor

Önceki sürüm Google Cloud Vision kullanıyordu (API anahtarı + faturalandırma hesabı
gerektiriyordu). Artık **EasyOCR** kullanılıyor — açık kaynak, sunucunun kendi üzerinde
çalışıyor, hiçbir dış servise bağlı değil, hiçbir kota/ücret yok.

## 1) Yerelde deneme (opsiyonel)

```bash
cd kargo-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt   # ilk kurulum torch indireceği icin biraz uzun surebilir
python3 app.py
```

Tarayıcıda `http://localhost:5000` adresini aç. İlk fotoğraf denemesinde EasyOCR modelini
indirecek (birkaç yüz MB, birkaç dakika sürebilir) — sonraki denemeler hızlı olur.

## 2) Ücretsiz olarak internete yayınlama (Render.com)

1. render.com'da hesap aç, GitHub reponu bağla (daha önce yaptığın gibi).
2. Ayarlar:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --timeout 120`
   - **Instance Type:** Free (yetersiz gelirse aşağıya bak)
3. Artık **Environment Variables** eklemene gerek yok — API anahtarı derdi bitti.
4. **Create Web Service** de.

### Önemli: Render'ın ücretsiz planı EasyOCR için yetersiz kalabilir

EasyOCR, Google Vision gibi hafif bir API çağrısı değil — arka planda bir yapay zeka
modelini (torch tabanlı) belleğe yükleyip çalıştırıyor. Render'ın ücretsiz planı sadece
**512 MB RAM** veriyor, bu EasyOCR için yetersiz kalabilir (servis "out of memory" hatasıyla
çökebilir ya da hiç açılmayabilir).

E�er bu olursa seçeneklerin:
- Render'da biraz daha güçlü, ücretli bir plana geçmek (aylık ~$7, 512 MB yerine daha
  fazla RAM veren plan).
- Railway.app gibi başka bir servise geçmek (bazılarının ücretsiz kotası biraz daha
  cömert olabilir).
- Dükkanda sürekli açık duran bir bilgisayarda (iş bilgisayarı değil, ayrı bir eski
  bilgisayar/mini PC) bu uygulamayı yerelde çalıştırıp yerel ağ üzerinden kullanmak —
  bu durumda RAM sınırı olmaz ve internete hiç çıkmaz.

Deploy'u dene, hata alırsak (Render loglarında "out of memory" ya da servis sürekli
yeniden başlıyorsa) hangi yöne gideceğimize birlikte karar veririz.

### Veri kalıcılığı notu

Render'ın ücretsiz planında disk kalıcı değildir — servis yeniden başlarsa `kargo.db`
sıfırlanabilir. Küçük ölçekli kullanım için sorun değildir; kalıcı olması kritikse
ilerde bir veritabanı eklentisine taşınabilir.

## Dosyalar

- `app.py` — Flask backend (API + EasyOCR + veritabanı)
- `static/index.html` — arayüz (fotoğraf çekme, form, liste)
- `requirements.txt` — Python bağımlılıkları
- `Procfile` — Render/Heroku için başlatma komutu
