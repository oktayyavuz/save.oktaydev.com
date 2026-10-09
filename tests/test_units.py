import pytest

from app import config, db, downloader, security, settings, urlguard


def test_password_hash_roundtrip():
    h = security.hash_password("hunter22")
    assert security.verify_password("hunter22", h)
    assert not security.verify_password("wrong", h)
    assert not security.verify_password("x", "garbage")


def test_encrypt_roundtrip():
    token = security.encrypt("123:ABC")
    assert token != "123:ABC"
    assert security.decrypt(token) == "123:ABC"
    assert security.decrypt("not-a-token") == ""


def test_settings_secret_is_encrypted_and_ints_clamped():
    changed = settings.set_many({"telegram_bot_token": " 42:secret ", "max_concurrent": 999, "web_enabled": False})
    assert set(changed) == {"telegram_bot_token", "max_concurrent", "web_enabled"}
    row = db.query_one("SELECT value, encrypted FROM settings WHERE key='telegram_bot_token'")
    assert row["encrypted"] == 1 and "secret" not in row["value"]
    settings.reset_cache()
    assert settings.get("telegram_bot_token") == "42:secret"
    assert settings.get("max_concurrent") == 32
    assert settings.get("web_enabled") is False
    assert settings.set_many({"max_concurrent": 32}) == []
    settings.set_many({"web_enabled": True, "max_concurrent": 3, "telegram_bot_token": ""})


def test_admin_ids_parsing():
    settings.set_many({"telegram_admin_ids": "1, 22,abc,-100"})
    assert settings.admin_ids() == {1, 22, -100}
    settings.set_many({"telegram_admin_ids": ""})


def test_find_urls():
    text = "bak şuna https://youtu.be/abc123). ve http://x.com/a/status/1?s=20"
    assert urlguard.find_urls(text) == ["https://youtu.be/abc123", "http://x.com/a/status/1?s=20"]


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/a", "http://localhost:8000", "http://10.0.0.5/x", "http://[::1]/",
    "http://169.254.169.254/latest/meta-data", "ftp://example.com/a", "http://user:pw@example.com/",
])
def test_normalize_blocks_unsafe(monkeypatch, url):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", False)
    with pytest.raises(urlguard.InvalidURL):
        urlguard.normalize(url)


def test_normalize_adds_scheme(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", True)
    assert urlguard.normalize("  example.com/v ") == "https://example.com/v"


@pytest.mark.parametrize("message,code", [
    ("ERROR: Unsupported URL: https://a.b", "unsupported"),
    ("Sign in to confirm you're not a bot", "login_required"),
    ("ERROR: [Instagram] abc: Requested content is not available, rate-limit reached or login required", "login_required"),
    ("Private video. Sign in if you've been granted access", "private"),
    ("HTTP Error 404: Not Found", "not_found"),
    ("something odd", "generic"),
])
def test_classify_error(message, code):
    assert downloader.classify_error(message) == code


def test_cookie_key_for():
    assert downloader.cookie_key_for("https://www.youtube.com/watch?v=x") == "youtube"
    assert downloader.cookie_key_for("https://m.youtube.com/watch?v=x") == "youtube"
    assert downloader.cookie_key_for("https://twitter.com/a/status/1") == "x"
    assert downloader.cookie_key_for("https://www.instagram.com/reel/abc/") == "instagram"
    assert downloader.cookie_key_for("https://example.org/v") == "generic"


def test_build_presets_only_offers_available_heights():
    info = {"formats": [
        {"format_id": "a", "vcodec": "none", "acodec": "mp4a", "abr": 128, "filesize": 1000},
        {"format_id": "v1", "vcodec": "avc1", "acodec": "none", "height": 720, "filesize": 5000},
        {"format_id": "v2", "vcodec": "avc1", "acodec": "none", "height": 360, "filesize": 2000},
    ]}
    presets, heights, has_video = downloader._build_presets(info, 60)
    keys = [p["key"] for p in presets]
    assert has_video and heights == [360, 720]
    assert keys == ["best", "720", "360", "mp3", "m4a"]
    by_key = {p["key"]: p for p in presets}
    assert by_key["720"]["size"] == 6000
    assert by_key["best"]["label"] == "En iyi (720p)"


def test_build_presets_audio_only():
    info = {"formats": [{"format_id": "a", "vcodec": "none", "acodec": "opus", "ext": "webm"}]}
    presets, _, has_video = downloader._build_presets(info, 100)
    assert not has_video
    assert [p["key"] for p in presets] == ["mp3", "m4a"]


def test_preset_options_prefer_h264_for_fixed_heights():
    opts = downloader.preset_options(downloader.PRESETS["720"])
    assert opts["format_sort"][0] == "res:720" and "vcodec:h264" in opts["format_sort"]
    mp3 = downloader.preset_options(downloader.PRESETS["mp3"])
    assert mp3["postprocessors"][0]["preferredcodec"] == "mp3"
