"""Telegram bot running inside the web process (long polling).

The token and other options come from the admin panel; saving them restarts
the bot without restarting the server.
"""

from __future__ import annotations

import asyncio
import html
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    Update,
)
from telegram.constants import ChatAction, ChatMemberStatus, ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import config, db, downloader, jobs, settings, urlguard
from .i18n import human_size, pick_lang, t
from .mtproto import MAX_UPLOAD, uploader
from .ratelimit import limiter

log = logging.getLogger("save.bot")

CLOUD_LIMIT = 50 * 1024 * 1024
LOCAL_LIMIT = 2000 * 1024 * 1024
PENDING_TTL = 3600


@dataclass
class Pending:
    url: str
    title: str
    platform: str
    is_playlist: bool
    count: int
    created: float
    markup: InlineKeyboardMarkup | None = None


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _retry_seconds(exc: RetryAfter) -> float:
    value = exc.retry_after
    return value.total_seconds() if hasattr(value, "total_seconds") else float(value)


def _progress_bar(percent: float | None) -> str:
    if percent is None:
        return ""
    filled = int(percent // 10)
    return "▰" * filled + "▱" * (10 - filled) + f" {percent:.0f}%"


class BotManager:
    def __init__(self) -> None:
        self.app: Application | None = None
        self.username: str = ""
        self.error: str = ""
        self.started_at: float | None = None
        self.last_broadcast: dict[str, Any] | None = None
        self._pending: dict[str, Pending] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle
    @property
    def running(self) -> bool:
        return self.app is not None and self.app.running

    @property
    def upload_limit(self) -> int:
        if settings.get("telegram_api_base"):
            return LOCAL_LIMIT
        if uploader.running:
            return MAX_UPLOAD
        return CLOUD_LIMIT

    async def start(self) -> None:
        async with self._lock:
            await self._start()

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def restart(self) -> None:
        async with self._lock:
            await self._stop()
            await self._start()

    async def _start(self) -> None:
        self.error = ""
        if config.DISABLE_BOT:
            return
        token = settings.get("telegram_bot_token")
        if not settings.get("telegram_enabled") or not token:
            return
        builder = (
            Application.builder()
            .token(token)
            .concurrent_updates(True)
            .connect_timeout(30)
            .read_timeout(60)
            .write_timeout(600)
            .media_write_timeout(1800)
            .pool_timeout(30)
        )
        api_base = (settings.get("telegram_api_base") or "").rstrip("/")
        if api_base:
            builder = builder.base_url(f"{api_base}/bot").base_file_url(f"{api_base}/file/bot")
        app = builder.build()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("stats", self.cmd_stats))
        app.add_handler(CommandHandler("broadcast", self.cmd_broadcast))
        app.add_handler(CallbackQueryHandler(self.on_callback, pattern=r"^d:"))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message))
        app.add_error_handler(self.on_error)
        try:
            await app.initialize()
            me = await app.bot.get_me()
            self.username = me.username or ""
            await app.start()
            assert app.updater is not None
            await app.updater.start_polling(allowed_updates=["message", "callback_query"])
            try:
                await app.bot.set_my_commands(
                    [BotCommand("start", "Başlat"), BotCommand("help", "Yardım")]
                )
            except TelegramError:
                pass
        except Exception as exc:  # noqa: BLE001 - surface any failure in the admin panel
            self.error = str(exc) or exc.__class__.__name__
            log.error("Telegram bot failed to start: %s", self.error)
            try:
                await app.shutdown()
            except Exception:  # noqa: BLE001
                pass
            return
        self.app = app
        self.started_at = time.time()
        log.info("Telegram bot @%s started", self.username)
        if not settings.get("telegram_api_base"):
            await uploader.start(token, settings.get("telegram_api_id"), settings.get("telegram_api_hash"))

    async def _stop(self) -> None:
        await uploader.stop()
        app, self.app = self.app, None
        self.started_at = None
        if not app:
            return
        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()
            await app.shutdown()
        except Exception:  # noqa: BLE001
            log.exception("error while stopping bot")

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "username": self.username if self.running else "",
            "error": self.error,
            "started_at": self.started_at,
            "upload_limit": self.upload_limit,
            "mtproto": uploader.running,
            "mtproto_error": uploader.error,
        }

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _touch_user(update: Update) -> tuple[dict[str, Any], str]:
        user = update.effective_user
        assert user is not None
        now = time.time()
        db.execute(
            "INSERT INTO tg_users(id, username, first_name, language, created_at, last_seen) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, "
            "language=excluded.language, last_seen=excluded.last_seen",
            (user.id, user.username, user.first_name, user.language_code, now, now),
        )
        row = db.query_one("SELECT * FROM tg_users WHERE id=?", (user.id,))
        return dict(row) if row else {}, pick_lang(user.language_code)

    async def _is_member(self, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
        channel = (settings.get("telegram_force_channel") or "").strip()
        if not channel or user_id in settings.admin_ids():
            return True
        try:
            member = await context.bot.get_chat_member(channel, user_id)
        except TelegramError as exc:
            log.warning("force-join check failed for %s: %s", channel, exc)
            return True  # fail open: a misconfigured channel shouldn't lock everyone out
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.RESTRICTED,
        )

    def _join_markup(self, lang: str) -> InlineKeyboardMarkup | None:
        channel = (settings.get("telegram_force_channel") or "").strip()
        if channel.startswith("@"):
            link = f"https://t.me/{channel[1:]}"
        elif channel.startswith("https://"):
            link = channel
        else:
            return None
        return InlineKeyboardMarkup([[InlineKeyboardButton(t("bot.join_btn", lang), url=link)]])

    async def _gate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
        """Common checks. Returns the user's language or None if blocked."""
        user, lang = self._touch_user(update)
        target = update.effective_message
        if user.get("banned"):
            if target:
                await target.reply_text(t("bot.banned", lang))
            return None
        if not await self._is_member(context, update.effective_user.id):
            if target:
                await target.reply_text(t("bot.join", lang), reply_markup=self._join_markup(lang))
            return None
        return lang

    @staticmethod
    async def _edit(message: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            if message.photo:
                await message.edit_caption(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            else:
                await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                        link_preview_options=LinkPreviewOptions(is_disabled=True))
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise
        except RetryAfter as exc:
            await asyncio.sleep(_retry_seconds(exc))

    def _prune_pending(self) -> None:
        now = time.time()
        for key in [k for k, p in self._pending.items() if now - p.created > PENDING_TTL]:
            del self._pending[key]

    # ------------------------------------------------------------------ commands
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        _user, lang = self._touch_user(update)
        custom = settings.get("telegram_welcome")
        text = html.escape(custom) if custom else t("bot.welcome", lang, name=html.escape(settings.get("site_name")))
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        _user, lang = self._touch_user(update)
        await update.effective_message.reply_text(t("bot.help", lang), parse_mode=ParseMode.HTML)

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id not in settings.admin_ids():
            return
        day = time.time() - 86400
        text = (
            "📊 <b>İstatistikler</b>\n"
            f"Kullanıcı: {db.scalar('SELECT COUNT(*) FROM tg_users')}\n"
            f"Aktif (24s): {db.scalar('SELECT COUNT(*) FROM tg_users WHERE last_seen > ?', (day,))}\n"
            f"İndirme (24s): {db.scalar('SELECT COUNT(*) FROM downloads WHERE created_at > ?', (day,))}\n"
            f"Toplam indirme: {db.scalar('SELECT COUNT(*) FROM downloads')}\n"
            f"Kuyruk: {len(jobs.manager.active())}"
        )
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    async def cmd_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id not in settings.admin_ids():
            return
        text = update.effective_message.text.partition(" ")[2].strip()
        if not text:
            await update.effective_message.reply_text("Kullanım: /broadcast mesaj")
            return
        await update.effective_message.reply_text("📣 Gönderiliyor…")
        ok, fail = await self.broadcast(text)
        await update.effective_message.reply_text(f"✅ {ok} başarılı, ❌ {fail} başarısız")

    async def broadcast(self, text: str) -> tuple[int, int]:
        if not self.app:
            raise RuntimeError("bot is not running")
        ok = fail = 0
        for row in db.query("SELECT id FROM tg_users WHERE banned=0"):
            try:
                await self.app.bot.send_message(row["id"], text, parse_mode=ParseMode.HTML)
                ok += 1
            except RetryAfter as exc:
                await asyncio.sleep(_retry_seconds(exc))
                fail += 1
            except TelegramError:
                fail += 1
            await asyncio.sleep(0.05)
        return ok, fail

    # ------------------------------------------------------------------ download flow
    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not message or not update.effective_user:
            return
        urls = urlguard.find_urls(message.text or "")
        private = update.effective_chat.type == ChatType.PRIVATE
        if not urls:
            if private:
                _u, lang = self._touch_user(update)
                await message.reply_text(t("bot.no_link", lang))
            return
        lang = await self._gate(update, context)
        if not lang:
            return

        status = await message.reply_text(t("bot.analyzing", lang))
        try:
            url = urlguard.normalize(urls[0])
            info = await asyncio.to_thread(downloader.extract_info, url)
        except urlguard.InvalidURL:
            await self._edit(status, t("err.invalid_url", lang))
            return
        except downloader.DownloadFailed as exc:
            await self._edit(status, "❌ " + t(f"err.{exc.code}", lang))
            return

        self._prune_pending()
        token = secrets.token_urlsafe(6)
        self._pending[token] = Pending(
            url=info.url,
            title=info.title,
            platform=info.platform,
            is_playlist=info.is_playlist,
            count=len(info.entries),
            created=time.time(),
        )

        buttons: list[InlineKeyboardButton] = []
        for p in info.presets:
            icon = "🎵" if p["kind"] == "audio" else "🎬"
            size = f" · {human_size(p['size'])}" if p.get("size") else ""
            buttons.append(InlineKeyboardButton(f"{icon} {p['label']}{size}", callback_data=f"d:{token}:{p['key']}"))
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        markup = InlineKeyboardMarkup(rows)
        self._pending[token].markup = markup

        lines = [f"<b>{html.escape(info.title)}</b>"]
        meta = " · ".join(x for x in (html.escape(info.uploader), _fmt_duration(info.duration), html.escape(info.platform)) if x)
        if meta:
            lines.append(meta)
        if info.is_playlist:
            lines.append(t("bot.items", lang, n=len(info.entries), max=settings.get("max_playlist_items")))
        lines.append("")
        lines.append(t("bot.choose", lang))
        caption = "\n".join(lines)

        if info.thumbnail:
            try:
                await status.delete()
                await message.reply_photo(info.thumbnail, caption=caption, parse_mode=ParseMode.HTML, reply_markup=markup)
                return
            except TelegramError:
                status = await message.reply_text(t("bot.analyzing", lang))
        await self._edit(status, caption, markup)

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        _prefix, token, preset = (query.data or "").split(":", 2)
        lang = await self._gate(update, context)
        if not lang:
            return
        pending = self._pending.get(token)
        card = query.message
        if not pending or preset not in downloader.PRESETS:
            await self._edit(card, t("bot.expired", lang))
            return
        user_id = update.effective_user.id
        if user_id not in settings.admin_ids() and not limiter.hit(f"tg:{user_id}", settings.get("bot_rate_limit")):
            await card.reply_text(t("err.rate_limited", lang))
            return

        header = f"<b>{html.escape(pending.title)}</b>\n\n"
        chat_id = card.chat_id

        cache_key = f"{pending.url}|{preset}"
        if not pending.is_playlist:
            cached = db.query_one("SELECT file_id, kind FROM tg_file_cache WHERE cache_key=?", (cache_key,))
            if cached:
                try:
                    await self._send_cached(context, chat_id, cached["file_id"], cached["kind"], card.message_id)
                    await self._edit(card, header + "✅", pending.markup)
                    db.execute("UPDATE tg_users SET downloads=downloads+1 WHERE id=?", (user_id,))
                    db.execute(
                        "INSERT INTO downloads(id, url, preset, source, requester, title, platform, status, created_at, finished_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (downloader.new_id(), pending.url, preset, "telegram", str(user_id), pending.title,
                         pending.platform, "done", time.time(), time.time()),
                    )
                    return
                except TelegramError:
                    db.execute("DELETE FROM tg_file_cache WHERE cache_key=?", (cache_key,))

        job = jobs.manager.submit(
            pending.url, preset, "telegram", str(user_id),
            all_items=pending.is_playlist, title=pending.title, platform=pending.platform,
        )
        last_text = ""

        async def on_update(j: jobs.Job) -> None:
            nonlocal last_text
            if j.status == jobs.QUEUED:
                text = t("bot.queued", lang, pos=j.public()["position"] or 1)
            elif j.status == jobs.PROCESSING:
                text = t("bot.processing", lang)
            else:
                prog = _progress_bar(j.percent)
                if j.total:
                    prog += f"\n{human_size(j.downloaded)} / {human_size(j.total)}"
                if j.speed:
                    prog += f" · {human_size(j.speed)}/s"
                if pending.is_playlist and j.current_item:
                    prog += f"\n#{j.current_item}/{min(pending.count, settings.get('max_playlist_items'))}"
                text = t("bot.downloading", lang, progress=("\n" + prog) if prog else "")
            if text != last_text:
                last_text = text
                await self._edit(card, header + text)

        await on_update(job)
        await jobs.manager.wait(job, on_update, interval=3.0)

        if job.status == jobs.ERROR:
            await self._edit(card, header + "❌ " + t(f"err.{job.error_code}", lang), pending.markup)
            return

        await self._edit(card, header + t("bot.uploading", lang))
        sent_any = False
        for index, f in enumerate(job.files):
            try:
                ok = await self._send_file(context, chat_id, job, index, f, lang, card,
                                           cache_key if len(job.files) == 1 else None, header)
                sent_any = sent_any or ok
            except Exception as exc:  # noqa: BLE001 - Bot API or MTProto upload failure
                log.warning("upload failed: %s", exc)
                await context.bot.send_message(chat_id, "❌ " + t("err.generic", lang))
        # Restore the buttons so another format can be picked from the same card.
        await self._edit(card, header + ("✅" if sent_any else "📦"), pending.markup)
        db.execute("UPDATE tg_users SET downloads=downloads+1 WHERE id=?", (user_id,))

    async def _send_cached(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, file_id: str, kind: str,
                           reply_to: int) -> None:
        caption = self._caption()
        kwargs = {"caption": caption, "parse_mode": ParseMode.HTML, "reply_to_message_id": reply_to}
        if kind == "video":
            await context.bot.send_video(chat_id, file_id, supports_streaming=True, **kwargs)
        elif kind == "audio":
            await context.bot.send_audio(chat_id, file_id, **kwargs)
        else:
            await context.bot.send_document(chat_id, file_id, **kwargs)

    def _caption(self) -> str:
        base = (settings.get("public_base_url") or "").rstrip("/")
        bot = f"@{self.username}" if self.username else settings.get("site_name")
        if base:
            return f"📥 {html.escape(bot)} · <a href=\"{html.escape(base)}\">{html.escape(urlguard.domain_of(base))}</a>"
        return f"📥 {html.escape(bot)}"

    async def _send_file(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, job: jobs.Job, index: int,
                         f: downloader.DownloadedFile, lang: str, card: Message, cache_key: str | None,
                         header: str = "") -> bool:
        reply_to = card.message_id
        if f.size > self.upload_limit:
            base = (settings.get("public_base_url") or "").rstrip("/")
            if base:
                link = f"{base}/d/{job.id}/{index}"
                await context.bot.send_message(
                    chat_id,
                    t("bot.too_big_link", lang, size=human_size(f.size), ttl=settings.get("file_ttl_min")),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t("bot.download_btn", lang), url=link)]]),
                    reply_to_message_id=reply_to,
                )
            else:
                await context.bot.send_message(chat_id, t("bot.too_big", lang, size=human_size(f.size)),
                                               reply_to_message_id=reply_to)
            return False

        caption = self._caption()
        is_video = f.kind == "video" and f.path.suffix.lower() in (".mp4", ".mov", ".m4v")
        thumb = None
        if is_video:
            if not (f.duration and f.width and f.height):
                meta = await asyncio.to_thread(downloader.probe, f.path)
                f.duration = f.duration or meta.get("duration")
                f.width = f.width or meta.get("width")
                f.height = f.height or meta.get("height")
            thumb = await asyncio.to_thread(downloader.make_thumbnail, f.path)

        if f.size > CLOUD_LIMIT and uploader.running and not settings.get("telegram_api_base"):
            # Too big for the Bot API: upload the file itself over MTProto (up to 2 GB).
            last = {"t": 0.0}

            async def progress(sent: int, total: int) -> None:
                now = time.monotonic()
                if now - last["t"] < 4 or not total:
                    return
                last["t"] = now
                await self._edit(card, header + t("bot.uploading", lang) + "\n" + _progress_bar(sent / total * 100))

            await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO if is_video else ChatAction.UPLOAD_DOCUMENT)
            await uploader.send(
                chat_id, f.path, "video" if is_video else f.kind, caption, reply_to=reply_to,
                duration=f.duration, width=f.width, height=f.height, title=f.title, performer=f.uploader,
                thumb=thumb, progress=progress,
            )
            return True

        common = {
            "caption": caption,
            "parse_mode": ParseMode.HTML,
            "reply_to_message_id": reply_to,
            "filename": f.name,
        }
        with f.path.open("rb") as fh:
            if is_video:
                await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
                msg = await context.bot.send_video(
                    chat_id, fh, duration=int(f.duration) if f.duration else None,
                    width=f.width, height=f.height, supports_streaming=True,
                    thumbnail=thumb.read_bytes() if thumb else None, **common,
                )
                file_id, kind = (msg.video.file_id if msg.video else msg.document.file_id), "video"
            elif f.kind == "audio":
                await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VOICE)
                msg = await context.bot.send_audio(
                    chat_id, fh, duration=int(f.duration) if f.duration else None,
                    title=f.title[:64], performer=(f.uploader or None), **common,
                )
                file_id, kind = (msg.audio.file_id if msg.audio else msg.document.file_id), "audio"
            else:
                await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
                msg = await context.bot.send_document(chat_id, fh, **common)
                file_id, kind = msg.document.file_id, "document"
        if cache_key and file_id:
            db.execute(
                "INSERT OR REPLACE INTO tg_file_cache(cache_key, file_id, kind, created_at) VALUES(?,?,?,?)",
                (cache_key, file_id, kind, time.time()),
            )
        return True

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        err = context.error
        if isinstance(err, Forbidden):
            return  # user blocked the bot
        log.warning("bot handler error: %s", err, exc_info=err)


bot_manager = BotManager()
