"""yt-dlp wrapper: metadata extraction, format presets and downloading.

All functions here are blocking and are meant to be run in a worker thread.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from . import config, settings, urlguard

log = logging.getLogger("save.downloader")


# --------------------------------------------------------------------------- presets

@dataclass(frozen=True)
class Preset:
    key: str
    kind: str  # video | audio
    label: str
    height: int | None = None


PRESETS: dict[str, Preset] = {
    p.key: p
    for p in (
        Preset("best", "video", "En iyi"),
        Preset("1080", "video", "1080p", 1080),
        Preset("720", "video", "720p", 720),
        Preset("480", "video", "480p", 480),
        Preset("360", "video", "360p", 360),
        Preset("mp3", "audio", "MP3"),
        Preset("m4a", "audio", "M4A"),
    )
}


def preset_options(preset: Preset) -> dict[str, Any]:
    if preset.kind == "audio":
        opts: dict[str, Any] = {"format": "ba/b"}
        if preset.key == "mp3":
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail", "already_have_thumbnail": False},
            ]
            opts["writethumbnail"] = True
        else:
            opts["format"] = "ba[ext=m4a]/ba/b"
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "m4a"},
                {"key": "FFmpegMetadata", "add_metadata": True},
            ]
        return opts

    # Prefer H.264/AAC in MP4 so the result plays everywhere (incl. Telegram).
    sort = ["vcodec:h264", "acodec:aac", "ext:mp4:m4a"]
    if preset.height:
        sort.insert(0, f"res:{preset.height}")
    else:
        sort = ["res", "ext:mp4:m4a"]
    return {
        "format": "bv*+ba/b",
        "format_sort": sort,
        "merge_output_format": "mp4/mkv",
        "postprocessors": [{"key": "FFmpegMetadata", "add_metadata": True}],
    }


# --------------------------------------------------------------------------- errors

class DownloadFailed(Exception):
    """User-facing error with a stable ``code`` for translation."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


_ERROR_PATTERNS: list[tuple[str, str]] = [
    (r"unsupported url", "unsupported"),
    (r"(sign in to confirm|confirm you.re not a bot|login required|log in|logged-in|rate-limit reached|requires authentication|cookies)", "login_required"),
    (r"(private video|this video is private|private account|is private)", "private"),
    (r"(not available in your country|geo.?restrict|blocked it in your country)", "geo"),
    (r"(age.?restricted|confirm your age|inappropriate for some users)", "age"),
    (r"(http error 404|not found|does not exist|has been removed|video unavailable|no longer available|deleted)", "not_found"),
    (r"(no video formats found|no formats found|requested format is not available)", "no_media"),
    (r"(is live|live event|premieres in)", "live"),
    (r"(file is larger than max-filesize|max-filesize)", "too_large"),
    (r"(timed out|connection reset|temporarily unavailable|http error 5\d\d|unable to download webpage)", "network"),
]


def classify_error(message: str) -> str:
    text = (message or "").lower()
    for pattern, code in _ERROR_PATTERNS:
        if re.search(pattern, text):
            return code
    return "generic"


def _clean_message(message: str) -> str:
    message = re.sub(r"\x1b\[[0-9;]*m", "", message or "")
    message = message.replace("ERROR: ", "")
    return message.strip()[:500]


class _Logger:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            log.debug(msg)

    def info(self, msg: str) -> None:
        log.debug(msg)

    def warning(self, msg: str) -> None:
        log.info("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        log.warning("yt-dlp error: %s", msg)


# --------------------------------------------------------------------------- options

def cookie_key_for(url: str) -> str:
    domain = urlguard.domain_of(url)
    for key, _name, domains in settings.COOKIE_PLATFORMS:
        if any(domain == d or domain.endswith("." + d) for d in domains):
            return key
    return "generic"


@contextlib.contextmanager
def _cookie_file(url: str, directory: Path | None) -> Iterator[str | None]:
    content = settings.get(f"cookies_{cookie_key_for(url)}") or ""
    if not content.strip():
        yield None
        return
    target_dir = directory or config.COOKIE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=".cookies-", suffix=".txt", dir=target_dir)
    try:
        with os.fdopen(fd, "w") as fh:
            if not content.lstrip().startswith("# "):
                fh.write("# Netscape HTTP Cookie File\n")
            fh.write(content.strip() + "\n")
        yield path
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


