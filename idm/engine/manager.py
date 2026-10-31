"""Coordinates downloads, the queue and worker threads."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..constants import PRIORITY_HIGH, PRIORITY_LOW
from ..core.paths import ensure_download_dir
from ..core.settings import AppSettings
from ..core.url_utils import (
    category_for_filename,
    sanitize_filename,
    unique_filename,
    validate_url,
)
from ..models.download_item import (
    ACTIVE_STATUSES,
    DownloadItem,
    DownloadStatus,
)
from .segmented import discard_partial, inspect_partial
from .speed_limiter import SpeedLimiter
from .worker import DownloadWorker

logger = logging.getLogger(__name__)


class DownloadManager(QObject):
    download_added = Signal(object)
    download_updated = Signal(object)
    download_removed = Signal(str)
    stats_changed = Signal(int, float, int)
    download_completed = Signal(object)
    download_failed = Signal(object)
    queue_changed = Signal()

    def __init__(self, settings: AppSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._items: dict[str, DownloadItem] = {}
        self._order: list[str] = []
        self._workers: dict[str, DownloadWorker] = {}
        self._pending_cleanup: dict[str, tuple[Path, Path, bool]] = {}
        self._limiter = SpeedLimiter(settings.speed_limit_kbps * 1024)
        self.max_concurrent = settings.max_concurrent
        self.connections_per_download = max(
            1, min(int(getattr(settings, "connections_per_download", 1)), 16)
        )
        self._auto_retry = settings.auto_retry
        self._max_retries = settings.max_retries
        self._shutting_down = False
        self._last_stats: tuple[int, float, int] | None = None
        self._store = getattr(settings, "database", None)
        self._dirty: set[str] = set()
        self._queue_dirty = False
        self._segment_persist_at: dict[str, float] = {}

        if getattr(settings, "restore_session", True):
            self._restore_downloads()

        self.queue_changed.connect(self._on_queue_changed)

        self._persist_timer = QTimer(self)
        self._persist_timer.setInterval(1500)
        self._persist_timer.timeout.connect(self._flush_persistence)

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self._emit_stats)
        self._stats_timer.start()
        if self._store is not None:
            self._persist_timer.start()

    # ------------------------------------------------------------------ access
    def items(self) -> list[DownloadItem]:
        return [self._items[download_id] for download_id in self._order if download_id in self._items]

    def get(self, download_id: str) -> DownloadItem | None:
        return self._items.get(download_id)

    def queue_items(self) -> list[DownloadItem]:
        queued = [item for item in self._items.values() if item.status == DownloadStatus.QUEUED]
        return sorted(queued, key=lambda item: item.queue_seq)

    def find_active_by_url(self, url: str) -> DownloadItem | None:
        """Return an unfinished download with the same URL, if any."""
        normalized = (url or "").strip().casefold()
        if not normalized:
            return None
        for item in self._items.values():
            if item.status == DownloadStatus.COMPLETED:
                continue
            if item.url.casefold() == normalized:
                return item
        return None

    @property
    def active_count(self) -> int:
        return sum(1 for item in self._items.values() if item.is_active)

    @property
    def total_speed(self) -> float:
        return sum(item.speed for item in self._items.values() if item.is_active)

    # ------------------------------------------------------------------ persistence
    def _restore_downloads(self) -> None:
        if self._store is None:
            return
        try:
            records = self._store.load_downloads()
        except Exception:
            logger.exception("Could not restore downloads")
            return

        restored = 0
        for record in records:
            item = _item_from_record(record)
            if item is None:
                continue
            if item.status in ACTIVE_STATUSES or item.status in {
                DownloadStatus.QUEUED,
                DownloadStatus.PAUSING,
                DownloadStatus.STOPPING,
            }:
                # Never silently continue network activity after a restart.
                item.status = DownloadStatus.PAUSED
                item.speed = 0.0
                item.eta = None
            if item.status != DownloadStatus.COMPLETED:
                try:
                    downloaded, plan_total, plan = inspect_partial(item.part_path)
                    if plan is not None:
                        item.downloaded_bytes = downloaded
                        item.total_bytes = plan_total
                        item.connections = plan.connection_count
                        item.segments = plan.snapshot(interrupted=True)
                    elif item.part_path.exists():
                        part_size = item.part_path.stat().st_size
                        if item.total_bytes and part_size > item.total_bytes:
                            part_size = 0
                        item.downloaded_bytes = part_size
                    elif not item.path.exists() and item.downloaded_bytes:
                        item.downloaded_bytes = 0
                except OSError:
                    logger.debug("Could not inspect %s", item.part_path, exc_info=True)
            self._items[item.id] = item
            self._order.append(item.id)
            restored += 1
        if restored:
            logger.info("Restored %d downloads from the database", restored)

    def _record_for(self, item: DownloadItem) -> dict:
        return {
            "id": item.id,
            "url": item.url,
            "filename": item.filename,
            "folder": item.folder,
            "category": item.category,
            "priority": int(item.priority),
            "status": item.status.value,
            "total_bytes": item.total_bytes,
            "downloaded_bytes": int(item.downloaded_bytes),
            "speed": float(item.speed),
            "eta": float(item.eta) if item.eta is not None else None,
            "error": item.error,
            "content_type": item.content_type,
            "source_browser": item.source_browser,
            "referrer": item.referrer,
            "range_supported": (
                None if item.range_supported is None else int(bool(item.range_supported))
            ),
            "created_at": item.created_at.isoformat(timespec="seconds"),
            "completed_at": (
                item.completed_at.isoformat(timespec="seconds")
                if item.completed_at is not None
                else None
            ),
            "last_try": (
                item.last_try.isoformat(timespec="seconds")
                if item.last_try is not None
                else None
            ),
            "queue_seq": float(item.queue_seq),
            "connections": int(item.connections),
            "speed_limit_kbps": int(item.speed_limit_kbps),
            "etag": item.etag,
            "last_modified": item.last_modified,
            "retry_count": int(item.retry_count),
        }

    def _save_item(self, item: DownloadItem) -> None:
        if self._store is None:
            return
        try:
            self._store.save_download(self._record_for(item))
            self._dirty.discard(item.id)
        except Exception:
            logger.warning("Could not persist download %s", item.id, exc_info=True)

    def _log(self, item: DownloadItem, level: str, message: str) -> None:
        if self._store is None:
            return
        try:
            self._store.add_download_log(item.id, level, message)
        except Exception:
            logger.debug("Could not write the download log", exc_info=True)

    def _on_queue_changed(self) -> None:
        if self._store is not None:
            self._queue_dirty = True

    def _mark_dirty(self, item: DownloadItem) -> None:
        if self._store is not None:
            self._dirty.add(item.id)

    def _flush_persistence(self) -> None:
        if self._store is None:
            return
        if self._dirty:
            ids = list(self._dirty)
            self._dirty.clear()
            for download_id in ids:
                item = self._items.get(download_id)
                if item is not None:
                    self._save_item(item)
        if self._queue_dirty:
            self._queue_dirty = False
            self._flush_queue()

    def _flush_queue(self) -> None:
        if self._store is None:
            return
        entries = [
            {
                "download_id": item.id,
                "state": "waiting",
                "priority": int(item.priority),
            }
            for item in self.queue_items()
        ]
        try:
            self._store.replace_queue(entries)
        except Exception:
            logger.debug("Could not persist the download queue", exc_info=True)

    # ------------------------------------------------------------------ CRUD
    def add_download(
        self,
        url: str,
        filename: str,
        folder: str,
        category: str = "",
        priority: int = 1,
        start_immediately: bool = True,
        connections: int | None = None,
        speed_limit_kbps: int = 0,
        source_browser: str = "",
        referrer: str = "",
    ) -> DownloadItem:
        normalized_url = validate_url(url)
        try:
            folder_path = ensure_download_dir(folder)
        except OSError as exc:
            raise ValueError(f"Could not use the destination folder: {exc}") from exc

        connection_count = (
            self.connections_per_download if connections is None else int(connections)
        )
        connection_count = max(1, min(connection_count, 16))
        limit = max(0, int(speed_limit_kbps))

        safe_name = sanitize_filename(filename)
        folder_key = str(folder_path.resolve()).casefold()
        reserved = {
            item.filename
            for item in self._items.values()
            if item.status != DownloadStatus.COMPLETED
            and str(Path(item.folder).resolve()).casefold() == folder_key
        }
        unique_name = unique_filename(folder_path, safe_name, reserved=reserved)
        category = category or category_for_filename(unique_name)

        item = DownloadItem(
            url=normalized_url,
            filename=unique_name,
            folder=str(folder_path),
            category=category,
            priority=priority,
            status=DownloadStatus.QUEUED if start_immediately else DownloadStatus.PAUSED,
            queue_seq=self._next_queue_seq(priority) if start_immediately else 0.0,
            connections=connection_count,
            speed_limit_kbps=limit,
            source_browser=str(source_browser or "")[:32],
            referrer=str(referrer or "")[:8192],
        )
        self._items[item.id] = item
        self._order.append(item.id)
        self._save_item(item)
        logger.info("Queued download %s (%s)", item.id, item.filename)
        self.download_added.emit(item)
        self.queue_changed.emit()
        self._emit_stats(force=True)
        if start_immediately:
            self._pump()
        return item

    # ------------------------------------------------------------------ queue
    def _next_queue_seq(self, priority: int) -> float:
        sequences = [
            item.queue_seq
            for item in self._items.values()
            if item.status == DownloadStatus.QUEUED
        ]
        if not sequences:
            return 1.0
        if priority == PRIORITY_HIGH:
            return min(sequences) - 1.0
        if priority == PRIORITY_LOW:
            return max(sequences) + 2.0
        return max(sequences) + 1.0

    def _front_sequence(self) -> float:
        sequences = [item.queue_seq for item in self.queue_items()]
        return (min(sequences) - 1.0) if sequences else 1.0

    def _pump(self) -> None:
        if self._shutting_down:
            return
        while len(self._workers) < self.max_concurrent:
            queued = self.queue_items()
            if not queued:
                break
            item = queued[0]
            item.status = DownloadStatus.CONNECTING
            item.error = ""
            item.speed = 0.0
            item.eta = None
            item.last_try = datetime.now()
            downloaded, plan_total, plan = inspect_partial(item.part_path)
            if plan is not None:
                item.downloaded_bytes = downloaded
                item.total_bytes = plan_total
                item.connections = plan.connection_count
                item.segments = plan.snapshot(interrupted=True)
            elif item.part_path.exists():
                try:
                    part_size = item.part_path.stat().st_size
                    if item.total_bytes and part_size > item.total_bytes:
                        item.part_path.unlink(missing_ok=True)
                        part_size = 0
                    item.downloaded_bytes = part_size
                except OSError:
                    item.downloaded_bytes = 0
            self._save_item(item)
            self.download_updated.emit(item)
            self.queue_changed.emit()
            self._start_worker(item)

    def _start_worker(self, item: DownloadItem) -> None:
        try:
            worker = DownloadWorker(
                download_id=item.id,
                url=item.url,
                folder=item.folder,
                filename=item.filename,
                auto_retry=self._auto_retry,
                max_retries=self._max_retries,
                limiter=self._limiter,
                connections=item.connections,
                speed_limit_kbps=item.speed_limit_kbps,
                parent=self,
            )
        except Exception as exc:
            logger.exception("Could not start download %s", item.id)
            item.status = DownloadStatus.FAILED
            item.error = f"Could not start the download: {exc}"
            self.download_updated.emit(item)
            self._emit_stats(force=True)
            return

        self._workers[item.id] = worker
        worker.progress.connect(self._on_worker_progress)
        worker.state.connect(self._on_worker_state)
        worker.metadata.connect(self._on_worker_metadata)
        worker.segments.connect(self._on_worker_segments)
        worker.completed.connect(self._on_worker_completed)
        worker.failed.connect(self._on_worker_failed)
        worker.thread_finished.connect(self._on_worker_finished)
        worker.start()
        self._emit_stats(force=True)

    def move_in_queue(self, download_id: str, delta: int) -> None:
        queue = self.queue_items()
        ids = [item.id for item in queue]
        if download_id not in ids or delta == 0:
            return
        index = ids.index(download_id)
        other_index = index + (1 if delta > 0 else -1)
        if other_index < 0 or other_index >= len(queue):
            return
        current = queue[index]
        other = queue[other_index]
        current.queue_seq, other.queue_seq = other.queue_seq, current.queue_seq
        logger.debug("Queue order updated for %s", download_id)
        self.queue_changed.emit()

    # ------------------------------------------------------------------ actions
    def pause(self, download_ids: list[str]) -> int:
        changed = 0
        for download_id in download_ids:
            item = self._items.get(download_id)
            if item is None or not item.can_pause:
                continue
            if item.status == DownloadStatus.QUEUED:
                item.status = DownloadStatus.PAUSED
                item.speed = 0.0
                item.eta = None
                self._save_item(item)
                self.download_updated.emit(item)
                changed += 1
                continue
            worker = self._workers.get(download_id)
            if worker is not None:
                item.status = DownloadStatus.PAUSING
                item.error = ""
                self._save_item(item)
                self.download_updated.emit(item)
                worker.request_pause()
                changed += 1
        if changed:
            self.queue_changed.emit()
            self._emit_stats(force=True)
        return changed

    def resume(self, download_ids: list[str]) -> int:
        changed = 0
        for download_id in download_ids:
            item = self._items.get(download_id)
            if item is None or not item.can_resume:
                continue
            item.status = DownloadStatus.QUEUED
            item.error = ""
            item.speed = 0.0
            item.eta = None
            item.queue_seq = self._front_sequence()
            self._save_item(item)
            self.download_updated.emit(item)
            changed += 1
        if changed:
            self.queue_changed.emit()
            self._pump()
            self._emit_stats(force=True)
        return changed

    def stop(self, download_ids: list[str]) -> int:
        changed = 0
        for download_id in download_ids:
            item = self._items.get(download_id)
            if item is None:
                continue
            worker = self._workers.get(download_id)
            if worker is not None and item.is_active:
                item.status = DownloadStatus.STOPPING
                self._save_item(item)
                self.download_updated.emit(item)
                worker.request_stop()
                changed += 1
            elif item.status in {
                DownloadStatus.PAUSED,
                DownloadStatus.QUEUED,
                DownloadStatus.FAILED,
                DownloadStatus.STOPPED,
            }:
                item.status = DownloadStatus.STOPPED
                item.speed = 0.0
                item.eta = None
                self._save_item(item)
                self.download_updated.emit(item)
                changed += 1
        if changed:
            self.queue_changed.emit()
            self._emit_stats(force=True)
        return changed

    def remove(self, download_ids: list[str], delete_files: bool = False) -> int:
        removed = 0
        for download_id in set(download_ids):
            item = self._items.get(download_id)
            if item is None:
                continue
            worker = self._workers.get(download_id)
            if worker is not None:
                worker.request_cancel()
                self._pending_cleanup[item.id] = (item.part_path, item.path, delete_files)
            else:
                self._discard_files(item, delete_files)
            self._items.pop(download_id, None)
            if download_id in self._order:
                self._order.remove(download_id)
            self._dirty.discard(download_id)
            self._segment_persist_at.pop(download_id, None)
            if self._store is not None:
                try:
                    self._store.delete_download(download_id)
                except Exception:
                    logger.warning(
                        "Could not remove download %s from the database",
                        download_id,
                        exc_info=True,
                    )
            self.download_removed.emit(download_id)
            removed += 1
        if removed:
            self.queue_changed.emit()
            self._emit_stats(force=True)
        return removed

    def delete_completed(self) -> int:
        completed_ids = [
            item.id for item in self._items.values() if item.status == DownloadStatus.COMPLETED
        ]
        return self.remove(completed_ids, delete_files=False)

    def pause_all(self) -> int:
        return self.pause([item.id for item in self._items.values() if item.can_pause])

    def resume_all(self) -> int:
        ids = [
            item.id
            for item in self._items.values()
            if item.status in {DownloadStatus.PAUSED, DownloadStatus.STOPPED}
        ]
        changed = self.resume(ids)
        self._pump()
        return changed

    @staticmethod
    def _discard_files(item: DownloadItem, delete_file: bool) -> None:
        discard_partial(item.part_path)
        if delete_file and item.status == DownloadStatus.COMPLETED:
            try:
                if item.path.is_file():
                    item.path.unlink()
            except OSError as exc:
                logger.warning("Could not remove downloaded file %s: %s", item.path, exc)

    # ------------------------------------------------------------------ config
    def apply_settings(self) -> None:
        self.max_concurrent = self._settings.max_concurrent
        self.connections_per_download = max(
            1, min(int(getattr(self._settings, "connections_per_download", 1)), 16)
        )
        self._auto_retry = self._settings.auto_retry
        self._max_retries = self._settings.max_retries
        self._limiter.set_limit_kbps(self._settings.speed_limit_kbps)
        self._pump()

    def set_speed_limit(self, download_id: str, kbps: int) -> bool:
        item = self._items.get(download_id)
        if item is None:
            return False
        limit = max(0, int(kbps))
        item.speed_limit_kbps = limit
        worker = self._workers.get(download_id)
        if worker is not None:
            worker.set_speed_limit(limit)
        self._save_item(item)
        self.download_updated.emit(item)
        logger.info("Speed limit for %s set to %d KB/s", item.filename, limit)
        return True

    # ------------------------------------------------------------------ worker callbacks
    def _on_worker_progress(
        self, download_id: str, downloaded: int, total: int, speed: float, eta: float
    ) -> None:
        item = self._items.get(download_id)
        if item is None:
            return
        item.downloaded_bytes = downloaded
        if total > 0:
            item.total_bytes = total
        item.speed = float(speed)
        item.eta = float(eta) if eta > 0 else None
        self._mark_dirty(item)
        self.download_updated.emit(item)

    def _on_worker_metadata(
        self, download_id: str, total: int, content_type: str, range_supported: bool
    ) -> None:
        item = self._items.get(download_id)
        if item is None:
            return
        if total > 0:
            item.total_bytes = total
        item.content_type = content_type or item.content_type
        item.range_supported = bool(range_supported)
        self._mark_dirty(item)
        self.download_updated.emit(item)

    def _on_worker_segments(self, download_id: str, snapshot: object) -> None:
        item = self._items.get(download_id)
        if item is None:
            return
        if not isinstance(snapshot, list):
            return
        item.segments = [dict(entry) for entry in snapshot if isinstance(entry, dict)]
        if item.segments:
            item.connections = len(item.segments)
        self._persist_segments(item)
        self.download_updated.emit(item)

    def _persist_segments(self, item: DownloadItem, force: bool = False) -> None:
        if self._store is None:
            return
        now = time.monotonic()
        last = self._segment_persist_at.get(item.id, 0.0)
        if not force and now - last < 1.0:
            return
        self._segment_persist_at[item.id] = now
        try:
            self._store.replace_segments(item.id, item.segments)
        except Exception:
            logger.debug("Could not persist segments for %s", item.id, exc_info=True)

    def _on_worker_state(self, download_id: str, status: DownloadStatus, message: str) -> None:
        item = self._items.get(download_id)
        if item is None:
            return
        item.status = status
        if status == DownloadStatus.RETRYING:
            item.error = message
            item.last_try = datetime.now()
            item.retry_count += 1
            self._persist_segments(item, force=True)
        elif status in {DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED, DownloadStatus.STOPPED}:
            item.error = ""
        if status in {DownloadStatus.PAUSED, DownloadStatus.STOPPED}:
            item.speed = 0.0
            item.eta = None
            self._persist_segments(item, force=True)
            self._save_item(item)
        else:
            self._mark_dirty(item)
        self.download_updated.emit(item)
        self.queue_changed.emit()
        self._emit_stats(force=True)

    def _on_worker_completed(self, download_id: str, final_path: str) -> None:
        item = self._items.get(download_id)
        if item is None:
            return
        path = Path(final_path)
        try:
            size = path.stat().st_size
        except OSError:
            size = item.total_bytes or item.downloaded_bytes
        item.filename = path.name
        item.folder = str(path.parent)
        item.status = DownloadStatus.COMPLETED
        item.completed_at = datetime.now()
        item.downloaded_bytes = size
        item.total_bytes = size
        item.speed = 0.0
        item.eta = None
        item.error = ""
        item.segments = []
        self._segment_persist_at.pop(download_id, None)
        if self._store is not None:
            try:
                self._store.delete_segments(download_id)
            except Exception:
                logger.debug("Could not clear segments for %s", download_id, exc_info=True)
        logger.info("Download completed: %s", item.filename)
        self._log(item, "info", f"Completed: {path.name}")
        self._save_item(item)
        self.download_updated.emit(item)
        self.download_completed.emit(item)
        self.queue_changed.emit()
        self._emit_stats(force=True)

    def _on_worker_failed(self, download_id: str, message: str) -> None:
        item = self._items.get(download_id)
        if item is None:
            return
        item.status = DownloadStatus.FAILED
        item.error = message
        item.speed = 0.0
        item.eta = None
        logger.warning("Download failed: %s (%s)", item.filename, message)
        self._log(item, "error", message)
        self._save_item(item)
        self.download_updated.emit(item)
        self.download_failed.emit(item)
        self.queue_changed.emit()
        self._emit_stats(force=True)

    def _on_worker_finished(self, download_id: str) -> None:
        worker = self._workers.pop(download_id, None)
        if worker is not None:
            worker.wait(2000)
            worker.deleteLater()

        cleanup = self._pending_cleanup.pop(download_id, None)
        if cleanup is not None:
            part_path, final_path, delete_file = cleanup
            discard_partial(part_path)
            if delete_file:
                try:
                    final_path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("Could not remove file %s: %s", final_path, exc)
        else:
            item = self._items.get(download_id)
            if item is not None and item.status in ACTIVE_STATUSES | {
                DownloadStatus.PAUSING,
                DownloadStatus.STOPPING,
            }:
                item.status = DownloadStatus.FAILED
                item.error = "The download stopped unexpectedly."
                item.speed = 0.0
                item.eta = None
                self._log(item, "error", item.error)
                self.download_updated.emit(item)
                self.download_failed.emit(item)

        self._pump()
        self.queue_changed.emit()
        self._emit_stats(force=True)

    # ------------------------------------------------------------------ stats
    def _emit_stats(self, force: bool = False) -> None:
        active = sum(1 for item in self._items.values() if item.is_active)
        speed = sum(item.speed for item in self._items.values() if item.is_active)
        queued = sum(1 for item in self._items.values() if item.status == DownloadStatus.QUEUED)
        snapshot = (active, round(speed, 1), queued)
        if force or snapshot != self._last_stats:
            self._last_stats = snapshot
            self.stats_changed.emit(active, float(speed), queued)

    # ------------------------------------------------------------------ lifecycle
    def shutdown(self) -> None:
        self._shutting_down = True
        self._stats_timer.stop()
        self._persist_timer.stop()
        self._flush_persistence()
        for item in self._items.values():
            self._save_item(item)
        workers = list(self._workers.values())
        for worker in workers:
            worker.request_stop()
        deadline = time.monotonic() + 4.0
        for worker in workers:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if remaining_ms and not worker.wait(remaining_ms):
                logger.warning("Terminating unresponsive download thread %s", worker.download_id)
                worker.terminate()
                worker.wait(1000)
        self._workers.clear()
        for item in self._items.values():
            self._save_item(item)
        self._flush_queue()


def _item_from_record(record: dict) -> DownloadItem | None:
    url = str(record.get("url") or "").strip()
    filename = str(record.get("filename") or "").strip()
    folder = str(record.get("folder") or "").strip()
    if not url or not filename or not folder:
        return None
    try:
        status = DownloadStatus(str(record.get("status") or DownloadStatus.PAUSED.value))
    except ValueError:
        status = DownloadStatus.PAUSED

    range_value = record.get("range_supported")
    range_supported = None if range_value is None else bool(range_value)

    return DownloadItem(
        id=str(record.get("id") or uuid.uuid4().hex),
        url=url,
        filename=filename,
        folder=folder,
        category=str(record.get("category") or "Other"),
        priority=_optional_int(record.get("priority"), 1) or 1,
        status=status,
        total_bytes=_optional_int(record.get("total_bytes"), None),
        downloaded_bytes=_optional_int(record.get("downloaded_bytes"), 0) or 0,
        speed=float(record.get("speed") or 0.0),
        eta=_optional_float(record.get("eta")),
        error=str(record.get("error") or ""),
        content_type=str(record.get("content_type") or ""),
        source_browser=str(record.get("source_browser") or ""),
        referrer=str(record.get("referrer") or ""),
        range_supported=range_supported,
        queue_seq=float(record.get("queue_seq") or 0.0),
        connections=max(1, _optional_int(record.get("connections"), 4) or 4),
        speed_limit_kbps=max(0, _optional_int(record.get("speed_limit_kbps"), 0) or 0),
        etag=str(record.get("etag") or ""),
        last_modified=str(record.get("last_modified") or ""),
        retry_count=max(0, _optional_int(record.get("retry_count"), 0) or 0),
        created_at=_parse_datetime(record.get("created_at")) or datetime.now(),
        completed_at=_parse_datetime(record.get("completed_at")),
        last_try=_parse_datetime(record.get("last_try")),
    )


def _optional_int(value, default):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
