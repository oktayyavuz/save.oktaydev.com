"""Exercise the bot handlers with fake Telegram objects (no network)."""

import asyncio
import functools
import http.server
import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest

from app import config, db, jobs, settings
from app.bot import BotManager


class FakeMessage:
    _next_id = 1

    def __init__(self, log, text="", photo=None, chat_id=100):
        self.log = log
        self.text = text
        self.photo = photo
        self.chat_id = chat_id
        self.message_id = FakeMessage._next_id
        FakeMessage._next_id += 1
        self.reply_markup = None

    async def reply_text(self, text, **kw):
        self.log.append(("reply_text", text))
        msg = FakeMessage(self.log, text)
        msg.reply_markup = kw.get("reply_markup")
        return msg

    async def reply_photo(self, photo, caption=None, **kw):
        self.log.append(("reply_photo", caption))
        msg = FakeMessage(self.log, caption, photo=[photo])
        msg.reply_markup = kw.get("reply_markup")
        self.log.append(("card", msg))
        return msg

    async def edit_text(self, text, **kw):
        self.text = text
        self.reply_markup = kw.get("reply_markup")
        self.log.append(("edit", text))

    async def edit_caption(self, caption, **kw):
        await self.edit_text(caption, **kw)

    async def delete(self):
        self.log.append(("delete", self.message_id))


class FakeBot:
    def __init__(self, log):
        self.log = log

    async def send_video(self, chat_id, video, **kw):
        self.log.append(("send_video", kw.get("filename")))
        return SimpleNamespace(video=SimpleNamespace(file_id="VID1"), document=None)

    async def send_audio(self, chat_id, audio, **kw):
        self.log.append(("send_audio", kw.get("filename")))
        return SimpleNamespace(audio=SimpleNamespace(file_id="AUD1"), document=None)

    async def send_document(self, chat_id, doc, **kw):
        self.log.append(("send_document", kw.get("filename")))
        return SimpleNamespace(document=SimpleNamespace(file_id="DOC1"))

    async def send_message(self, chat_id, text, **kw):
        self.log.append(("send_message", text))

    async def send_chat_action(self, *a, **kw):
        pass


def _update(log, text=None, data=None, message=None):
    user = SimpleNamespace(id=42, username="tester", first_name="Test", language_code="tr")
    chat = SimpleNamespace(type="private", id=100)
    msg = message or FakeMessage(log, text or "")
    upd = SimpleNamespace(effective_user=user, effective_chat=chat, effective_message=msg, callback_query=None)
    if data:
        async def answer(*a, **kw):
            return None
        upd.callback_query = SimpleNamespace(data=data, message=msg, answer=answer)
    return upd


@pytest.fixture()
def media_url(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(tmp_path / "bot.mp4")],
        check=True,
    )
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", True)
    yield f"http://127.0.0.1:{server.server_address[1]}/bot.mp4"
    server.shutdown()


def test_bot_download_flow(media_url):
    async def run():
        await jobs.manager.start()
        try:
            log: list = []
            bm = BotManager()
            bm.username = "savebot"
            ctx = SimpleNamespace(bot=FakeBot(log))

            await bm.on_message(_update(log, text=f"şunu indir {media_url} lütfen"), ctx)
            edits = [e for e in log if e[0] == "edit"]
            assert edits, log
            card_text = edits[-1][1]
            assert "Format" in card_text or "format" in card_text
            # The analyzing message became the card with buttons.
            status_msgs = [m for m in log if m[0] == "reply_text"]
            assert status_msgs

            token = next(iter(bm._pending))
            card = FakeMessage(log, card_text)
            await bm.on_callback(_update(log, data=f"d:{token}:best", message=card), ctx)
            assert ("send_video", "bot.mp4") in log, log
            assert card.text.endswith("✅") and card.reply_markup is not None

            # Second request for the same format is served from the file_id cache.
            log.clear()
            await bm.on_callback(_update(log, data=f"d:{token}:best", message=card), ctx)
            assert ("send_video", None) in log

            await bm.on_callback(_update(log, data=f"d:{token}:mp3", message=card), ctx)
            assert ("send_audio", "bot.mp3") in log

            row = db.query_one("SELECT downloads, banned FROM tg_users WHERE id=42")
            assert row["downloads"] == 3

            # Banned users are refused.
            db.execute("UPDATE tg_users SET banned=1 WHERE id=42")
            log.clear()
            await bm.on_message(_update(log, text=media_url), ctx)
            assert log and "⛔" in log[0][1]
            db.execute("UPDATE tg_users SET banned=0 WHERE id=42")
        finally:
            await jobs.manager.stop()

    asyncio.run(run())


def test_bot_large_file_sends_link(media_url, monkeypatch):
    async def run():
        await jobs.manager.start()
        try:
            log: list = []
            bm = BotManager()
            monkeypatch.setattr(BotManager, "upload_limit", property(lambda self: 10))
            settings.set_many({"public_base_url": "https://save.example.com"})
            ctx = SimpleNamespace(bot=FakeBot(log))
            await bm.on_message(_update(log, text=media_url), ctx)
            token = next(iter(bm._pending))
            await bm.on_callback(_update(log, data=f"d:{token}:m4a", message=FakeMessage(log)), ctx)
            sent = [e for e in log if e[0] == "send_message"]
            assert sent and "büyük" in sent[0][1]
        finally:
            settings.set_many({"public_base_url": ""})
            await jobs.manager.stop()

    asyncio.run(run())


class FakeUploader:
    running = True
    error = ""

    def __init__(self):
        self.sent = []

    async def send(self, chat_id, path, kind, caption, **kw):
        if kw.get("progress"):
            await kw["progress"](50, 100)
        self.sent.append((path.name, kind, kw.get("duration"), kw.get("width"), kw.get("thumb") is not None))


def test_bot_large_file_goes_over_mtproto(media_url, monkeypatch):
    import app.bot as botmod

    async def run():
        await jobs.manager.start()
        try:
            log: list = []
            fake = FakeUploader()
            monkeypatch.setattr(botmod, "uploader", fake)
            monkeypatch.setattr(botmod, "CLOUD_LIMIT", 10)  # every file counts as "large"
            bm = BotManager()
            assert bm.upload_limit == botmod.MAX_UPLOAD
            ctx = SimpleNamespace(bot=FakeBot(log))
            await bm.on_message(_update(log, text=media_url), ctx)
            token = next(iter(bm._pending))
            card = FakeMessage(log)
            await bm.on_callback(_update(log, data=f"d:{token}:best", message=card), ctx)
            assert len(fake.sent) == 1, log
            name, kind, duration, width, has_thumb = fake.sent[0]
            assert name == "bot.mp4" and kind == "video"
            assert duration and width == 320 and has_thumb
            assert not [e for e in log if e[0] in ("send_video", "send_message")]
            assert card.text.endswith("✅")
        finally:
            await jobs.manager.stop()

    asyncio.run(run())