def _base_options(logger: _Logger) -> dict[str, Any]:
    s = settings.all_settings()
    opts: dict[str, Any] = {
        "logger": logger,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "playlistend": s["max_playlist_items"],
        "extract_flat": "in_playlist",
        "windowsfilenames": True,
        "trim_file_name": 120,
        "check_formats": False,
        "color": {"stdout": "no_color", "stderr": "no_color"},
    }
    if s["proxy"]:
        opts["proxy"] = s["proxy"]
    if s["user_agent"]:
        opts["http_headers"] = {"User-Agent": s["user_agent"]}
    if s["source_address"]:
        opts["source_address"] = s["source_address"]
    return opts


# --------------------------------------------------------------------------- info

@dataclass
class MediaInfo:
    url: str
    title: str
    platform: str
    uploader: str = ""
    duration: float | None = None
    thumbnail: str = ""
    is_playlist: bool = False
    entries: list[dict[str, Any]] = field(default_factory=list)
    heights: list[int] = field(default_factory=list)
    has_video: bool = True
    presets: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "platform": self.platform,
            "uploader": self.uploader,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "is_playlist": self.is_playlist,
            "entries": self.entries,
            "presets": self.presets,
        }


_info_cache: dict[str, tuple[float, MediaInfo]] = {}
_info_lock = threading.Lock()
_INFO_TTL = 600


def _thumb(info: dict[str, Any]) -> str:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbs = info.get("thumbnails") or []
    for t in reversed(thumbs):
        if t.get("url"):
            return t["url"]
    return ""


