"""Process-level configuration read from environment variables.

Everything that an operator should be able to change at runtime lives in the
database (see ``app.settings``) and is edited from the admin panel. Only the
things needed *before* the database is available are configured here.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
TOOLS_DIR = ROOT_DIR / "tools"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE per line); real env vars win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_dotenv(ROOT_DIR / ".env")

# Bundled binaries (ffmpeg, deno) installed by windows/install.ps1 live in tools/.
for _p in (TOOLS_DIR / "ffmpeg" / "bin", TOOLS_DIR):
    if _p.is_dir() and str(_p) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(_p) + os.pathsep + os.environ.get("PATH", "")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
# Set by the Windows service wrapper; enables the "restart" button in the panel.
RUNNING_AS_SERVICE = os.environ.get("RUNNING_AS_SERVICE", "0") == "1"

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR.parent / "data")).resolve()
DOWNLOAD_DIR = DATA_DIR / "downloads"
COOKIE_DIR = DATA_DIR / "cookies"
DB_PATH = DATA_DIR / "app.db"

# Allow yt-dlp to fetch private/loopback addresses. Only for local testing.
ALLOW_PRIVATE_URLS = os.environ.get("ALLOW_PRIVATE_URLS", "0") == "1"

# Mark session cookies as Secure (set to 0 only for plain-http local dev).
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "1") == "1"

# Optional bootstrap admin (otherwise the first visit to /admin runs setup).
BOOTSTRAP_ADMIN_USER = os.environ.get("ADMIN_USERNAME", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# Disable the Telegram bot entirely (useful for tests).
DISABLE_BOT = os.environ.get("DISABLE_BOT", "0") == "1"


def ensure_dirs() -> None:
    for d in (DATA_DIR, DOWNLOAD_DIR, COOKIE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _load_secret_key() -> str:
    env = os.environ.get("SECRET_KEY", "").strip()
    if env:
        return env
    ensure_dirs()
    path = DATA_DIR / ".secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


SECRET_KEY = _load_secret_key()
