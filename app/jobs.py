"""Download queue shared by the website and the Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import config, db, downloader, settings

log = logging.getLogger("save.jobs")

QUEUED, RUNNING, PROCESSING, DONE, ERROR = "queued", "downloading", "processing", "done", "error"


@dataclass
class Job:
    id: str
    url: str
    preset: str
    source: str  # web | telegram
    requester: str
    item: int | None = None
    all_items: bool = False
    status: str = QUEUED
    percent: float | None = None
    downloaded: int | None = None
    total: int | None = None
    speed: float | None = None
    eta: int | None = None
    current_item: int | None = None
    title: str = ""
    platform: str = ""
    files: list[downloader.DownloadedFile] = field(default_factory=list)
    error_code: str = ""
    error_detail: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    done_event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def dir(self) -> Path:
        return config.DOWNLOAD_DIR / self.id

    @property
    def finished(self) -> bool:
        return self.status in (DONE, ERROR)

    def public(self) -> dict[str, Any]:
        position = None
        if self.status == QUEUED:
            position = manager.queue_position(self.id)
        return {
            "id": self.id,
            "status": self.status,
            "percent": round(self.percent, 1) if self.percent is not None else None,
            "downloaded": self.downloaded,
            "total": self.total,
            "speed": self.speed,
            "eta": self.eta,
            "position": position,
            "title": self.title,
            "error": self.error_code or None,
            "files": [
                {"index": i, "name": f.name, "size": f.size, "kind": f.kind, "url": f"/d/{self.id}/{i}"}
                for i, f in enumerate(self.files)
            ],
            "expires_at": (self.finished_at or 0) + settings.get("file_ttl_min") * 60 if self.finished_at else None,
        }


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[str] | None = None
        self._workers: list[asyncio.Task] = []
        self._target = 1
        self._cleanup_task: asyncio.Task | None = None
        self._order: list[str] = []
        self._dedupe: dict[tuple[str, str, int | None, bool], str] = {}

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._queue = asyncio.Queue()
        self.resize(settings.get("max_concurrent"))
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        # Mark downloads interrupted by a restart.
        db.execute(
            "UPDATE downloads SET status=?, error=? WHERE status NOT IN (?, ?)",
            (ERROR, "interrupted", DONE, ERROR),
        )

    async def stop(self) -> None:
        for task in [*self._workers, *([self._cleanup_task] if self._cleanup_task else [])]:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    def resize(self, count: int) -> None:
        """Change concurrency. Surplus workers exit after their current job."""
        self._target = max(1, int(count))
        self._workers = [w for w in self._workers if not w.done()]
        while len(self._workers) < self._target:
            self._workers.append(asyncio.create_task(self._worker()))

    # ------------------------------------------------------------------ api
    def submit(
        self,
        url: str,
        preset: str,
        source: str,
        requester: str,
        item: int | None = None,
        all_items: bool = False,
        title: str = "",
        platform: str = "",
    ) -> Job:
        assert self._queue is not None, "JobManager not started"
        key = (url, preset, item, all_items)
        existing_id = self._dedupe.get(key)
        if existing_id and source == "web":
            existing = self.jobs.get(existing_id)
            if existing and existing.status != ERROR and all(f.path.exists() for f in existing.files):
                return existing
        job = Job(
            id=downloader.new_id(),
            url=url,
            preset=preset,
            source=source,
            requester=requester,
            item=item,
            all_items=all_items,
            title=title,
            platform=platform,
        )
        self.jobs[job.id] = job
        self._order.append(job.id)
        self._dedupe[key] = job.id
        db.execute(
            "INSERT INTO downloads(id, url, preset, source, requester, title, platform, status, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (job.id, url, preset, source, requester, title, platform, QUEUED, job.created_at),
        )
        self._queue.put_nowait(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def queue_position(self, job_id: str) -> int | None:
        pos = 0
        for jid in self._order:
            job = self.jobs.get(jid)
            if not job or job.status != QUEUED:
                continue
            pos += 1
            if jid == job_id:
                return pos
        return None

    def active(self) -> list[Job]:
        return [j for j in self.jobs.values() if not j.finished]

    async def wait(self, job: Job, on_update: Callable[[Job], Awaitable[None]] | None = None, interval: float = 3.0) -> Job:
        while not job.finished:
            try:
                await asyncio.wait_for(job.done_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            if on_update and not job.finished:
                try:
                    await on_update(job)
                except Exception:  # noqa: BLE001 - progress updates are best effort
                    log.debug("progress update failed", exc_info=True)
        return job

    # ------------------------------------------------------------------ internals
    async def _worker(self) -> None:
        assert self._queue is not None
        me = asyncio.current_task()
        while True:
            alive = [w for w in self._workers if not w.done()]
            if len(alive) > self._target and me in self._workers:
                self._workers.remove(me)
                return
            job_id = await self._queue.get()
            job = self.jobs.get(job_id)
            try:
                if job and job.status == QUEUED:
                    await self._run(job)
            except asyncio.CancelledError:
                if job and not job.finished:
                    self._fail(job, "interrupted", "")
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("job %s crashed", job_id)
                if job:
                    self._fail(job, "generic", str(exc))
            finally:
                self._queue.task_done()

    async def _run(self, job: Job) -> None:
        job.status = RUNNING
        db.execute("UPDATE downloads SET status=? WHERE id=?", (RUNNING, job.id))

        def progress(d: dict[str, Any]) -> None:
            if d["stage"] == "processing":
                job.status = PROCESSING
                job.percent = 100.0
                return
            job.status = RUNNING
            job.percent = d.get("percent")
            job.downloaded = d.get("downloaded")
            job.total = d.get("total")
            job.speed = d.get("speed")
            job.eta = d.get("eta")
            job.current_item = d.get("item")

        try:
            files = await asyncio.to_thread(
                downloader.download, job.url, job.preset, job.dir, job.item, job.all_items, progress
            )
        except downloader.DownloadFailed as exc:
            self._fail(job, exc.code, exc.detail)
            return

        job.files = files
        if not job.title and files:
            job.title = files[0].title
        job.status = DONE
        job.percent = 100.0
        job.finished_at = time.time()
        db.execute(
            "UPDATE downloads SET status=?, title=?, filesize=?, finished_at=? WHERE id=?",
            (DONE, job.title, sum(f.size for f in files), job.finished_at, job.id),
        )
        job.done_event.set()

    def _fail(self, job: Job, code: str, detail: str) -> None:
        job.status = ERROR
        job.error_code = code
        job.error_detail = detail
        job.finished_at = time.time()
        db.execute(
            "UPDATE downloads SET status=?, error=?, finished_at=? WHERE id=?",
            (ERROR, f"{code}: {detail}"[:1000], job.finished_at, job.id),
        )
        shutil.rmtree(job.dir, ignore_errors=True)
        job.done_event.set()

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                self.cleanup()
            except Exception:  # noqa: BLE001
                log.exception("cleanup failed")
            await asyncio.sleep(60)

    def cleanup(self) -> None:
        ttl = settings.get("file_ttl_min") * 60
        now = time.time()
        for job_id in list(self.jobs):
            job = self.jobs[job_id]
            if job.finished and job.finished_at and now - job.finished_at > ttl:
                shutil.rmtree(job.dir, ignore_errors=True)
                self.jobs.pop(job_id, None)
        live = set(self.jobs)
        self._order = [j for j in self._order if j in live]
        self._dedupe = {k: v for k, v in self._dedupe.items() if v in live}
        # Remove orphan directories (e.g. left over from a restart).
        if config.DOWNLOAD_DIR.exists():
            for path in config.DOWNLOAD_DIR.iterdir():
                if path.is_dir() and path.name not in live and now - path.stat().st_mtime > ttl:
                    shutil.rmtree(path, ignore_errors=True)


manager = JobManager()