def _estimate_size(formats: list[dict[str, Any]], preset: Preset, duration: float | None) -> int | None:
    def size(f: dict[str, Any]) -> int | None:
        if f.get("filesize") or f.get("filesize_approx"):
            return f.get("filesize") or f.get("filesize_approx")
        if f.get("tbr") and duration:
            return int(f["tbr"] * 1000 / 8 * duration)
        return None

    audios = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")]
    best_audio = max(audios, key=lambda f: f.get("abr") or f.get("tbr") or 0, default=None)
    if preset.kind == "audio":
        if preset.key == "mp3" and duration:
            return int(192_000 / 8 * duration)
        return size(best_audio) if best_audio else None
    videos = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("height")]
    if preset.height:
        candidates = [f for f in videos if f["height"] <= preset.height] or videos
        target = max((f["height"] for f in candidates), default=None)
        candidates = [f for f in candidates if f["height"] == target]
        h264 = [f for f in candidates if str(f.get("vcodec", "")).startswith(("avc", "h264"))]
        candidates = h264 or candidates
    else:
        candidates = videos
    if not candidates:
        return None
    best_video = max(candidates, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
    vs = size(best_video)
    if vs is None:
        return None
    if best_video.get("acodec") in (None, "none") and best_audio:
        vs += size(best_audio) or 0
    return vs


def _build_presets(info: dict[str, Any], duration: float | None) -> tuple[list[dict[str, Any]], list[int], bool]:
    formats = info.get("formats") or []
    heights = sorted({f["height"] for f in formats if f.get("height") and f.get("vcodec") != "none"})
    audio_exts = {"mp3", "m4a", "aac", "opus", "ogg", "oga", "wav", "flac", "weba"}

    def is_audio_only(f: dict[str, Any]) -> bool:
        return f.get("vcodec") == "none" or f.get("video_ext") == "none" or f.get("ext") in audio_exts

    # vcodec is often unknown (None) for direct files; treat those as video.
    has_video = bool(heights) or any(not is_audio_only(f) for f in formats)
    if not formats:
        # Single direct file (or unknown) — offer generic options.
        has_video = info.get("vcodec") != "none"
    out: list[dict[str, Any]] = []
    max_h = max(heights) if heights else None
    for preset in PRESETS.values():
        if preset.kind == "video":
            if not has_video:
                continue
            if preset.height and (not heights or preset.height > max_h or preset.height not in heights):
                # Offer a fixed height only if the source actually has it.
                continue
        est = _estimate_size(formats, preset, duration) if formats else None
        label = preset.label
        if preset.key == "best" and max_h:
            label = f"En iyi ({max_h}p)"
        out.append({"key": preset.key, "kind": preset.kind, "label": label, "size": est})
    return out, heights, has_video


def extract_info(url: str, use_cache: bool = True) -> MediaInfo:
    url = urlguard.normalize(url)
    if use_cache:
        with _info_lock:
            cached = _info_cache.get(url)
            if cached and time.time() - cached[0] < _INFO_TTL:
                return cached[1]

    logger = _Logger()
    opts = _base_options(logger)
    opts["skip_download"] = True
    with _cookie_file(url, None) as cookie_path:
        if cookie_path:
            opts["cookiefile"] = cookie_path
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                info = ydl.sanitize_info(info)
        except (DownloadError, ExtractorError) as exc:
            msg = _clean_message(str(exc))
            raise DownloadFailed(classify_error(msg), msg) from None

    if not info:
        raise DownloadFailed("no_media", "")

    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise DownloadFailed("live", "")

    platform = info.get("extractor_key") or info.get("extractor") or urlguard.domain_of(url)
    media = MediaInfo(
        url=url,
        title=(info.get("title") or info.get("id") or "video")[:300],
        platform=str(platform),
        uploader=info.get("uploader") or info.get("channel") or info.get("uploader_id") or "",
        duration=info.get("duration"),
        thumbnail=_thumb(info),
    )

    if info.get("_type") == "playlist" or info.get("entries") is not None:
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise DownloadFailed("no_media", "")
        if len(entries) == 1:
            # Single-item "playlist" (common on X/Instagram) -> treat as a single video.
            single = entries[0]
            if single.get("formats"):
                media.title = (single.get("title") or media.title)[:300]
                media.duration = single.get("duration") or media.duration
                media.thumbnail = _thumb(single) or media.thumbnail
                info = single
            else:
                media.is_playlist = True
        else:
            media.is_playlist = True
        if media.is_playlist:
            media.entries = [
                {
                    "index": i,
                    "title": (e.get("title") or f"#{i}")[:200],
                    "duration": e.get("duration"),
                    "thumbnail": _thumb(e),
                }
                for i, e in enumerate(entries, start=1)
            ]
            media.thumbnail = media.thumbnail or (media.entries[0]["thumbnail"] if media.entries else "")
            # Use the first entry's formats to decide which presets make sense.
            sample = entries[0] if entries[0].get("formats") else {"formats": []}
            media.presets, media.heights, media.has_video = _build_presets(sample, None)
            if not sample.get("formats"):
                media.presets = [
                    {"key": p.key, "kind": p.kind, "label": p.label, "size": None}
                    for p in PRESETS.values()
                    if p.key in ("best", "720", "480", "mp3")
                ]
    if not media.is_playlist:
        media.presets, media.heights, media.has_video = _build_presets(info, media.duration)

    max_duration = settings.get("max_duration_min") * 60
    if media.duration and media.duration > max_duration:
        raise DownloadFailed("too_long", "")

    with _info_lock:
        now = time.time()
        for key in [k for k, (ts, _) in _info_cache.items() if now - ts > _INFO_TTL]:
            _info_cache.pop(key, None)
        _info_cache[url] = (now, media)
    return media


def cached_info(url: str) -> MediaInfo | None:
    with _info_lock:
        cached = _info_cache.get(url)
    return cached[1] if cached else None


# --------------------------------------------------------------------------- download

@dataclass
class DownloadedFile:
    path: Path
    title: str
    kind: str  # video | audio | other
    size: int
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    uploader: str = ""

    @property
    def name(self) -> str:
        return self.path.name


ProgressCallback = Callable[[dict[str, Any]], None]

_MEDIA_EXT_VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".3gp", ".ts"}
_MEDIA_EXT_AUDIO = {".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav", ".flac", ".weba"}
_SKIP_EXT = {".part", ".ytdl", ".jpg", ".jpeg", ".png", ".webp", ".json", ".txt", ".temp"}


def _kind_for(path: Path, preset: Preset) -> str:
    ext = path.suffix.lower()
    if ext in _MEDIA_EXT_AUDIO or preset.kind == "audio":
        return "audio"
    if ext in _MEDIA_EXT_VIDEO:
        return "video"
    return "other"


