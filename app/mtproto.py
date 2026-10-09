"""Large-file uploads for the Telegram bot over MTProto (Telethon).

The regular Bot API only lets bots upload files up to 50 MB. Logging in to
MTProto with the *same* bot token lifts that to 2 GB without running a local
Bot API server. Updates are still received by python-telegram-bot; this client
is started with ``receive_updates=False`` and is only used to send files.

Needs ``api_id`` / ``api_hash`` from https://my.telegram.org (entered in the
admin panel).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Awaitable, Callable

from telethon import TelegramClient, types

from . import config

log = logging.getLogger("save.mtproto")

MAX_UPLOAD = 2000 * 1024 * 1024

ProgressCallback = Callable[[int, int], Awaitable[None] | None]


class MTProtoUploader:
    def __init__(self) -> None:
        self.client: TelegramClient | None = None
        self.error: str = ""

    @property
    def running(self) -> bool:
        return self.client is not None and self.client.is_connected()

    async def start(self, bot_token: str, api_id: str, api_hash: str) -> None:
        await self.stop()
        self.error = ""
        if not (bot_token and api_id and api_hash):
            return
        try:
            api_id_int = int(str(api_id).strip())
        except ValueError:
            self.error = "API ID sayı olmalı"
            return
        # One session file per bot so a token change doesn't reuse a stale login.
        bot_id = bot_token.split(":", 1)[0]
        session = config.DATA_DIR / f"mtproto-{bot_id}"
        client = TelegramClient(str(session), api_id_int, api_hash.strip(), receive_updates=False,
                                connection_retries=5, request_retries=5, flood_sleep_threshold=120)
        try:
            await client.start(bot_token=bot_token)
        except Exception as exc:  # noqa: BLE001 - surfaced in the admin panel
            self.error = str(exc) or exc.__class__.__name__
            log.error("MTProto login failed: %s", self.error)
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            return
        self.client = client
        log.info("MTProto uploader ready (files up to 2 GB)")

    async def stop(self) -> None:
        client, self.client = self.client, None
        if client:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                log.debug("disconnect failed", exc_info=True)

    async def send(
        self,
        chat_id: int,
        path: Path,
        kind: str,
        caption: str,
        reply_to: int | None = None,
        duration: float | None = None,
        width: int | None = None,
        height: int | None = None,
        title: str = "",
        performer: str = "",
        thumb: Path | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        assert self.client is not None
        attributes: list = [types.DocumentAttributeFilename(path.name)]
        streaming = False
        if kind == "video" and path.suffix.lower() in (".mp4", ".mov", ".m4v"):
            attributes.append(types.DocumentAttributeVideo(
                duration=float(duration or 0), w=int(width or 0), h=int(height or 0), supports_streaming=True))
            streaming = True
        elif kind == "audio":
            attributes.append(types.DocumentAttributeAudio(
                duration=int(duration or 0), title=title[:64] or None, performer=performer[:64] or None))
        await self.client.send_file(
            chat_id,
            str(path),
            caption=caption,
            parse_mode="html",
            reply_to=reply_to,
            attributes=attributes,
            supports_streaming=streaming,
            force_document=kind not in ("video", "audio"),
            thumb=str(thumb) if thumb else None,
            progress_callback=progress,
        )


uploader = MTProtoUploader()
