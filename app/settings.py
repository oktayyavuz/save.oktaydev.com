"""Runtime settings stored in SQLite and edited from the admin panel.

Each setting is declared once in ``FIELDS``; the admin settings page is
rendered from these declarations, so adding a new option only takes one line.
Secret values (tokens, cookies, proxy) are encrypted at rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import db, security


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    kind: str = "text"  # text | textarea | int | bool | secret | secret_textarea | select
    default: Any = ""
    help: str = ""
    options: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    min: int | None = None
    max: int | None = None

    @property
    def secret(self) -> bool:
        return self.kind.startswith("secret")


GROUPS: list[tuple[str, str]] = [
    ("general", "Genel"),
    ("telegram", "Telegram Bot"),
    ("credentials", "Çerezler & Hesaplar"),
    ("limits", "Limitler"),
    ("network", "Ağ"),
]

COOKIE_PLATFORMS: list[tuple[str, str, tuple[str, ...]]] = [
    ("youtube", "YouTube", ("youtube.com", "youtu.be", "youtube-nocookie.com")),
    ("instagram", "Instagram", ("instagram.com",)),
    ("x", "X / Twitter", ("x.com", "twitter.com")),
    ("tiktok", "TikTok", ("tiktok.com",)),
    ("facebook", "Facebook", ("facebook.com", "fb.watch")),
    ("reddit", "Reddit", ("reddit.com", "redd.it")),
]

_COOKIE_HELP = (
    "Netscape formatında cookies.txt içeriği. Giriş gerektiren, yaş sınırlı veya "
    "özel içerikler için gerekir. Tarayıcıda 'Get cookies.txt LOCALLY' eklentisiyle alınabilir."
)

FIELDS: list[Field] = [
    # General
    Field("site_name", "Site adı", "general", default="Save"),
    Field("site_tagline", "Slogan", "general", default="Her yerden video ve müzik indir"),
    Field("site_description", "Meta açıklama", "general", "textarea",
          default="YouTube, Instagram, X, TikTok ve 1800+ siteden video ve müzik indirin. Ücretsiz, hızlı, reklamsız."),
    Field("public_base_url", "Genel adres (URL)", "general",
          default="", help="Örn. https://save.oktaydev.com — Telegram'a büyük dosya linki gönderirken kullanılır."),
    Field("web_enabled", "Web indirme açık", "general", "bool", default=True),
    Field("announcement", "Duyuru bandı", "general", "textarea",
          default="", help="Boş bırakılırsa gösterilmez."),
    # Telegram
    Field("telegram_enabled", "Bot aktif", "telegram", "bool", default=False),
    Field("telegram_bot_token", "Bot token", "telegram", "secret",
          help="@BotFather'dan alınan token. Kaydedince bot otomatik yeniden başlar."),
    Field("telegram_api_base", "Bot API sunucusu", "telegram", default="",
          help="Boş = api.telegram.org (50 MB limit). Kendi telegram-bot-api sunucunuz için örn. http://127.0.0.1:8081 (2 GB limit)."),
    Field("telegram_admin_ids", "Admin Telegram ID'leri", "telegram", default="",
          help="Virgülle ayrılmış kullanıcı ID'leri. /stats ve /broadcast komutlarını kullanabilir."),
    Field("telegram_force_channel", "Zorunlu kanal", "telegram", default="",
          help="Örn. @kanalim — kullanıcı bu kanala katılmadan indiremez. Bot kanalda admin olmalı."),
    Field("telegram_welcome", "Karşılama mesajı", "telegram", "textarea", default="",
          help="Boş bırakılırsa varsayılan mesaj kullanılır."),
    # Credentials
    *[
        Field(f"cookies_{key}", f"{name} çerezleri", "credentials", "secret_textarea", help=_COOKIE_HELP)
        for key, name, _ in COOKIE_PLATFORMS
    ],
    Field("cookies_generic", "Diğer siteler için çerezler", "credentials", "secret_textarea",
          help="Yukarıdakiler dışındaki siteler için kullanılır."),
    # Limits
    Field("max_filesize_mb", "Maks. dosya boyutu (MB)", "limits", "int", default=1024, min=1, max=20000),
    Field("max_duration_min", "Maks. süre (dakika)", "limits", "int", default=240, min=1, max=10000),
    Field("max_concurrent", "Eşzamanlı indirme", "limits", "int", default=3, min=1, max=32),
    Field("max_playlist_items", "Çoklu gönderide maks. öğe", "limits", "int", default=10, min=1, max=50,
          help="Instagram carousel, X çoklu video vb."),
    Field("file_ttl_min", "Dosya saklama süresi (dakika)", "limits", "int", default=60, min=5, max=10080),
    Field("web_rate_limit", "Web: saatlik istek / IP", "limits", "int", default=30, min=1, max=10000),
    Field("bot_rate_limit", "Bot: saatlik istek / kullanıcı", "limits", "int", default=30, min=1, max=10000),
    # Network
    Field("proxy", "Proxy", "network", "secret",
          help="Örn. socks5://user:pass@host:1080 veya http://host:8080. Engellenen siteler için."),
    Field("user_agent", "User-Agent", "network", default="", help="Boş = yt-dlp varsayılanı."),
    Field("source_address", "Çıkış IP'si", "network", default="",
          help="Birden fazla IP'li sunucularda (örn. 0.0.0.0 → IPv4'e zorlar)."),
]

FIELD_MAP: dict[str, Field] = {f.key: f for f in FIELDS}

_cache: dict[str, Any] | None = None


def _coerce(f: Field, raw: str) -> Any:
    if f.kind == "bool":
        return raw in ("1", "true", "on", "True")
    if f.kind == "int":
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return f.default
        if f.min is not None:
            value = max(f.min, value)
        if f.max is not None:
            value = min(f.max, value)
        return value
    return raw


def _load() -> dict[str, Any]:
    values = {f.key: f.default for f in FIELDS}
    for row in db.query("SELECT key, value, encrypted FROM settings"):
        f = FIELD_MAP.get(row["key"])
        if not f:
            continue
        raw = security.decrypt(row["value"]) if row["encrypted"] else row["value"]
        values[f.key] = _coerce(f, raw)
    return values


def all_settings() -> dict[str, Any]:
    global _cache
    if _cache is None:
        _cache = _load()
    return dict(_cache)


def get(key: str) -> Any:
    return all_settings()[key]


def set_many(values: dict[str, Any]) -> list[str]:
    """Persist values; returns the keys that actually changed."""
    global _cache
    current = all_settings()
    changed: list[str] = []
    for key, value in values.items():
        f = FIELD_MAP[key]
        if f.kind == "bool":
            value = bool(value)
            stored = "1" if value else "0"
        elif f.kind == "int":
            value = _coerce(f, str(value))
            stored = str(value)
        else:
            value = str(value or "").replace("\r\n", "\n")
            if f.kind in ("text", "secret", "select"):
                value = value.strip()
            stored = value
        if current.get(key) == value:
            continue
        if f.secret:
            stored = security.encrypt(stored) if stored else ""
        db.execute(
            "INSERT INTO settings(key, value, encrypted) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, encrypted=excluded.encrypted",
            (key, stored, 1 if f.secret and stored else 0),
        )
        changed.append(key)
    _cache = None
    return changed


def reset_cache() -> None:
    global _cache
    _cache = None


def admin_ids() -> set[int]:
    ids = set()
    for part in str(get("telegram_admin_ids")).replace(" ", "").split(","):
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return ids


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "•" * 8 + value[-4:]