def download(
    url: str,
    preset_key: str,
    target_dir: Path,
    item: int | None = None,
    all_items: bool = False,
    progress: ProgressCallback | None = None,
) -> list[DownloadedFile]:
    url = urlguard.normalize(url)
    preset = PRESETS.get(preset_key)
    if not preset:
        raise DownloadFailed("bad_preset", preset_key)

    s = settings.all_settings()
    target_dir.mkdir(parents=True, exist_ok=True)
    logger = _Logger()
    opts = _base_options(logger)
    opts.update(preset_options(preset))
    opts.pop("extract_flat", None)
    opts.update(
        {
            "paths": {"home": str(target_dir), "temp": str(target_dir)},
            "outtmpl": {
                "default": "%(playlist_index)02d - %(title).90B.%(ext)s" if (item or all_items) else "%(title).100B.%(ext)s"
            },
            "max_filesize": s["max_filesize_mb"] * 1024 * 1024,
        }
    )
    if item:
        opts["playlist_items"] = str(item)
        opts["noplaylist"] = False
    elif all_items:
        opts["playlist_items"] = f"1:{s['max_playlist_items']}"
        opts["noplaylist"] = False

    rejected: list[str] = []
    max_duration = s["max_duration_min"] * 60

    def match_filter(info: dict[str, Any], *, incomplete: bool = False) -> str | None:
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            rejected.append("live")
            return "live"
        duration = info.get("duration")
        if duration and duration > max_duration:
            rejected.append("too_long")
            return "too_long"
        return None

    opts["match_filter"] = match_filter

    def hook(d: dict[str, Any]) -> None:
        if not progress:
            return
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            progress(
                {
                    "stage": "downloading",
                    "percent": (done / total * 100) if total else None,
                    "downloaded": done,
                    "total": total or None,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                    "item": (d.get("info_dict") or {}).get("playlist_index"),
                }
            )
        elif status == "finished":
            progress({"stage": "processing"})

    opts["progress_hooks"] = [hook]
    opts["postprocessor_hooks"] = [lambda d: progress and d.get("status") == "started" and progress({"stage": "processing"})]

    with _cookie_file(url, target_dir) as cookie_path:
        if cookie_path:
            opts["cookiefile"] = cookie_path
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                info = ydl.sanitize_info(info) if info else None
        except (DownloadError, ExtractorError) as exc:
            msg = _clean_message(str(exc))
            raise DownloadFailed(classify_error(msg), msg) from None

    files = _collect_files(info, target_dir, preset)
    if not files:
        if rejected:
            raise DownloadFailed(rejected[0], "")
        msg = "\n".join(logger.errors)
        if "max-filesize" in msg.lower() or any("larger than max" in e.lower() for e in logger.errors):
            raise DownloadFailed("too_large", "")
        raise DownloadFailed(classify_error(msg) if msg else "no_media", _clean_message(msg))
    return files


def _collect_files(info: dict[str, Any] | None, target_dir: Path, preset: Preset) -> list[DownloadedFile]:
    files: list[DownloadedFile] = []
    seen: set[Path] = set()

    def add(entry: dict[str, Any]) -> None:
        for rd in entry.get("requested_downloads") or []:
            fp = rd.get("filepath") or rd.get("_filename")
            if not fp:
                continue
            path = Path(fp)
            if not path.exists() or path in seen:
                continue
            seen.add(path)
            files.append(
                DownloadedFile(
                    path=path,
                    title=entry.get("title") or path.stem,
                    kind=_kind_for(path, preset),
                    size=path.stat().st_size,
                    duration=entry.get("duration"),
                    width=rd.get("width") or entry.get("width"),
                    height=rd.get("height") or entry.get("height"),
                    uploader=entry.get("uploader") or entry.get("channel") or "",
                )
            )

    if info:
        if info.get("entries") is not None:
            for entry in info.get("entries") or []:
                if entry:
                    add(entry)
        else:
            add(info)

    if not files:
        # Fallback: whatever media ended up in the directory.
        for path in sorted(target_dir.iterdir()):
            if path.is_file() and path.suffix.lower() not in _SKIP_EXT and not path.name.startswith("."):
                files.append(DownloadedFile(path=path, title=path.stem, kind=_kind_for(path, preset), size=path.stat().st_size))
    return files


def new_id() -> str:
    return secrets.token_urlsafe(12)


def ytdlp_version() -> str:
    return yt_dlp.version.__version__
