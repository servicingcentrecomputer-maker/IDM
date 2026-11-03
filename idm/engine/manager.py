"""Coordinates downloads, the queue and worker threads."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..constants import PRIORITY_HIGH, PRIORITY_LOW
from ..core.media import (
    format_for,
    media_kind_for,
    media_metadata,
    normalize_sha256,
    source_domain,
)
from ..core.categories import detect_category, safe_category
from ..core.network_monitor import NetworkMonitor
from ..core.paths import ensure_download_dir
from ..core.settings import AppSettings
from ..core.url_utils import (
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

_NETWORK_WAIT_MESSAGE = "Waiting for the network connection to come back."
_NETWORK_RETRY_INTERVAL_MS = 30_000
_NETWORK_FAILURE_HINTS = (
    "network error",
    "network is unreachable",
    "timed out",
    "timeout",
    "connection was interrupted",
    "connection closed",
    "connection reset",
    "connection aborted",
    "remote end closed",
    "temporarily unavailable",
    "name resolution",
    "getaddrinfo",
    "no route to host",
    "server disconnected",
)


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
        self._auto_resume_on_network = bool(
            getattr(settings, "auto_resume_on_network", True)
        )
        self._shutting_down = False
        self._last_stats: tuple[int, float, int] | None = None
        self._store = getattr(settings, "database", None)
        self._dirty: set[str] = set()
        self._queue_dirty = False
        self._segment_persist_at: dict[str, float] = {}
        self._network_waiting: set[str] = set()

        if getattr(settings, "restore_session", True):
            self._restore_downloads()

        self._network_monitor = NetworkMonitor(self)
        self._network_monitor.online_changed.connect(self._on_network_changed)
        self._network_retry_timer = QTimer(self)
        self._network_retry_timer.setSingleShot(True)
        self._network_retry_timer.setInterval(_NETWORK_RETRY_INTERVAL_MS)
        self._network_retry_timer.timeout.connect(self._retry_network_waiting)
        if self._network_waiting:
            QTimer.singleShot(1500, self._retry_network_waiting)

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
    def total_downloaded(self) -> int:
        return sum(max(0, item.downloaded_bytes) for item in self._items.values())

    @property
    def total_speed(self) -> float:
        return sum(item.speed for item in self._items.values() if item.is_active)

    @property
    def network_online(self) -> bool:
        return bool(self._network_monitor.online)

    @property
    def network_status_available(self) -> bool:
        return bool(self._network_monitor.available)

    def video_items(self) -> list[DownloadItem]:
        return [item for item in self.items() if item.is_video]

    @property
    def media_active_count(self) -> int:
        return sum(1 for item in self._items.values() if item.is_video and item.is_active)

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
            if item.queued_later and item.status == DownloadStatus.QUEUED:
                item.speed = 0.0
                item.eta = None
            elif item.status in ACTIVE_STATUSES or item.status in {
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
            if item.status == DownloadStatus.PAUSED and item.error == _NETWORK_WAIT_MESSAGE:
                self._network_waiting.add(item.id)
            restored += 1
        if restored:
            self._restore_media_metadata()
            logger.info("Restored %d downloads from the database", restored)

    def _restore_media_metadata(self) -> None:
        if self._store is None:
            return
        try:
            metadata = self._store.load_all_media_metadata()
        except Exception:
            logger.debug("Could not restore media metadata", exc_info=True)
            return
        for download_id, record in metadata.items():
            item = self._items.get(download_id)
            if item is None:
                continue
            if not item.media_kind:
                item.media_kind = str(record.get("media_kind") or "")
            if not item.page_url:
                item.page_url = str(record.get("page_url") or "")
            if not item.page_title:
                item.page_title = str(record.get("page_title") or "")
            if not item.source_domain:
                item.source_domain = str(record.get("source_domain") or "")
            if not item.file_format:
                item.file_format = format_for(item.content_type, item.filename)

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
            "media_kind": item.media_kind,
            "page_url": item.page_url,
            "page_title": item.page_title,
            "source_domain": item.source_domain,
            "file_format": item.file_format,
            "expected_sha256": item.expected_sha256,
            "checksum_status": item.checksum_status,
            "integrity_verified_at": item.integrity_verified_at,
            "description": item.description,
            "start_later": int(bool(item.queued_later)),
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

    def _save_media(self, item: DownloadItem, metadata: dict | None = None) -> None:
        if self._store is None or not item.media_kind:
            return
        record = metadata or {
            "media_kind": item.media_kind,
            "page_url": item.page_url,
            "page_title": item.page_title,
            "source_domain": item.source_domain,
            "file_format": item.file_format,
        }
        try:
            self._store.save_media_metadata(item.id, record)
        except Exception:
            logger.debug("Could not save media metadata", exc_info=True)

    def _event(self, download_id: str | None, event: str, byte_count: int = 0) -> None:
        if self._store is None:
            return
        try:
            self._store.add_download_event(download_id, event, byte_count)
        except Exception:
            logger.debug("Could not record download event", exc_info=True)

    def _notify(
        self,
        kind: str,
        title: str,
        message: str,
        download_id: str | None = None,
    ) -> None:
        if self._store is None:
            return
        try:
            self._store.add_notification(kind, title, message, download_id)
        except Exception:
            logger.debug("Could not record notification", exc_info=True)

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
                "state": "held" if item.queued_later else "waiting",
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
        page_url: str = "",
        page_title: str = "",
        quality_label: str = "",
        duration_seconds: int | None = None,
        detected_by: str = "",
        expected_sha256: str = "",
        content_type: str = "",
        media_kind_hint: str = "",
        description: str = "",
        download_later: bool = False,
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
        custom_categories = getattr(self._settings, "custom_categories", [])
        category = safe_category(
            category
            or detect_category(unique_name, content_type, custom_categories),
            custom_categories,
        )
        metadata = media_metadata(
            url=normalized_url,
            filename=unique_name,
            content_type=content_type,
            page_url=str(page_url or "")[:8192],
            page_title=str(page_title or "")[:1024],
            quality_label=str(quality_label or "")[:64],
            duration_seconds=duration_seconds,
            detected_by=str(detected_by or "")[:64],
            media_kind_hint=media_kind_hint,
        )

        held = bool(download_later)
        if download_later or start_immediately:
            item_status = DownloadStatus.QUEUED
            queue_seq = self._next_queue_seq(priority)
        else:
            item_status = DownloadStatus.PAUSED
            queue_seq = 0.0

        item = DownloadItem(
            url=normalized_url,
            filename=unique_name,
            folder=str(folder_path),
            category=category,
            priority=priority,
            status=item_status,
            queue_seq=queue_seq,
            connections=connection_count,
            speed_limit_kbps=limit,
            source_browser=str(source_browser or "")[:32],
            referrer=str(referrer or "")[:8192],
            content_type=str(content_type or "")[:255],
            media_kind=metadata["media_kind"],
            page_url=metadata["page_url"],
            page_title=metadata["page_title"],
            source_domain=metadata["source_domain"],
            file_format=metadata["file_format"],
            expected_sha256=normalize_sha256(expected_sha256),
            checksum_status="pending" if normalize_sha256(expected_sha256) else "not-requested",
            description=str(description or "").strip()[:2000],
            queued_later=held,
        )
        self._items[item.id] = item
        self._order.append(item.id)
        self._save_item(item)
        self._save_media(item, metadata)
        self._event(item.id, "added", 0)
        logger.info("Queued download %s (%s)", item.id, item.filename)
        self.download_added.emit(item)
        self.queue_changed.emit()
        self._emit_stats(force=True)
        if start_immediately and not held:
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
            queued = [item for item in self.queue_items() if not item.queued_later]
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
                expected_sha256=item.expected_sha256,
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
        worker.integrity.connect(self._on_worker_integrity)
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
                self._event(item.id, "paused", 0)
                self.download_updated.emit(item)
                changed += 1
                continue
            worker = self._workers.get(download_id)
            if worker is not None:
                item.status = DownloadStatus.PAUSING
                item.error = ""
                self._save_item(item)
                self._event(item.id, "paused", 0)
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
            item.queued_later = False
            item.queue_seq = self._front_sequence()
            self._network_waiting.discard(download_id)
            self._save_item(item)
            self._event(item.id, "resumed", 0)
            self.download_updated.emit(item)
            changed += 1
        if changed:
            self.queue_changed.emit()
            self._pump()
            self._emit_stats(force=True)
        return changed

    def start_queued(self, download_ids: list[str]) -> int:
        """Release “Download Later” entries into the active queue."""
        changed = 0
        for download_id in download_ids:
            item = self._items.get(download_id)
            if (
                item is None
                or item.status != DownloadStatus.QUEUED
                or not item.queued_later
            ):
                continue
            item.queued_later = False
            item.queue_seq = self._front_sequence()
            self._save_item(item)
            self._event(item.id, "queued", 0)
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
            self._network_waiting.discard(download_id)
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
            self._network_waiting.discard(download_id)
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
            self._event(download_id, "removed", 0)
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
        self._auto_resume_on_network = bool(
            getattr(self._settings, "auto_resume_on_network", True)
        )
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
        discovered = media_kind_for(item.content_type, item.filename)
        if discovered and not item.media_kind:
            item.media_kind = discovered
            item.file_format = format_for(item.content_type, item.filename)
            self._save_media(item)
        elif not item.file_format:
            item.file_format = format_for(item.content_type, item.filename)
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

    def _on_worker_integrity(
        self, download_id: str, status: str, digest: str = ""
    ) -> None:
        item = self._items.get(download_id)
        if item is None:
            return
        if status in {"verified", "mismatch"}:
            item.checksum_status = status
            item.integrity_verified_at = datetime.now().isoformat(timespec="seconds")
            if status == "verified":
                item.error = ""
            self._mark_dirty(item)
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
        self._network_waiting.discard(download_id)
        if self._store is not None:
            try:
                self._store.delete_segments(download_id)
            except Exception:
                logger.debug("Could not clear segments for %s", download_id, exc_info=True)
        logger.info("Download completed: %s", item.filename)
        self._log(item, "info", f"Completed: {path.name}")
        self._save_item(item)
        self._event(item.id, "completed", size)
        self._notify(
            "success",
            "Download complete",
            f"{item.filename} ({_format_bytes(size)})",
            item.id,
        )
        self.download_updated.emit(item)
        self.download_completed.emit(item)
        self.queue_changed.emit()
        self._emit_stats(force=True)

    def _on_worker_failed(self, download_id: str, message: str) -> None:
        item = self._items.get(download_id)
        if item is None:
            return
        if self._should_wait_for_network(message):
            self._wait_for_network(item, message)
            return
        item.status = DownloadStatus.FAILED
        item.error = message
        item.speed = 0.0
        item.eta = None
        logger.warning("Download failed: %s (%s)", item.filename, message)
        self._log(item, "error", message)
        self._save_item(item)
        self._event(item.id, "failed", 0)
        self._notify(
            "error",
            "Download failed",
            f"{item.filename}: {message}",
            item.id,
        )
        self.download_updated.emit(item)
        self.download_failed.emit(item)
        self.queue_changed.emit()
        self._emit_stats(force=True)

    # ------------------------------------------------------------------ network
    def _should_wait_for_network(self, message: str) -> bool:
        return (
            self._auto_resume_on_network
            and self._auto_retry
            and not self._shutting_down
            and _looks_like_network_failure(message)
        )

    def _wait_for_network(self, item: DownloadItem, message: str) -> None:
        newly_waiting = item.id not in self._network_waiting
        self._network_waiting.add(item.id)
        item.status = DownloadStatus.PAUSED
        item.error = _NETWORK_WAIT_MESSAGE
        item.speed = 0.0
        item.eta = None
        self._log(item, "warning", f"{message} {_NETWORK_WAIT_MESSAGE}")
        self._event(item.id, "network-wait", 0)
        if newly_waiting:
            self._notify(
                "warning",
                "Connection lost",
                f"{item.filename} is paused until the network returns.",
                item.id,
            )
        self._save_item(item)
        logger.info(
            "Download %s paused because the network is unavailable: %s",
            item.id,
            message,
        )
        self.download_updated.emit(item)
        self.queue_changed.emit()
        self._emit_stats(force=True)
        self._schedule_network_retry()

    def _schedule_network_retry(self) -> None:
        if not self._network_waiting or self._shutting_down:
            return
        if not self._network_monitor.available:
            self._network_retry_timer.start()

    def _on_network_changed(self, online: bool) -> None:
        if online:
            self._resume_network_waiting()

    def _retry_network_waiting(self) -> None:
        if self._shutting_down or not self._network_waiting:
            return
        if not self._network_monitor.online:
            self._network_retry_timer.start()
            return
        self._resume_network_waiting()

    def _resume_network_waiting(self) -> None:
        if self._shutting_down or not self._network_waiting:
            return
        pending = [
            download_id
            for download_id in self._network_waiting
            if download_id in self._items
        ]
        self._network_waiting.clear()
        if not pending:
            return
        resumed = self.resume(pending)
        if resumed:
            logger.info("Resumed %d downloads after the network returned", resumed)
            self._notify(
                "info",
                "Connection restored",
                f"{resumed} download(s) resumed automatically.",
            )
            self._event(None, "network-restored", 0)
        else:
            self._schedule_network_retry()

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
        self._network_retry_timer.stop()
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


def _looks_like_network_failure(message: str) -> bool:
    lowered = (message or "").casefold()
    return any(hint in lowered for hint in _NETWORK_FAILURE_HINTS)


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
        media_kind=str(record.get("media_kind") or ""),
        page_url=str(record.get("page_url") or ""),
        page_title=str(record.get("page_title") or ""),
        source_domain=str(record.get("source_domain") or ""),
        file_format=str(record.get("file_format") or ""),
        expected_sha256=str(record.get("expected_sha256") or ""),
        checksum_status=str(record.get("checksum_status") or "not-requested"),
        integrity_verified_at=str(record.get("integrity_verified_at") or ""),
        description=str(record.get("description") or ""),
        queued_later=bool(record.get("start_later")),
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


def _format_bytes(size: int) -> str:
    value = float(max(0, int(size)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
