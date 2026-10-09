"""Very small translation table (Turkish + English) for the site and the bot."""

from __future__ import annotations

LANGS = ("tr", "en")
DEFAULT = "tr"

T: dict[str, dict[str, str]] = {
    # errors
    "err.unsupported": {"tr": "Bu bağlantı desteklenmiyor.", "en": "This link is not supported."},
    "err.login_required": {
        "tr": "Bu içerik giriş gerektiriyor veya site botu engelledi. Biraz sonra tekrar deneyin.",
        "en": "This content requires login or the site blocked us. Please try again later.",
    },
    "err.private": {"tr": "Bu içerik gizli.", "en": "This content is private."},
    "err.geo": {"tr": "Bu içerik bölgesel olarak engelli.", "en": "This content is geo-restricted."},
    "err.age": {"tr": "Bu içerik yaş doğrulaması gerektiriyor.", "en": "This content is age-restricted."},
    "err.not_found": {"tr": "İçerik bulunamadı veya kaldırılmış.", "en": "Content not found or removed."},
    "err.no_media": {"tr": "Bu bağlantıda indirilebilir video/ses bulunamadı.", "en": "No downloadable media found at this link."},
    "err.live": {"tr": "Canlı yayınlar indirilemez.", "en": "Live streams can't be downloaded."},
    "err.too_large": {"tr": "Dosya izin verilen boyuttan büyük.", "en": "The file is larger than allowed."},
    "err.too_long": {"tr": "Video izin verilen süreden uzun.", "en": "The video is longer than allowed."},
    "err.network": {"tr": "Kaynağa bağlanılamadı, tekrar deneyin.", "en": "Couldn't reach the source, please retry."},
    "err.invalid_url": {"tr": "Geçerli bir bağlantı girin.", "en": "Please enter a valid link."},
    "err.rate_limited": {"tr": "Çok fazla istek. Biraz bekleyip tekrar deneyin.", "en": "Too many requests. Please wait a bit."},
    "err.disabled": {"tr": "İndirme şu an kapalı.", "en": "Downloading is currently disabled."},
    "err.expired": {"tr": "Bağlantının süresi doldu, tekrar indirin.", "en": "This link expired, please download again."},
    "err.interrupted": {"tr": "İndirme yarıda kesildi, tekrar deneyin.", "en": "Download was interrupted, please retry."},
    "err.bad_preset": {"tr": "Geçersiz format.", "en": "Invalid format."},
    "err.generic": {"tr": "Bir hata oluştu. Bağlantıyı kontrol edip tekrar deneyin.", "en": "Something went wrong. Check the link and retry."},
    # website
    "web.nav_how": {"tr": "Nasıl çalışır", "en": "How it works"},
    "web.nav_sites": {"tr": "Siteler", "en": "Sites"},
    "web.nav_faq": {"tr": "SSS", "en": "FAQ"},
    "web.badge": {"tr": "1800+ site · Reklamsız · Kayıt yok", "en": "1800+ sites · No ads · No sign-up"},
    "web.placeholder": {"tr": "Video veya müzik bağlantısını yapıştır…", "en": "Paste a video or music link…"},
    "web.paste": {"tr": "Yapıştır", "en": "Paste"},
    "web.go": {"tr": "Getir", "en": "Fetch"},
    "web.analyzing": {"tr": "Bağlantı inceleniyor…", "en": "Analyzing link…"},
    "web.video": {"tr": "Video", "en": "Video"},
    "web.audio": {"tr": "Ses", "en": "Audio"},
    "web.items": {"tr": "Öğe seç", "en": "Pick an item"},
    "web.queued": {"tr": "Sırada bekliyor", "en": "Waiting in queue"},
    "web.position": {"tr": "Sıra", "en": "Position"},
    "web.downloading": {"tr": "Sunucuya indiriliyor", "en": "Downloading to server"},
    "web.processing": {"tr": "Dönüştürülüyor", "en": "Processing"},
    "web.ready": {"tr": "Dosyan hazır!", "en": "Your file is ready!"},
    "web.save": {"tr": "Dosyayı kaydet", "en": "Save file"},
    "web.again": {"tr": "Başka bir format", "en": "Another format"},
    "web.new": {"tr": "Yeni bağlantı", "en": "New link"},
    "web.expires": {"tr": "Bağlantı {min} dakika geçerli.", "en": "Link is valid for {min} minutes."},
    "web.retry": {"tr": "Tekrar dene", "en": "Try again"},
    "web.how_title": {"tr": "Üç adımda indir", "en": "Download in three steps"},
    "web.how1_t": {"tr": "Bağlantıyı kopyala", "en": "Copy the link"},
    "web.how1_d": {"tr": "Uygulamadaki veya tarayıcıdaki “Paylaş → Bağlantıyı kopyala” seçeneğini kullan.", "en": "Use “Share → Copy link” in the app or browser."},
    "web.how2_t": {"tr": "Yapıştır ve getir", "en": "Paste and fetch"},
    "web.how2_d": {"tr": "Bağlantıyı yukarıdaki kutuya yapıştır, içerik saniyeler içinde analiz edilir.", "en": "Paste the link above and we'll analyze it in seconds."},
    "web.how3_t": {"tr": "Formatı seç", "en": "Pick a format"},
    "web.how3_d": {"tr": "1080p’den 360p’ye video ya da MP3 / M4A ses — seçtiğin gibi indir.", "en": "Video from 1080p to 360p, or MP3 / M4A audio — your call."},
    "web.sites_title": {"tr": "Neredeyse her yerden", "en": "From almost anywhere"},
    "web.sites_desc": {"tr": "Popüler platformların yanı sıra, sayfasında video oynatıcı bulunan binlerce siteyi destekliyoruz.", "en": "Besides the popular platforms we support thousands of sites that embed a video player."},
    "web.sites_more": {"tr": "+1800 site daha", "en": "+1800 more sites"},
    "web.bot_title": {"tr": "Telegram’da da buradayız", "en": "We're on Telegram too"},
    "web.bot_desc": {"tr": "Bağlantıyı bota gönder, dosya doğrudan sohbetine gelsin. Uygulama yok, reklam yok.", "en": "Send a link to the bot and get the file right in your chat. No app, no ads."},
    "web.bot_btn": {"tr": "Botu aç", "en": "Open the bot"},
    "web.faq_title": {"tr": "Sık sorulan sorular", "en": "Frequently asked questions"},
    "web.faq1_q": {"tr": "Ücretli mi?", "en": "Is it free?"},
    "web.faq1_a": {"tr": "Hayır, tamamen ücretsiz ve kayıt gerektirmez.", "en": "Yes, completely free and no sign-up required."},
    "web.faq2_q": {"tr": "Dosyalar saklanıyor mu?", "en": "Do you keep the files?"},
    "web.faq2_a": {"tr": "Hayır. İndirilen dosyalar kısa bir süre sonra sunucudan otomatik silinir.", "en": "No. Downloaded files are deleted from the server automatically after a short while."},
    "web.faq3_q": {"tr": "Gizli veya özel içerikleri indirebilir miyim?", "en": "Can I download private content?"},
    "web.faq3_a": {"tr": "Hayır. Yalnızca herkese açık içerikler indirilebilir.", "en": "No. Only publicly available content can be downloaded."},
    "web.faq4_q": {"tr": "Neden bazı videolar inmiyor?", "en": "Why do some videos fail?"},
    "web.faq4_a": {"tr": "Canlı yayınlar, DRM korumalı içerikler (Netflix, Spotify vb.) ve kaldırılmış videolar indirilemez. Bazen platformlar geçici olarak engel koyabilir; birkaç dakika sonra tekrar deneyin.", "en": "Live streams, DRM-protected content (Netflix, Spotify, etc.) and removed videos can't be downloaded. Platforms sometimes block temporarily; retry in a few minutes."},
    "web.faq5_q": {"tr": "Telefonda nasıl kullanırım?", "en": "How do I use it on mobile?"},
    "web.faq5_a": {"tr": "Site mobil uyumlu. Daha da kolayı için Telegram botumuzu kullanabilirsin.", "en": "The site works on mobile. For even less friction use our Telegram bot."},
    "web.legal": {"tr": "Yalnızca sahibi olduğunuz veya indirme izni bulunan içerikleri indirin. Telif haklarına saygı gösterin.", "en": "Only download content you own or have permission to download. Respect copyright."},
    "web.expired_title": {"tr": "Bu bağlantının süresi doldu", "en": "This link has expired"},
    "web.expired_desc": {"tr": "Dosyalar gizliliğin için kısa süre sonra silinir. Bağlantıyı tekrar yapıştırarak yeniden indirebilirsin.", "en": "Files are removed shortly for your privacy. Paste the link again to re-download."},
    "web.home": {"tr": "Ana sayfaya dön", "en": "Back to home"},
    "web.disabled": {"tr": "Web üzerinden indirme şu an kapalı.", "en": "Web downloads are currently disabled."},
    # bot
    "bot.welcome": {
        "tr": "👋 <b>{name}</b>'e hoş geldin!\n\nYouTube, Instagram, X, TikTok ve 1800+ siteden video veya müzik indirmek için bağlantıyı bana gönder.",
        "en": "👋 Welcome to <b>{name}</b>!\n\nSend me a link from YouTube, Instagram, X, TikTok or 1800+ other sites to download video or music.",
    },
    "bot.help": {
        "tr": "📥 <b>Nasıl kullanılır?</b>\n1. Video bağlantısını kopyala\n2. Buraya yapıştır\n3. Formatı seç (video / MP3)\n\nKomutlar:\n/start – Başlat\n/help – Yardım",
        "en": "📥 <b>How to use</b>\n1. Copy a video link\n2. Paste it here\n3. Pick a format (video / MP3)\n\nCommands:\n/start – Start\n/help – Help",
    },
    "bot.no_link": {"tr": "Bir bağlantı göndermelisin 🔗", "en": "Please send me a link 🔗"},
    "bot.analyzing": {"tr": "🔎 Bağlantı inceleniyor…", "en": "🔎 Analyzing link…"},
    "bot.choose": {"tr": "Format seç:", "en": "Choose a format:"},
    "bot.items": {"tr": "📚 {n} öğe bulundu (en fazla {max} tanesi gönderilir).", "en": "📚 {n} items found (up to {max} will be sent)."},
    "bot.queued": {"tr": "⏳ Sıraya alındı (sıra: {pos})", "en": "⏳ Queued (position: {pos})"},
    "bot.downloading": {"tr": "⬇️ İndiriliyor… {progress}", "en": "⬇️ Downloading… {progress}"},
    "bot.processing": {"tr": "⚙️ İşleniyor…", "en": "⚙️ Processing…"},
    "bot.uploading": {"tr": "📤 Telegram'a yükleniyor…", "en": "📤 Uploading to Telegram…"},
    "bot.too_big_link": {
        "tr": "📦 Dosya Telegram limiti için çok büyük ({size}). Buradan indir (link {ttl} dk geçerli):",
        "en": "📦 The file is too big for Telegram ({size}). Download it here (valid for {ttl} min):",
    },
    "bot.too_big": {"tr": "📦 Dosya Telegram için çok büyük ({size}).", "en": "📦 The file is too big for Telegram ({size})."},
    "bot.done_caption": {"tr": "via {bot}", "en": "via {bot}"},
    "bot.banned": {"tr": "⛔ Bu botu kullanman engellendi.", "en": "⛔ You are banned from using this bot."},
    "bot.join": {
        "tr": "📢 Botu kullanmak için önce kanalımıza katıl, sonra tekrar dene.",
        "en": "📢 Please join our channel first, then try again.",
    },
    "bot.join_btn": {"tr": "Kanala katıl", "en": "Join channel"},
    "bot.expired": {"tr": "Bu istek zaman aşımına uğradı, bağlantıyı tekrar gönder.", "en": "This request expired, please send the link again."},
    "bot.download_btn": {"tr": "⬇️ İndir", "en": "⬇️ Download"},
}


def t(key: str, lang: str = DEFAULT, **kwargs: object) -> str:
    entry = T.get(key)
    if not entry:
        return key
    text = entry.get(lang) or entry[DEFAULT]
    return text.format(**kwargs) if kwargs else text


def pick_lang(code: str | None) -> str:
    code = (code or "").lower()[:2]
    return code if code in LANGS else ("en" if code else DEFAULT)


def human_size(n: int | float | None) -> str:
    if not n:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
