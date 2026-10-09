"""Public website + JSON API used by the site's JavaScript."""

from __future__ import annotations

import asyncio
import secrets
import time
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from .. import downloader, jobs, settings, urlguard
from ..bot import bot_manager
from ..i18n import T
from ..i18n import t
from ..ratelimit import limiter
from ..web import client_ip, render, request_lang

router = APIRouter()

# Thumbnails are proxied because some CDNs (e.g. Instagram) forbid hotlinking.
_thumbs: dict[str, tuple[float, str]] = {}
_THUMB_TTL = 3600


def _thumb_token(url: str) -> str:
    if not url:
        return ""
    now = time.time()
    if len(_thumbs) > 5000:
        for k in [k for k, (ts, _) in _thumbs.items() if now - ts > _THUMB_TTL]:
            _thumbs.pop(k, None)
    token = secrets.token_urlsafe(10)
    _thumbs[token] = (now, url)
    return f"/api/thumb/{token}"


def _client_ip(request: Request) -> str:
    return client_ip(request)


def _error(request: Request, code: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": code, "message": t(f"err.{code}", request_lang(request))}, status_code=status)


@router.get("/")
async def index(request: Request):
    lang = request_lang(request)
    js_strings = {k: v.get(lang) or v["tr"] for k, v in T.items() if k.startswith(("web.", "err."))}
    response = render(request, "index.html", {"bot": bot_manager.status(), "js_strings": js_strings})
    if request.query_params.get("lang") in ("tr", "en"):
        response.set_cookie("lang", request.query_params["lang"], max_age=31536000, samesite="lax")
    return response


@router.get("/healthz")
async def healthz():
    return {"ok": True}


@router.get("/robots.txt")
async def robots():
    return PlainTextResponse("User-agent: *\nDisallow: /admin\nDisallow: /api\nDisallow: /d/\n")


class InfoIn(BaseModel):
    url: str = Field(max_length=2048)


@router.post("/api/info")
async def api_info(request: Request, body: InfoIn):
    if not settings.get("web_enabled"):
        return _error(request, "disabled", 503)
    if not limiter.hit(f"info:{_client_ip(request)}", settings.get("web_rate_limit") * 3):
        return _error(request, "rate_limited", 429)
    try:
        url = await asyncio.to_thread(urlguard.normalize, body.url)
        info = await asyncio.to_thread(downloader.extract_info, url)
    except urlguard.InvalidURL:
        return _error(request, "invalid_url")
    except downloader.DownloadFailed as exc:
        return _error(request, exc.code, 422)
    data = info.to_dict()
    data["thumbnail"] = _thumb_token(info.thumbnail)
    data["entries"] = [dict(e, thumbnail=_thumb_token(e.get("thumbnail", ""))) for e in info.entries]
    return data


class DownloadIn(BaseModel):
    url: str = Field(max_length=2048)
    preset: str = Field(max_length=16)
    item: int | None = Field(default=None, ge=1, le=1000)


@router.post("/api/download")
async def api_download(request: Request, body: DownloadIn):
    if not settings.get("web_enabled"):
        return _error(request, "disabled", 503)
    if body.preset not in downloader.PRESETS:
        return _error(request, "bad_preset")
    try:
        url = await asyncio.to_thread(urlguard.normalize, body.url)
    except urlguard.InvalidURL:
        return _error(request, "invalid_url")
    ip = _client_ip(request)
    if not limiter.hit(f"dl:{ip}", settings.get("web_rate_limit")):
        return _error(request, "rate_limited", 429)
    info = downloader.cached_info(url)
    title = info.title if info else ""
    if info and info.is_playlist and body.item:
        title = next((e["title"] for e in info.entries if e["index"] == body.item), title)
    job = jobs.manager.submit(url, body.preset, "web", ip, item=body.item, title=title,
                              platform=info.platform if info else "")
    return job.public()


@router.get("/api/jobs/{job_id}")
async def api_job(request: Request, job_id: str):
    job = jobs.manager.get(job_id)
    if not job:
        return _error(request, "expired", 404)
    data = job.public()
    if data["error"]:
        data["message"] = t(f"err.{data['error']}", request_lang(request))
    return data


@router.get("/api/thumb/{token}")
async def api_thumb(token: str):
    entry = _thumbs.get(token)
    if not entry:
        return Response(status_code=404)
    url = entry[1]
    try:
        urlguard.normalize(url)
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, proxy=settings.get("proxy") or None) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    except (httpx.HTTPError, urlguard.InvalidURL):
        return Response(status_code=502)
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) > 5 * 1024 * 1024:
        return Response(status_code=502)
    return Response(r.content, media_type=ctype, headers={"Cache-Control": "public, max-age=3600"})


@router.get("/d/{job_id}/{index}")
async def download_file(request: Request, job_id: str, index: int):
    job = jobs.manager.get(job_id)
    if not job or job.status != jobs.DONE or index < 0 or index >= len(job.files):
        return render(request, "expired.html", status_code=404)
    f = job.files[index]
    if not f.path.exists():
        return render(request, "expired.html", status_code=404)
    ascii_name = f.name.encode("ascii", "ignore").decode() or f"download{f.path.suffix}"
    ascii_name = ascii_name.replace('"', "")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(f.name)}"
    return FileResponse(f.path, headers={"Content-Disposition": disposition, "Cache-Control": "private, no-store"})
