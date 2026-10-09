import functools
import http.server
import re
import shutil
import subprocess
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _csrf(client, path):
    r = client.get(path)
    m = re.search(r'name="csrf" value="([^"]+)"', r.text)
    assert m, r.text[:500]
    return m.group(1)


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="fetch-form"' in r.text
    assert client.get("/?lang=en").text.count("Fetch") >= 1


def test_admin_flow(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/setup")

    token = _csrf(client, "/admin/setup")
    r = client.post("/admin/setup", data={"csrf": token, "username": "admin", "password": "short", "password2": "short"})
    assert r.status_code == 400

    r = client.post("/admin/setup", data={"csrf": token, "username": "admin", "password": "longpassword", "password2": "longpassword"},
                    follow_redirects=False)
    assert r.status_code == 303
    for path in ["/admin", "/admin/downloads", "/admin/users", "/admin/broadcast", "/admin/account", "/admin/system",
                 "/admin/settings?tab=general", "/admin/settings?tab=telegram", "/admin/settings?tab=credentials"]:
        assert client.get(path).status_code == 200, path

    token = _csrf(client, "/admin/settings?tab=general")
    r = client.post("/admin/settings", data={"csrf": token, "tab": "general", "site_name": "Kaydet", "web_enabled": "on"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "Kaydet" in client.get("/").text

    # Bad CSRF token is rejected.
    r = client.post("/admin/settings", data={"csrf": "nope", "tab": "general", "site_name": "Hacked"}, follow_redirects=False)
    assert r.status_code == 303 and "/admin/login" in r.headers["location"]
    client.cookies.clear()
    assert "Hacked" not in client.get("/").text

    # Setup is closed once an admin exists; login works.
    assert client.get("/admin/setup", follow_redirects=False).headers["location"] == "/admin/login"
    token = _csrf(client, "/admin/login")
    r = client.post("/admin/login", data={"csrf": token, "username": "admin", "password": "bad"})
    assert r.status_code == 401
    r = client.post("/admin/login", data={"csrf": token, "username": "admin", "password": "longpassword"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"


def test_info_rejects_invalid_and_private_urls(client, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", False)
    r = client.post("/api/info", json={"url": "http://127.0.0.1:1/x"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_url"


@pytest.fixture(scope="module")
def media_server(tmp_path_factory):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    root = tmp_path_factory.mktemp("media")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(root / "clip.mp4")],
        check=True,
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.mark.parametrize("preset,ext", [("best", ".mp4"), ("mp3", ".mp3")])
def test_download_end_to_end(client, media_server, monkeypatch, preset, ext):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", True)
    url = f"{media_server}/clip.mp4"
    info = client.post("/api/info", json={"url": url})
    assert info.status_code == 200, info.text
    assert preset in [p["key"] for p in info.json()["presets"]]

    job = client.post("/api/download", json={"url": url, "preset": preset}).json()
    deadline = time.time() + 60
    while job["status"] not in ("done", "error") and time.time() < deadline:
        time.sleep(0.3)
        job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "done", job
    f = job["files"][0]
    assert f["name"].endswith(ext)
    r = client.get(f["url"])
    assert r.status_code == 200 and len(r.content) == f["size"]
    assert "attachment" in r.headers["content-disposition"]


def test_expired_file_link(client):
    r = client.get("/d/doesnotexist/0")
    assert r.status_code == 404


def test_cloudflare_client_ip(monkeypatch):
    from starlette.requests import Request

    from app import web

    scope = {"type": "http", "headers": [(b"cf-connecting-ip", b"203.0.113.9")], "client": ("127.0.0.1", 5000)}
    monkeypatch.setattr(config, "BEHIND_CLOUDFLARE", False)
    assert web.client_ip(Request(scope)) == "127.0.0.1"
    monkeypatch.setattr(config, "BEHIND_CLOUDFLARE", True)
    assert web.client_ip(Request(scope)) == "203.0.113.9"


def test_system_diagnose(client, media_server, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", True)
    token = _csrf(client, "/admin/login")
    client.post("/admin/login", data={"csrf": token, "username": "admin", "password": "longpassword"})
    token = _csrf(client, "/admin/system")
    r = client.post("/admin/system/diagnose", data={"csrf": token, "url": f"{media_server}/clip.mp4"})
    assert r.status_code == 200
    assert "OK: clip" in r.text and "[debug] params" not in r.text
    assert "yt-dlp JS çözücü" in r.text
