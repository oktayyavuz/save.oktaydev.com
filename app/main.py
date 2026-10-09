"""Application entry point: ``uvicorn app.main:app``."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import config, db, security
from .bot import bot_manager
from .jobs import manager
from .routes import admin, public

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("save")


def _bootstrap_admin() -> None:
    if not config.BOOTSTRAP_ADMIN_USER or not config.BOOTSTRAP_ADMIN_PASSWORD:
        return
    if db.scalar("SELECT COUNT(*) FROM admins"):
        return
    db.execute(
        "INSERT INTO admins(username, password_hash, created_at) VALUES(?,?,?)",
        (config.BOOTSTRAP_ADMIN_USER, security.hash_password(config.BOOTSTRAP_ADMIN_PASSWORD), time.time()),
    )
    log.info("Created bootstrap admin %r", config.BOOTSTRAP_ADMIN_USER)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.ensure_dirs()
    db.connect()
    _bootstrap_admin()
    await manager.start()
    await bot_manager.start()
    try:
        yield
    finally:
        await bot_manager.stop()
        await manager.stop()
        db.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    session_cookie="save_session",
    max_age=7 * 86400,
    same_site="lax",
    https_only=config.SECURE_COOKIES,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/admin"):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cache-Control", "no-store")
    else:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.exception_handler(admin.NotAuthenticated)
async def _not_authenticated(request: Request, _exc: admin.NotAuthenticated):
    if request.url.path.startswith("/admin/api"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": "auth"}, status_code=401)
    target = "/admin/login" if admin.has_admin() else "/admin/setup"
    if request.method == "GET" and request.url.path not in ("/admin/login", "/admin/setup"):
        target += f"?next={request.url.path}"
    return RedirectResponse(target, status_code=303)


app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")
app.include_router(public.router)
app.include_router(admin.router)
