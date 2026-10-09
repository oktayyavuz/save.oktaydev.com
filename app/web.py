"""Shared template setup."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import config, settings
from .i18n import human_size, t

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))
STATIC_VERSION = str(int(time.time()))


def _datetime(ts: float | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime(fmt)


def _duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


templates.env.filters["dt"] = _datetime
templates.env.filters["size"] = human_size
templates.env.filters["duration"] = _duration
templates.env.globals["static_version"] = STATIC_VERSION


def client_ip(request: Request) -> str:
    if config.BEHIND_CLOUDFLARE:
        cf = request.headers.get("cf-connecting-ip", "").strip()
        if cf:
            return cf
    return request.client.host if request.client else "unknown"


def request_lang(request: Request) -> str:
    q = request.query_params.get("lang")
    if q in ("tr", "en"):
        return q
    cookie = request.cookies.get("lang")
    if cookie in ("tr", "en"):
        return cookie
    # The site content (tagline etc.) is written in Turkish, so default to it.
    return "tr"


def render(request: Request, name: str, context: dict[str, Any] | None = None, status_code: int = 200):
    ctx: dict[str, Any] = {
        "s": settings.all_settings(),
        "lang": request_lang(request),
        "t": t,
        "csrf": request.session.get("csrf", "") if "session" in request.scope else "",
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
