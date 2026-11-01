"""HTTP download worker with single- and multi-connection transfers.

The worker is independent from the UI.  It reports progress via Qt signals and
supports pause, resume (HTTP Range when available), stop and automatic retry.

Multi-connection downloads are only used when the server proves Range support,
the file is at least two segments long and the user selected more than one
connection.  Segments write into one ``.idm.part`` file at disjoint offsets and
a JSON journal records durable per-segment progress.  When Range support is
lost or the remote file changes, the partial data is discarded before a safe
restart; corrupted data is never finalized.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QThread, Signal

from ..constants import APP_USER_AGENT, CHUNK_SIZE
from ..core.media import normalize_sha256
from ..core.url_utils import (
    parse_content_range_start,
    parse_content_range_total,
    unique_filename,
    validate_url,
)
from ..models.download_item import DownloadStatus
from .segmented import (
    MAX_SEGMENTS,
    Segment,
    SegmentPlan,
    can_segment,
    discard_partial,
    load_plan,
    plan_segments,
    remove_journal,
    save_plan,
)
from .speed_limiter import SpeedLimiter

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 15
_READ_TIMEOUT = 20
_PROGRESS_INTERVAL = 0.25
_SPEED_WINDOW_SECONDS = 3.0
_JOURNAL_INTERVAL = 1.5
_SEGMENT_POLL = 0.05


class _RetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class _FatalError(Exception):
    pass


class _RangeLost(Exception):
    """The server stopped honouring Range requests mid-transfer."""


class _RemoteChanged(Exception):
    """The remote file no longer matches the journaled partial download."""


class DownloadWorker(QThread):
    # Byte counts must be 64-bit: Qt marshals "int" as a signed 32-bit value,
    # so files of 2 GiB or more arrive wrapped negative on the main thread.
    progress = Signal(str, "qint64", "qint64", float, float)
    state = Signal(str, object, str)
    metadata = Signal(str, "qint64", str, bool)
    segments = Signal(str, object)
    integrity = Signal(str, str, str)
    completed = Signal(str, str)
    failed = Signal(str, str)
    thread_finished = Signal(str)

    def __init__(
        self,
        download_id: str,
        url: str,
        folder: str,
        filename: str,
        auto_retry: bool,
        max_retries: int,
        limiter: SpeedLimiter,
        connections: int = 1,
        speed_limit_kbps: int = 0,
        expected_sha256: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.download_id = download_id
        self.url = validate_url(url)
        self.final_path = Path(folder) / filename
        self.part_path = Path(folder) / f"{filename}.idm.part"
        self.filename = filename
        self.folder = Path(folder)
        self.auto_retry = auto_retry
        self.max_retries = max(0, int(max_retries))
        self.connections = max(1, min(int(connections), MAX_SEGMENTS))
        self.expected_sha256 = normalize_sha256(expected_sha256)
        self._limiter = limiter
        self._local_limiter = SpeedLimiter(max(0, int(speed_limit_kbps)) * 1024)

        self._pause_requested = threading.Event()
        self._stop_requested = threading.Event()
        self._cancel_requested = threading.Event()
        self._speed_samples: deque[tuple[float, int]] = deque()
        self._segments_lock = threading.Lock()
        self._plan: SegmentPlan | None = None
        self._segments_disabled = False
        self._remote_restarts = 0
        self._session: requests.Session | None = None

    # ------------------------------------------------------------------ control
    def request_pause(self) -> None:
        self._pause_requested.set()

    def request_stop(self) -> None:
        self._stop_requested.set()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def set_speed_limit(self, kbps: int) -> None:
        self._local_limiter.set_limit_kbps(max(0, int(kbps)))

    @property
    def is_terminal_requested(self) -> bool:
        return (
            self._pause_requested.is_set()
            or self._stop_requested.is_set()
            or self._cancel_requested.is_set()
        )

    def _interrupted(self) -> bool:
        return (
            self._pause_requested.is_set()
            or self._stop_requested.is_set()
            or self._cancel_requested.is_set()
        )

    # ------------------------------------------------------------------ thread
    def run(self) -> None:
        attempts = 0
        try:
            while True:
                terminal = self._terminal_status_if_requested()
                if terminal is not None:
                    if terminal == DownloadStatus.STOPPED and self._cancel_requested.is_set():
                        return
                    self.state.emit(self.download_id, terminal, "")
                    return

                try:
                    outcome = self._transfer()
                except _RetryableError as exc:
                    if self._interrupted():
                        terminal = self._terminal_status_if_requested()
                        if terminal is not None:
                            self.state.emit(self.download_id, terminal, "")
                        return
                    attempts += 1
                    if not self.auto_retry or attempts > self.max_retries:
                        self.failed.emit(self.download_id, str(exc))
                        return
                    if exc.retry_after is not None:
                        delay = max(1.0, exc.retry_after)
                    else:
                        delay = float(min(2**attempts, 15))
                    self.state.emit(
                        self.download_id,
                        DownloadStatus.RETRYING,
                        f"{exc} Retrying in {delay:g} s ({attempts}/{self.max_retries}).",
                    )
                    if not self._interruptible_sleep(delay):
                        terminal = self._terminal_status_if_requested()
                        if terminal is not None:
                            self.state.emit(self.download_id, terminal, "")
                        return
                    continue
                except _FatalError as exc:
                    self.failed.emit(self.download_id, str(exc))
                    return
                except Exception as exc:  # pragma: no cover - defensive boundary
                    logger.exception(
                        "Unexpected failure in download worker %s", self.download_id
                    )
                    self.failed.emit(self.download_id, f"Unexpected error: {exc}")
                    return

                if outcome == DownloadStatus.COMPLETED:
                    return
                self.state.emit(self.download_id, outcome, "")
                return
        finally:
            self._close_session()
            self.thread_finished.emit(self.download_id)

    def _http_session(self) -> requests.Session:
        # Reuse TCP/TLS connections across retries and resume attempts.
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _close_session(self) -> None:
        session = self._session
        self._session = None
        if session is not None:
            try:
                session.close()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug("Could not close the HTTP session", exc_info=True)

    def _terminal_status_if_requested(self) -> DownloadStatus | None:
        if self._cancel_requested.is_set() or self._stop_requested.is_set():
            return DownloadStatus.STOPPED
        if self._pause_requested.is_set():
            return DownloadStatus.PAUSED
        return None

    def _interruptible_sleep(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._interrupted():
                return False
            time.sleep(min(0.15, max(0.0, deadline - time.monotonic())))
        return not self._interrupted()

    def _sleep_or_stop(self, seconds: float, stop_event: threading.Event) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if stop_event.is_set() or self._interrupted():
                return False
            time.sleep(min(0.15, max(0.0, deadline - time.monotonic())))
        return not (stop_event.is_set() or self._interrupted())

    # ------------------------------------------------------------------ transfer
    def _transfer(self) -> DownloadStatus:
        plan = load_plan(self.part_path)
        if plan is not None:
            try:
                valid_part = self.part_path.exists() and (
                    self.part_path.stat().st_size <= plan.total
                )
            except OSError:
                valid_part = False
            if not valid_part:
                logger.warning(
                    "Discarding invalid partial state for %s", self.filename
                )
                discard_partial(self.part_path)
                plan = None
            else:
                try:
                    return self._run_segmented(plan, fresh=False)
                except _RangeLost as exc:
                    logger.warning(
                        "Server stopped supporting Range for %s (%s); restarting safely.",
                        self.filename,
                        exc,
                    )
                    discard_partial(self.part_path)
                    self._plan = None
                    self._segments_disabled = True
                except _RemoteChanged as exc:
                    self._remote_restarts += 1
                    logger.warning(
                        "Remote file changed for %s (%s); restarting.",
                        self.filename,
                        exc,
                    )
                    discard_partial(self.part_path)
                    self._plan = None
                    if self._remote_restarts > 1:
                        raise _FatalError(
                            "The file keeps changing on the server. "
                            "Try downloading it again later."
                        ) from exc

        try:
            offset = self.part_path.stat().st_size if self.part_path.exists() else 0
        except OSError:
            offset = 0
        return self._open_transfer(offset)

    def _open_transfer(self, offset: int) -> DownloadStatus:
        headers = {
            "User-Agent": APP_USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        }
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"

        try:
            response = self._http_session().get(
                self.url,
                headers=headers,
                stream=True,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                allow_redirects=True,
            )
        except requests.exceptions.SSLError as exc:
            raise _FatalError(
                "TLS certificate verification failed. The server could not be trusted."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise _RetryableError("The connection timed out.") from exc
        except (requests.exceptions.InvalidURL, requests.exceptions.InvalidSchema) as exc:
            raise _FatalError("The download link is not valid.") from exc
        except requests.exceptions.RequestException as exc:
            raise _RetryableError(f"Network error: {_clean_error(exc)}") from exc

        restart_single = False
        with response:
            try:
                self._validate_redirect(response.url)
            except ValueError:
                raise _FatalError("The server redirected to an unsupported address.")

            status = response.status_code
            final_url = response.url or self.url
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
            accept_ranges = "bytes" in response.headers.get("Accept-Ranges", "").lower()
            etag = response.headers.get("ETag", "").strip()
            last_modified = response.headers.get("Last-Modified", "").strip()

            if status == 416 and offset > 0:
                total = parse_content_range_total(response.headers.get("Content-Range"))
                if total is not None and total == offset:
                    self.metadata.emit(self.download_id, total, content_type, True)
                    self.progress.emit(self.download_id, total, total, 0.0, 0.0)
                    return self._finalize()
                raise _FatalError("The server rejected the resume request for this file.")

            if status == 200:
                if offset > 0:
                    logger.info(
                        "Server ignored Range for %s; restarting from the beginning.",
                        self.filename,
                    )
                    offset = 0
                    try:
                        self.part_path.unlink(missing_ok=True)
                    except OSError as exc:
                        raise _FatalError(
                            f"Could not reset the partial file: {exc}"
                        ) from exc
                total = _content_length(response.headers)
                range_supported = accept_ranges
                self._ensure_disk_space(total)
                if (
                    offset == 0
                    and not self._segments_disabled
                    and range_supported
                    and can_segment(total, self.connections)
                ):
                    assert total is not None
                    plan = SegmentPlan(
                        total=total,
                        url=final_url,
                        etag=etag,
                        last_modified=last_modified,
                        segments=plan_segments(total, self.connections),
                    )
                    logger.info(
                        "Starting %d connections for %s (%s)",
                        plan.connection_count,
                        self.filename,
                        _format_bytes(total),
                    )
                    response.close()
                    try:
                        self.part_path.touch(exist_ok=True)
                        if not save_plan(self.part_path, plan):
                            raise _FatalError(
                                "Could not create the segment journal in the "
                                "destination folder."
                            )
                        return self._run_segmented(plan, fresh=True)
                    except (_RangeLost, _RemoteChanged) as exc:
                        logger.warning(
                            "Segmented start failed for %s (%s); using one connection.",
                            self.filename,
                            exc,
                        )
                        discard_partial(self.part_path)
                        self._plan = None
                        self._segments_disabled = True
                        restart_single = True
                if not restart_single:
                    return self._stream_single(
                        response, 0, total, content_type, range_supported
                    )
            elif status == 206:
                start = parse_content_range_start(response.headers.get("Content-Range"))
                if start is None or start != offset:
                    raise _FatalError("The server returned an unexpected byte range.")
                total = parse_content_range_total(response.headers.get("Content-Range"))
                if total is not None and total < offset:
                    raise _FatalError(
                        "The server reported a file smaller than the resumed data."
                    )
                if total is None:
                    length = _content_length(response.headers)
                    total = offset + length if length is not None else None
                return self._stream_single(response, offset, total, content_type, True)
            elif status in (408, 425, 429) or status >= 500:
                raise _RetryableError(
                    _http_error_message(status),
                    retry_after=_retry_after_seconds(response.headers.get("Retry-After")),
                )
            elif status >= 400:
                raise _FatalError(_http_error_message(status))
            else:
                raise _RetryableError(
                    f"The server returned an unexpected response (HTTP {status})."
                )

        if restart_single:
            return self._open_transfer(0)
        raise _RetryableError("The server did not return a usable response.")

    def _stream_single(
        self,
        response,
        offset: int,
        total: int | None,
        content_type: str,
        range_supported: bool,
    ) -> DownloadStatus:
        self._ensure_disk_space(total, offset)
        self.metadata.emit(self.download_id, total or 0, content_type, range_supported)
        self.state.emit(self.download_id, DownloadStatus.DOWNLOADING, "")
        self._speed_samples.clear()
        downloaded = offset
        self._emit_progress(downloaded, total, final=True)

        mode = "ab" if offset > 0 else "wb"
        try:
            with open(self.part_path, mode) as handle:
                last_emit = 0.0
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if self._interrupted():
                        self._flush(handle)
                        self._emit_progress(downloaded, total, final=True)
                        return (
                            self._terminal_status_if_requested()
                            or DownloadStatus.STOPPED
                        )
                    if not chunk:
                        continue
                    if not self._limiter.throttle(len(chunk), self._interrupted):
                        self._flush(handle)
                        self._emit_progress(downloaded, total, final=True)
                        return (
                            self._terminal_status_if_requested()
                            or DownloadStatus.STOPPED
                        )
                    if not self._local_limiter.throttle(len(chunk), self._interrupted):
                        self._flush(handle)
                        self._emit_progress(downloaded, total, final=True)
                        return (
                            self._terminal_status_if_requested()
                            or DownloadStatus.STOPPED
                        )
                    handle.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_emit >= _PROGRESS_INTERVAL:
                        self._emit_progress(downloaded, total)
                        last_emit = now
                self._flush(handle)
        except requests.exceptions.RequestException as exc:
            raise _RetryableError(
                f"The connection was interrupted: {_clean_error(exc)}"
            ) from exc
        except OSError as exc:
            raise _FatalError(f"Could not write the file to disk: {exc}") from exc

        if self._interrupted():
            self._emit_progress(downloaded, total, final=True)
            return self._terminal_status_if_requested() or DownloadStatus.STOPPED

        try:
            actual_size = self.part_path.stat().st_size
        except OSError:
            actual_size = 0
        if total is not None and actual_size != total:
            raise _RetryableError(
                "The connection closed before the file finished transferring."
            )
        if total is None:
            total = actual_size

        self._emit_progress(actual_size, total, final=True)
        self.metadata.emit(self.download_id, total, content_type, range_supported)
        return self._finalize()

    # ------------------------------------------------------------------ segments
    def _run_segmented(self, plan: SegmentPlan, fresh: bool) -> DownloadStatus:
        self._plan = plan
        if not fresh and not self.part_path.exists():
            raise _RangeLost("the partial file is missing")
        self._ensure_disk_space(plan.total, plan.downloaded)

        if plan.complete:
            try:
                size = self.part_path.stat().st_size
            except OSError:
                size = 0
            if size != plan.total:
                logger.warning(
                    "Discarding a completed journal whose part file size is wrong (%s != %s)",
                    size,
                    plan.total,
                )
                discard_partial(self.part_path)
                self._plan = None
                raise _RangeLost("the journal does not match the partial file")
            self.metadata.emit(self.download_id, plan.total, "", True)
            self._emit_progress(plan.downloaded, plan.total, final=True)
            return self._finalize()

        self.metadata.emit(self.download_id, plan.total, "", True)
        self.state.emit(self.download_id, DownloadStatus.DOWNLOADING, "")
        self._speed_samples.clear()
        self._emit_progress(plan.downloaded, plan.total, final=True)
        self._emit_segments(plan)

        stop_event = threading.Event()
        executor = ThreadPoolExecutor(
            max_workers=plan.connection_count,
            thread_name_prefix=f"idm-seg-{self.download_id[:8]}",
        )
        futures = [
            executor.submit(self._segment_worker, segment, plan, stop_event)
            for segment in plan.segments
        ]
        error: BaseException | None = None
        interrupted = False
        last_progress = 0.0
        last_journal = time.monotonic()

        try:
            while True:
                with self._segments_lock:
                    complete = plan.complete
                if complete:
                    break
                if self._interrupted():
                    interrupted = True
                    stop_event.set()
                    break
                for future in futures:
                    if future.done():
                        exception = future.exception()
                        if exception is not None:
                            error = exception
                            stop_event.set()
                            break
                if error is not None:
                    break
                if all(future.done() for future in futures):
                    stop_event.set()
                    break

                now = time.monotonic()
                if now - last_progress >= _PROGRESS_INTERVAL:
                    with self._segments_lock:
                        downloaded = plan.downloaded
                    self._emit_progress(downloaded, plan.total)
                    self._emit_segments(plan)
                    last_progress = now
                if now - last_journal >= _JOURNAL_INTERVAL:
                    save_plan(self.part_path, plan)
                    last_journal = now
                time.sleep(_SEGMENT_POLL)
        finally:
            stop_event.set()
            executor.shutdown(wait=True)

        save_plan(self.part_path, plan)
        with self._segments_lock:
            downloaded = plan.downloaded
            complete = plan.complete
        self._emit_segments(plan, interrupted=interrupted or error is not None)
        self._emit_progress(downloaded, plan.total, final=True)

        if error is not None:
            raise error
        if interrupted:
            return self._terminal_status_if_requested() or DownloadStatus.STOPPED
        if not complete:
            raise _RetryableError(
                "The segmented transfer stopped before all connections finished."
            )

        try:
            size = self.part_path.stat().st_size
        except OSError:
            size = 0
        if size != plan.total:
            raise _FatalError(
                "The downloaded file size does not match the expected size. "
                "The incomplete data was kept for recovery."
            )
        try:
            with open(self.part_path, "r+b") as handle:
                self._flush(handle)
        except OSError:
            logger.debug("Could not fsync the segmented file", exc_info=True)
        return self._finalize()

    def _segment_worker(
        self, segment: Segment, plan: SegmentPlan, stop_event: threading.Event
    ) -> None:
        session = requests.Session()
        try:
            self._segment_loop(segment, plan, stop_event, session)
        finally:
            try:
                session.close()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug("Could not close a segment session", exc_info=True)

    def _segment_loop(
        self,
        segment: Segment,
        plan: SegmentPlan,
        stop_event: threading.Event,
        session: requests.Session,
    ) -> None:
        attempts = 0
        while True:
            with self._segments_lock:
                finished = segment.finished
            if finished:
                return
            if stop_event.is_set() or self._interrupted():
                return
            try:
                self._segment_request(segment, plan, stop_event, session)
                attempts = 0
            except (_RangeLost, _RemoteChanged, _FatalError):
                raise
            except _RetryableError as exc:
                if stop_event.is_set() or self._interrupted():
                    return
                attempts += 1
                if not self.auto_retry or attempts > self.max_retries:
                    raise
                delay = (
                    max(1.0, exc.retry_after)
                    if exc.retry_after is not None
                    else float(min(2**attempts, 15))
                )
                self.state.emit(
                    self.download_id,
                    DownloadStatus.RETRYING,
                    f"{exc} Retrying segment {segment.index + 1} in {delay:g} s "
                    f"({attempts}/{self.max_retries}).",
                )
                logger.info(
                    "Retrying segment %s of %s in %.0f s: %s",
                    segment.index + 1,
                    self.filename,
                    delay,
                    exc,
                )
                if not self._sleep_or_stop(delay, stop_event):
                    return
                self.state.emit(self.download_id, DownloadStatus.DOWNLOADING, "")

    def _segment_request(
        self,
        segment: Segment,
        plan: SegmentPlan,
        stop_event: threading.Event,
        session: requests.Session,
    ) -> None:
        with self._segments_lock:
            offset = segment.next_offset
            remaining = segment.length - segment.done
        if remaining <= 0:
            return

        headers = {
            "User-Agent": APP_USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Range": f"bytes={offset}-{segment.end}",
        }
        try:
            response = session.get(
                self.url,
                headers=headers,
                stream=True,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                allow_redirects=True,
            )
        except requests.exceptions.SSLError as exc:
            raise _FatalError(
                "TLS certificate verification failed while downloading a segment."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise _RetryableError("A segment connection timed out.") from exc
        except requests.exceptions.RequestException as exc:
            raise _RetryableError(
                f"Network error on a segment: {_clean_error(exc)}"
            ) from exc

        wrote = 0
        with response:
            self._validate_redirect(response.url)
            status = response.status_code
            if status == 200:
                raise _RangeLost("the server ignored the segment Range request")
            if status == 416:
                with self._segments_lock:
                    if segment.finished:
                        return
                raise _RetryableError("The server rejected a segment resume request.")
            if status != 206:
                if status in (408, 425, 429) or status >= 500:
                    raise _RetryableError(
                        _http_error_message(status),
                        retry_after=_retry_after_seconds(
                            response.headers.get("Retry-After")
                        ),
                    )
                if status >= 400:
                    raise _FatalError(_http_error_message(status))
                raise _RetryableError(
                    f"A segment received an unexpected response (HTTP {status})."
                )

            start = parse_content_range_start(response.headers.get("Content-Range"))
            total = parse_content_range_total(response.headers.get("Content-Range"))
            if start is not None and start != offset:
                raise _RangeLost("the server returned an unexpected segment offset")
            if total is not None and total != plan.total:
                raise _RemoteChanged("the remote file size changed")
            current_etag = response.headers.get("ETag", "").strip()
            current_modified = response.headers.get("Last-Modified", "").strip()
            if plan.etag and current_etag and plan.etag != current_etag:
                raise _RemoteChanged("the remote ETag changed")
            if (
                plan.last_modified
                and current_modified
                and plan.last_modified != current_modified
            ):
                raise _RemoteChanged("the remote modification date changed")

            try:
                with open(self.part_path, "r+b") as handle:
                    handle.seek(offset)
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if stop_event.is_set() or self._interrupted():
                            self._flush(handle)
                            return
                        if not chunk:
                            continue
                        if len(chunk) > remaining:
                            chunk = chunk[:remaining]
                        if not self._limiter.throttle(len(chunk), self._interrupted):
                            self._flush(handle)
                            return
                        if not self._local_limiter.throttle(
                            len(chunk), self._interrupted
                        ):
                            self._flush(handle)
                            return
                        handle.write(chunk)
                        wrote += len(chunk)
                        remaining -= len(chunk)
                        with self._segments_lock:
                            segment.done = min(segment.length, segment.done + len(chunk))
                        if remaining <= 0:
                            break
                    self._flush(handle)
            except requests.exceptions.RequestException as exc:
                raise _RetryableError(
                    f"A segment connection was interrupted: {_clean_error(exc)}"
                ) from exc
            except OSError as exc:
                raise _FatalError(f"Could not write a segment to disk: {exc}") from exc

        with self._segments_lock:
            finished = segment.finished
        if not finished and wrote == 0:
            raise _RetryableError(
                "A segment connection closed before any data arrived."
            )

    def _emit_segments(self, plan: SegmentPlan, interrupted: bool = False) -> None:
        with self._segments_lock:
            snapshot = plan.snapshot(interrupted=interrupted)
        self.segments.emit(self.download_id, snapshot)

    # ------------------------------------------------------------------ helpers
    def _ensure_disk_space(self, total: int | None, already_have: int = 0) -> None:
        if not total or total <= 0:
            return
        required = max(0, int(total) - max(0, int(already_have)))
        if required <= 0:
            return
        try:
            free = shutil.disk_usage(self.folder).free
        except OSError:
            return
        if free < required + 1024 * 1024:
            raise _FatalError(
                "There is not enough free disk space for this download "
                f"({_format_bytes(required)} required, {_format_bytes(free)} free)."
            )

    @staticmethod
    def _flush(handle) -> None:
        try:
            handle.flush()
            os.fsync(handle.fileno())
        except OSError:
            pass

    def _validate_redirect(self, url: str) -> None:
        scheme = urlparse(url).scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError(scheme)

    def _finalize(self) -> DownloadStatus:
        if not self.part_path.exists():
            raise _FatalError("The downloaded data is missing.")

        if self.expected_sha256:
            digest = _file_sha256(self.part_path)
            if digest != self.expected_sha256:
                self.integrity.emit(self.download_id, "mismatch", digest)
                discard_partial(self.part_path)
                raise _FatalError(
                    "Integrity verification failed. The downloaded data did not "
                    "match the expected SHA-256 and was discarded."
                )
            self.integrity.emit(self.download_id, "verified", digest)

        remove_journal(self.part_path)
        final_path = self.final_path
        for _ in range(100):
            try:
                os.rename(self.part_path, final_path)
                break
            except FileExistsError:
                final_path = self.folder / unique_filename(self.folder, self.filename)
            except OSError as exc:
                raise _FatalError(f"Could not finalize the downloaded file: {exc}") from exc
        else:
            raise _FatalError("Could not choose a destination file name.")

        logger.info("Download completed: %s -> %s", self.download_id, final_path)
        self.completed.emit(self.download_id, str(final_path))
        return DownloadStatus.COMPLETED

    # ------------------------------------------------------------------ progress
    def _emit_progress(
        self, downloaded: int, total: int | None, final: bool = False
    ) -> None:
        now = time.monotonic()
        self._speed_samples.append((now, downloaded))
        while (
            len(self._speed_samples) > 2
            and now - self._speed_samples[0][0] > _SPEED_WINDOW_SECONDS
        ):
            self._speed_samples.popleft()

        speed = 0.0 if final else self._current_speed(now, downloaded)

        eta = 0.0
        if total and speed > 0 and downloaded < total:
            eta = (total - downloaded) / speed
        self.progress.emit(self.download_id, downloaded, int(total or 0), speed, eta)

    def _current_speed(self, now: float, downloaded: int) -> float:
        if len(self._speed_samples) < 2:
            return 0.0
        first_time, first_bytes = self._speed_samples[0]
        elapsed = now - first_time
        if elapsed <= 0:
            return 0.0
        return max(0.0, (downloaded - first_bytes) / elapsed)


def _content_length(headers) -> int | None:
    value = headers.get("Content-Length")
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _http_error_message(status: int) -> str:
    messages = {
        400: "The server rejected the request (HTTP 400).",
        401: "This file requires authentication (HTTP 401).",
        403: "Access was denied by the server (HTTP 403).",
        404: "The file was not found on the server (HTTP 404).",
        405: "The server does not allow this request (HTTP 405).",
        407: "A proxy requires authentication (HTTP 407).",
        408: "The server timed out the request (HTTP 408).",
        410: "The file is no longer available (HTTP 410).",
        429: "The server is rate limiting requests (HTTP 429).",
    }
    if status in messages:
        return messages[status]
    if status >= 500:
        return f"The server encountered an error (HTTP {status})."
    return f"The request failed (HTTP {status})."


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - datetime.now(UTC)).total_seconds())


def _clean_error(exc: Exception) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
