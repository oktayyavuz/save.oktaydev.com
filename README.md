# Save — video & müzik indirme sitesi + Telegram botu

YouTube, Instagram, X/Twitter, TikTok, Facebook, Reddit, SoundCloud, Vimeo ve
[yt-dlp](https://github.com/yt-dlp/yt-dlp)'nin desteklediği **1800+ siteden** (ayrıca sayfasında
video oynatıcı olan çoğu siteden) video veya müzik indiren web sitesi ve Telegram botu.
Tüm ayarlar (bot token'ı, çerezler, proxy, limitler…) **admin panelinden** yapılır.

Windows VDS üzerinde **Docker olmadan** çalışacak şekilde hazırlandı (Linux'ta da aynı şekilde çalışır).

## Özellikler

**Site**
- Bağlantıyı yapıştır → otomatik analiz → format seç → indir
- Video: En iyi / 1080p / 720p / 480p / 360p (sadece kaynakta olanlar gösterilir, tahmini boyutlarla)
- Ses: MP3 (192 kbps, kapak + etiketli) ve M4A
- Çoklu gönderiler (Instagram carousel, X çoklu video, playlist) için öğe seçimi
- Canlı ilerleme çubuğu, sıra bilgisi, hız/kalan süre
- Dosyalar belirlenen süre sonunda sunucudan otomatik silinir
- Mobil uyumlu, karanlık/aydınlık tema, TR/EN

**Telegram botu**
- Bağlantı gönder → küçük resim + format butonları → dosya sohbete gelir
- Aynı içerik ikinci kez istenirse Telegram `file_id` önbelleğinden anında gönderilir
- 50 MB'tan büyük dosyalar için siteden indirme linki gönderir (veya kendi Bot API sunucunla 2 GB'a kadar yükler)
- Zorunlu kanal üyeliği, kullanıcı engelleme, saatlik limit
- Admin komutları: `/stats`, `/broadcast mesaj`

**Admin paneli** (`/admin`)
- Genel bakış: günlük indirmeler, trafik, 14 günlük grafik, platform dağılımı, canlı işler
- İndirme geçmişi (arama/filtre), bot kullanıcıları (engelle/aç), toplu duyuru
- Ayarlar: site metinleri, bot token'ı, platform bazlı çerezler (cookies.txt), proxy, limitler
- Sistem: yt-dlp / ffmpeg / deno durumu, tek tıkla yt-dlp güncelleme, yeniden başlatma
- Token, çerez ve proxy değerleri veritabanında **şifreli** saklanır

## Windows VDS'e kurulum

Gereken: Windows Server 2016+ / Windows 10+, yönetici yetkisi. (Python, ffmpeg ve deno'yu script kendisi kurar.)

1. Projeyi sunucuya indir (ör. `C:\save`):
   ```powershell
   git clone https://github.com/oktayyavuz/save.oktaydev.com C:\save
   # git yoksa GitHub'dan ZIP indirip C:\save içine çıkar
   cd C:\save
   ```
2. Domain'in DNS **A kaydını** sunucunun IP'sine yönlendir (`save.oktaydev.com → VDS IP`).
3. **Yönetici PowerShell**'de çalıştır:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Domain save.oktaydev.com
   ```
   Bu komut:
   - Python 3.12'yi (yoksa) kurar, `.venv` oluşturur, paketleri yükler
   - `tools\` klasörüne **ffmpeg** (birleştirme/MP3 için) ve **deno** (YouTube için gerekli) indirir
   - Rastgele `SECRET_KEY` ile `.env` oluşturur
   - Uygulamayı **`SaveApp`** adlı Windows servisi olarak kurar (açılışta başlar, çökerse yeniden başlar)
   - **Caddy**'yi `SaveAppCaddy` servisi olarak kurar → Let's Encrypt ile otomatik **HTTPS**
   - Güvenlik duvarında 80/443 portlarını açar
4. `https://save.oktaydev.com/admin` adresine gir → yönetici hesabını oluştur.
5. **Ayarlar → Telegram Bot**: [@BotFather](https://t.me/BotFather)'dan aldığın token'ı gir, "Bot aktif"i aç, kaydet.
6. **Ayarlar → Genel → Genel adres**: `https://save.oktaydev.com` yaz (bot büyük dosyalar için bu linki kullanır).

> Domain olmadan denemek için: `windows\install.ps1 -Port 80` → site `http://SUNUCU-IP` adresinde HTTP olarak açılır.
>
> Sunucuda zaten IIS / başka bir web sunucusu 80-443'ü kullanıyorsa `-Domain` vermeden kur
> (`.env` içinde `HOST=127.0.0.1`, `PORT=8000`, `SECURE_COOKIES=1` yap) ve o sunucudan
> `127.0.0.1:8000`'e reverse proxy tanımla.

### Güncelleme ve bakım

```powershell
powershell -ExecutionPolicy Bypass -File windows\update.ps1   # git pull + paket/yt-dlp güncelle + servisi yeniden başlat
Restart-Service SaveApp                                         # sadece yeniden başlat
Get-Content C:\save\logs\SaveApp.err.log -Tail 50 -Wait         # canlı log (uygulama logları)
powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1  # servisleri kaldır (data\ kalır)
```

Siteler sık değiştiği için indirmeler bozulursa ilk iş **yt-dlp'yi güncellemek**tir
(admin paneli → Sistem → "yt-dlp'yi güncelle" → "Uygulamayı yeniden başlat" veya `update.ps1`).

Elle/ön planda çalıştırmak için: `windows\start.bat`.

## Instagram / X / YouTube için çerezler

Bu platformlar veri merkezi IP'lerinden gelen istekleri sıkça giriş yapmaya zorlar
("login required", "Sign in to confirm you're not a bot"). Çözüm:

1. Tarayıcıda **yan bir hesapla** ilgili siteye giriş yap (ana hesabını kullanma).
2. *Get cookies.txt LOCALLY* eklentisiyle çerezleri **Netscape formatında** dışa aktar.
3. Admin → Ayarlar → **Çerezler & Hesaplar** → ilgili platformun kutusuna yapıştır, kaydet.

Hâlâ engelleniyorsa **Ağ** sekmesinden bir (residential) proxy tanımlanabilir.

## Notlar ve sınırlar

- DRM'li içerikler (Netflix, Spotify, Disney+ vb.) ve canlı yayınlar indirilemez.
- Telegram'ın standart Bot API'si bot yüklemelerini **50 MB** ile sınırlar. Daha büyük dosyalar için bot,
  sitedeki indirme linkini gönderir. 2 GB'a kadar yükleme istersen kendi
  [telegram-bot-api](https://github.com/tdlib/telegram-bot-api) sunucunu `--local` ile çalıştırıp
  adresini (ör. `http://127.0.0.1:8081`) Ayarlar → Telegram → "Bot API sunucusu"na yaz.
- Site Cloudflare arkasındaysa SSL modunu **Full** yap; Caddy sertifikayı yine alır.
- Güvenlik: girilen URL'ler iç ağ adreslerine (127.0.0.1, 10.x, 169.254.x…) yönlendirilemez, admin formları CSRF korumalı,
  giriş denemeleri sınırlı, şifreler scrypt ile hash'lenir.
- Yalnızca hakkına sahip olduğun veya indirme izni bulunan içerikleri indir; platformların kullanım koşullarına ve telif haklarına
  dikkat et.

## Proje yapısı

```
app/
  main.py         FastAPI uygulaması, başlangıç/kapanış
  config.py       .env okuma, klasörler, tools\ PATH ayarı
  settings.py     Admin panelinden düzenlenen ayarlar (tek yerde tanımlı, şifreli gizli alanlar)
  downloader.py   yt-dlp sarmalayıcı: analiz, format presetleri, indirme, hata sınıflandırma
  jobs.py         Site ve botun ortak indirme kuyruğu (eşzamanlılık, ilerleme, temizlik)
  bot.py          Telegram botu (python-telegram-bot, long polling, panelden yeniden başlatılabilir)
  routes/         public.py (site + JSON API), admin.py (panel)
  templates/      Jinja2 şablonları
  static/         CSS / JS / logo
windows/          install.ps1, update.ps1, uninstall.ps1, start.bat
tests/            pytest testleri
run.py            Sunucuyu başlatır (python run.py)
```

## Geliştirme

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
SECURE_COOKIES=0 python run.py                    # http://127.0.0.1:8000
pytest
```
