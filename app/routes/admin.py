"""Admin panel."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import config, db, downloader, jobs, security, settings, urlguard
from ..bot import bot_manager
from ..ratelimit import limiter
from ..web import client_ip, render

router = APIRouter(prefix="/admin")

# Last maintenance outputs (kept in memory; too large for the session cookie).
_logs: dict[str, str] = {}


class NotAuthenticated(Exception):
    pass


def has_admin() -> bool:
    return bool(db.scalar("SELECT COUNT(*) FROM admins"))


def current_admin(request: Request) -> dict[str, Any]:
    admin_id = request.session.get("admin_id")
    if admin_id:
        row = db.query_one("SELECT id, username FROM admins WHERE id=?", (admin_id,))
        if row:
            return dict(row)
    raise NotAuthenticated()


def _ensure_csrf(request: Request) -> str:
    if not request.session.get("csrf"):
        request.session["csrf"] = security.new_csrf_token()
    return request.session["csrf"]


async def _form(request: Request) -> dict[str, Any]:
    form = await request.form()
    if not security.check_csrf(request.session, form.get("csrf")):
        raise NotAuthenticated()
    return form


def _flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def _page(request: Request, name: str, context: dict[str, Any] | None = None, status_code: int = 200):
    _ensure_csrf(request)
    ctx = {"admin": None, "flash": request.session.pop("flash", None), "path": request.url.path,
           "bot": bot_manager.status(), "active_jobs": len(jobs.manager.active())}
    try:
        ctx["admin"] = current_admin(request)
    except NotAuthenticated:
        pass
    if context:
        ctx.update(context)
    return render(request, name, ctx, status_code)


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _ip(request: Request) -> str:
    return client_ip(request)


# --------------------------------------------------------------------------- auth

@router.get("/setup")
async def setup_page(request: Request):
    if has_admin():
        return _redirect("/admin/login")
    return _page(request, "admin/setup.html")


@router.post("/setup")
async def setup_submit(request: Request):
    if has_admin():
        return _redirect("/admin/login")
    form = await _form(request)
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    if len(username) < 3 or len(password) < 8 or password != form.get("password2"):
        return _page(request, "admin/setup.html",
                     {"error": "Kullanıcı adı en az 3, şifre en az 8 karakter olmalı ve şifreler eşleşmeli."}, 400)
    cur = db.execute("INSERT INTO admins(username, password_hash, created_at) VALUES(?,?,?)",
                     (username, security.hash_password(password), time.time()))
    request.session.clear()
    request.session["admin_id"] = cur.lastrowid
    _flash(request, "Hoş geldin! Önce Telegram bot token'ını ve site adresini ayarla.")
    return _redirect("/admin/settings?tab=telegram")


@router.get("/login")
async def login_page(request: Request):
    if not has_admin():
        return _redirect("/admin/setup")
    return _page(request, "admin/login.html")


@router.post("/login")
async def login_submit(request: Request):
    form = await _form(request)
    if not limiter.hit(f"login:{_ip(request)}", 10, 900):
        return _page(request, "admin/login.html", {"error": "Çok fazla deneme. 15 dakika sonra tekrar deneyin."}, 429)
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    row = db.query_one("SELECT id, password_hash FROM admins WHERE username=?", (username,))
    if not row or not security.verify_password(password, row["password_hash"]):
        await asyncio.sleep(0.5)
        return _page(request, "admin/login.html", {"error": "Kullanıcı adı veya şifre hatalı.", "username": username}, 401)
    request.session.clear()
    request.session["admin_id"] = row["id"]
    nxt = str(form.get("next", ""))
    return _redirect(nxt if nxt.startswith("/admin") and not nxt.startswith("//") else "/admin")


@router.post("/logout")
async def logout(request: Request):
    await _form(request)
    request.session.clear()
    return _redirect("/admin/login")


# --------------------------------------------------------------------------- dashboard

@router.get("")
async def dashboard(request: Request):
    current_admin(request)
    now = time.time()
    day = now - 86400
    stats = {
        "downloads_total": db.scalar("SELECT COUNT(*) FROM downloads"),
        "downloads_today": db.scalar("SELECT COUNT(*) FROM downloads WHERE created_at > ?", (day,)),
        "errors_today": db.scalar("SELECT COUNT(*) FROM downloads WHERE created_at > ? AND status='error'", (day,)),
        "bytes_today": db.scalar("SELECT COALESCE(SUM(filesize),0) FROM downloads WHERE created_at > ?", (day,)),
        "users_total": db.scalar("SELECT COUNT(*) FROM tg_users"),
        "users_active": db.scalar("SELECT COUNT(*) FROM tg_users WHERE last_seen > ?", (day,)),
        "web_today": db.scalar("SELECT COUNT(*) FROM downloads WHERE created_at > ? AND source='web'", (day,)),
        "tg_today": db.scalar("SELECT COUNT(*) FROM downloads WHERE created_at > ? AND source='telegram'", (day,)),
    }
    # Last 14 days, local time buckets.
    days: list[dict[str, Any]] = []
    start = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1)) - 13 * 86400
    rows = db.query(
        "SELECT CAST((created_at - ?) / 86400 AS INTEGER) AS d, source, COUNT(*) AS c "
        "FROM downloads WHERE created_at >= ? GROUP BY d, source",
        (start, start),
    )
    buckets = {(r["d"], r["source"]): r["c"] for r in rows}
    for i in range(14):
        web = buckets.get((i, "web"), 0)
        tg = buckets.get((i, "telegram"), 0)
        days.append({"label": time.strftime("%d.%m", time.localtime(start + i * 86400 + 3600)), "web": web, "tg": tg,
                     "total": web + tg})
    peak = max((d["total"] for d in days), default=0) or 1
    platforms = db.query(
        "SELECT COALESCE(NULLIF(platform,''),'?') AS p, COUNT(*) AS c FROM downloads WHERE created_at > ? "
        "GROUP BY p ORDER BY c DESC LIMIT 8",
        (now - 30 * 86400,),
    )
    recent = db.query("SELECT * FROM downloads ORDER BY created_at DESC LIMIT 8")
    return _page(request, "admin/dashboard.html", {
        "stats": stats, "days": days, "peak": peak, "platforms": platforms, "recent": recent,
        "active": jobs.manager.active(),
    })


@router.get("/api/active")
async def active_jobs(request: Request):
    current_admin(request)
    return JSONResponse([
        {"id": j.id, "title": j.title or j.url, "status": j.status, "percent": j.percent, "source": j.source}
        for j in jobs.manager.active()
    ])


# --------------------------------------------------------------------------- lists

PAGE_SIZE = 30


@router.get("/downloads")
async def downloads(request: Request, q: str = "", status: str = "", source: str = "", page: int = 1):
    current_admin(request)
    where, params = ["1=1"], []
    if q:
        where.append("(url LIKE ? OR title LIKE ? OR requester LIKE ?)")
        params += [f"%{q}%"] * 3
    if status in ("done", "error", "queued", "downloading", "processing"):
        where.append("status=?")
        params.append(status)
    if source in ("web", "telegram"):
        where.append("source=?")
        params.append(source)
    clause = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM downloads WHERE {clause}", params)
    page = max(1, page)
    rows = db.query(f"SELECT * FROM downloads WHERE {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE])
    return _page(request, "admin/downloads.html", {
        "rows": rows, "q": q, "status": status, "source": source, "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)), "total": total,
    })


@router.post("/downloads/clear")
async def downloads_clear(request: Request):
    current_admin(request)
    form = await _form(request)
    days = int(form.get("days") or 30)
    cur = db.execute("DELETE FROM downloads WHERE created_at < ?", (time.time() - days * 86400,))
    _flash(request, f"{cur.rowcount} kayıt silindi.")
    return _redirect("/admin/downloads")


@router.get("/users")
async def users(request: Request, q: str = "", page: int = 1, banned: str = ""):
    current_admin(request)
    where, params = ["1=1"], []
    if q:
        where.append("(CAST(id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ?)")
        params += [f"%{q}%"] * 3
    if banned == "1":
        where.append("banned=1")
    clause = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM tg_users WHERE {clause}", params)
    page = max(1, page)
    rows = db.query(f"SELECT * FROM tg_users WHERE {clause} ORDER BY last_seen DESC LIMIT ? OFFSET ?",
                    [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE])
    return _page(request, "admin/users.html", {
        "rows": rows, "q": q, "banned": banned, "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)), "total": total,
    })


@router.post("/users/{user_id}/ban")
async def user_ban(request: Request, user_id: int):
    current_admin(request)
    await _form(request)
    db.execute("UPDATE tg_users SET banned = 1 - banned WHERE id=?", (user_id,))
    return _redirect(request.headers.get("referer") or "/admin/users")


# --------------------------------------------------------------------------- settings

RESTART_KEYS = {"telegram_enabled", "telegram_bot_token", "telegram_api_base", "telegram_api_id", "telegram_api_hash"}


@router.get("/settings")
async def settings_page(request: Request, tab: str = "general"):
    current_admin(request)
    groups = dict(settings.GROUPS)
    if tab not in groups:
        tab = "general"
    values = settings.all_settings()
    fields = [f for f in settings.FIELDS if f.group == tab]
    return _page(request, "admin/settings.html", {
        "tab": tab, "groups": settings.GROUPS, "fields": fields, "values": values, "mask": settings.mask,
    })


@router.post("/settings")
async def settings_save(request: Request):
    current_admin(request)
    form = await _form(request)
    tab = str(form.get("tab", "general"))
    updates: dict[str, Any] = {}
    for f in settings.FIELDS:
        if f.group != tab:
            continue
        if f.kind == "bool":
            updates[f.key] = form.get(f.key) == "on"
        elif f.secret:
            if form.get(f"{f.key}__clear") == "on":
                updates[f.key] = ""
            elif str(form.get(f.key, "")).strip():
                updates[f.key] = form.get(f.key)
        elif f.key in form:
            updates[f.key] = form.get(f.key)
    if "public_base_url" in updates:
        updates["public_base_url"] = str(updates["public_base_url"]).strip().rstrip("/")
    changed = settings.set_many(updates)
    if "max_concurrent" in changed:
        jobs.manager.resize(settings.get("max_concurrent"))
    message = "Ayarlar kaydedildi." if changed else "Değişiklik yok."
    if RESTART_KEYS & set(changed):
        await bot_manager.restart()
        st = bot_manager.status()
        if st["running"]:
            message += f" Bot @{st['username']} olarak çalışıyor."
        elif st["error"]:
            _flash(request, f"Ayarlar kaydedildi ama bot başlatılamadı: {st['error']}", "error")
            return _redirect(f"/admin/settings?tab={tab}")
        else:
            message += " Bot durduruldu."
    _flash(request, message)
    return _redirect(f"/admin/settings?tab={tab}")


@router.post("/bot/restart")
async def bot_restart(request: Request):
    current_admin(request)
    await _form(request)
    await bot_manager.restart()
    st = bot_manager.status()
    if st["running"]:
        _flash(request, f"Bot @{st['username']} yeniden başlatıldı.")
    elif st["error"]:
        _flash(request, f"Bot başlatılamadı: {st['error']}", "error")
    else:
        _flash(request, "Bot kapalı (token yok veya bot pasif).", "error")
    return _redirect(request.headers.get("referer") or "/admin")


# --------------------------------------------------------------------------- broadcast

@router.get("/broadcast")
async def broadcast_page(request: Request):
    current_admin(request)
    count = db.scalar("SELECT COUNT(*) FROM tg_users WHERE banned=0")
    return _page(request, "admin/broadcast.html", {"count": count})


@router.post("/broadcast")
async def broadcast_send(request: Request):
    current_admin(request)
    form = await _form(request)
    text = str(form.get("text", "")).strip()
    if not text:
        _flash(request, "Mesaj boş olamaz.", "error")
        return _redirect("/admin/broadcast")
    if not bot_manager.running:
        _flash(request, "Bot çalışmıyor.", "error")
        return _redirect("/admin/broadcast")

    async def run() -> None:
        ok, fail = await bot_manager.broadcast(text)
        bot_manager.last_broadcast = {"ok": ok, "fail": fail, "at": time.time()}

    asyncio.create_task(run())
    _flash(request, "Duyuru arka planda gönderiliyor.")
    return _redirect("/admin/broadcast")


# --------------------------------------------------------------------------- account & system

@router.get("/account")
async def account_page(request: Request):
    current_admin(request)
    return _page(request, "admin/account.html")


@router.post("/account")
async def account_save(request: Request):
    admin = current_admin(request)
    form = await _form(request)
    row = db.query_one("SELECT password_hash FROM admins WHERE id=?", (admin["id"],))
    if not security.verify_password(str(form.get("current", "")), row["password_hash"]):
        _flash(request, "Mevcut şifre hatalı.", "error")
        return _redirect("/admin/account")
    username = str(form.get("username", "")).strip() or admin["username"]
    new = str(form.get("password", ""))
    if len(username) < 3:
        _flash(request, "Kullanıcı adı en az 3 karakter olmalı.", "error")
        return _redirect("/admin/account")
    if new:
        if len(new) < 8 or new != form.get("password2"):
            _flash(request, "Yeni şifre en az 8 karakter olmalı ve tekrarı eşleşmeli.", "error")
            return _redirect("/admin/account")
        db.execute("UPDATE admins SET password_hash=? WHERE id=?", (security.hash_password(new), admin["id"]))
    try:
        db.execute("UPDATE admins SET username=? WHERE id=?", (username, admin["id"]))
    except Exception:  # noqa: BLE001 - unique constraint
        _flash(request, "Bu kullanıcı adı kullanılıyor.", "error")
        return _redirect("/admin/account")
    _flash(request, "Hesap güncellendi.")
    return _redirect("/admin/account")


def _tool_version(cmd: list[str]) -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError, IndexError):
        return "?"


@router.get("/system")
async def system_page(request: Request):
    current_admin(request)
    usage = shutil.disk_usage(config.DATA_DIR)
    folder = sum(p.stat().st_size for p in config.DOWNLOAD_DIR.rglob("*") if p.is_file())
    info = {
        "ytdlp": downloader.ytdlp_version(),
        "ffmpeg": await asyncio.to_thread(_tool_version, ["ffmpeg", "-version"]),
        "deno": await asyncio.to_thread(_tool_version, ["deno", "--version"]),
        "python": sys.version.split()[0],
        "disk_total": usage.total, "disk_free": usage.free, "downloads_size": folder,
        "data_dir": str(config.DATA_DIR),
        "jobs": len(jobs.manager.jobs),
        "service": config.RUNNING_AS_SERVICE,
        "js": await asyncio.to_thread(downloader.js_status),
    }
    info["js_ok"] = any("(uygun)" in line for line in info["js"])
    return _page(request, "admin/system.html", {
        "info": info, "update_log": _logs.pop("update", None), "diag_log": _logs.get("diag"),
        "diag_url": _logs.get("diag_url", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    })


@router.post("/system/update-ytdlp")
async def update_ytdlp(request: Request):
    current_admin(request)
    await _form(request)

    def run() -> str:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-U", "yt-dlp[default]"],
            capture_output=True, text=True, timeout=600,
        )
        return (proc.stdout + proc.stderr)[-3000:]

    try:
        out = await asyncio.to_thread(run)
    except (OSError, subprocess.SubprocessError) as exc:
        out = str(exc)
    _logs["update"] = out
    _flash(request, "Güncelleme denendi. Yeni sürümün devreye girmesi için uygulamayı yeniden başlatın.")
    return _redirect("/admin/system")


@router.post("/system/diagnose")
async def system_diagnose(request: Request):
    current_admin(request)
    form = await _form(request)
    url = str(form.get("url", "")).strip()
    try:
        url = await asyncio.to_thread(urlguard.normalize, url)
    except urlguard.InvalidURL:
        _flash(request, "Geçerli bir URL girin.", "error")
        return _redirect("/admin/system")
    _logs["diag_url"] = url
    _logs["diag"] = await asyncio.to_thread(downloader.diagnose, url)
    return _redirect("/admin/system#diag")


@router.post("/system/restart")
async def system_restart(request: Request):
    current_admin(request)
    await _form(request)
    if not config.RUNNING_AS_SERVICE:
        _flash(request, "Uygulama servis olarak çalışmıyor; elle yeniden başlatın.", "error")
        return _redirect("/admin/system")

    async def later() -> None:
        await asyncio.sleep(1)
        # The Windows service wrapper (WinSW) restarts the process on a non-zero exit.
        os._exit(3)

    asyncio.create_task(later())
    _flash(request, "Uygulama yeniden başlatılıyor… Birkaç saniye sonra sayfayı yenileyin.")
    return _redirect("/admin/system")


@router.post("/system/cleanup")
async def system_cleanup(request: Request):
    current_admin(request)
    await _form(request)
    jobs.manager.cleanup()
    db.execute("DELETE FROM tg_file_cache WHERE created_at < ?", (time.time() - 30 * 86400,))
    _flash(request, "Temizlik yapıldı.")
    return _redirect("/admin/system")
