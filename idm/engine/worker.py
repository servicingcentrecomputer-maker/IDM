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

import ftplib
import logging
import mimetypes
import os
import shutil
import ssl
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlparse, urljoin

import requests
from PySide6.QtCore import QThread, Signal
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from ..constants import APP_USER_AGENT, CHUNK_SIZE
from ..core.media import normalize_sha256
from ..core.network import NetworkProfile
from ..core.url_utils import (
    parse_content_range_start,
    parse_content_range_total,
    scrub_secrets,
    unique_filename,
    validate_url,
)
from ..models.download_item import DownloadStatus
from .checksum import sha256_of
from .segmented import (
    MAX_SEGMENTS,
    MIN_SEGMENT_BYTES,
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
# A connection asks for at most this many bytes per request, which lets another
# connection take over the tail of a segment that is running slowly.
_GRANT_BYTES = 8 * 1024 * 1024
# Beyond this many hops a redirect chain is a misconfiguration, not a CDN.
_MAX_REDIRECT_HOPS = 8


class _RetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class _FatalError(Exception):
    pass


class _RangeLost(Exception):
    """The server stopped honouring Range requests mid-transfer."""


class _FtpAborted(Exception):
    """An FTP transfer was paused, stopped or cancelled by the user."""


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
        network: NetworkProfile | None = None,
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
        self.network = network or NetworkProfile()
        self._limiter = limiter
        self._local_limiter = SpeedLimiter(max(0, int(speed_limit_kbps)) * 1024)

        self._pause_requested = threading.Event()
        self._stop_requested = threading.Event()
        self._cancel_requested = threading.Event()
        self._speed_samples: deque[tuple[float, int]] = deque(maxlen=64)
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
                    self.failed.emit(
                        self.download_id,
                        f"Unexpected error: {scrub_secrets(str(exc))}",
                    )
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
            self._configure_session(self._session)
        return self._session

    def _configure_session(self, session: requests.Session) -> None:
        profile = self.network
        session.trust_env = profile.trust_env
        if profile.proxies is not None:
            session.proxies.update(profile.proxies)
        if profile.auth is not None:
            username, password, scheme = profile.auth
            if scheme == "digest":
                session.auth = HTTPDigestAuth(username, password)
            else:
                session.auth = HTTPBasicAuth(username, password)

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
        if urlparse(self.url).scheme.lower() in {"ftp", "ftps"}:
            return self._ftp_transfer()
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

    # ------------------------------------------------------------------ ftp
    def _ftp_transfer(self, allow_restart: bool = True) -> DownloadStatus:
        # A journal belongs to an HTTP transfer; an FTP URL must never reuse it.
        if load_plan(self.part_path) is not None:
            discard_partial(self.part_path)
        try:
            offset = self.part_path.stat().st_size if self.part_path.exists() else 0
        except OSError:
            offset = 0
        remote_path = unquote(urlparse(self.url).path or "")
        if not remote_path or remote_path.endswith("/"):
            raise _FatalError("The FTP link points to a folder, not a file.")

        client: ftplib.FTP | None = None
        try:
            client = self._open_ftp_client()
            total = self._ftp_size(client, remote_path)
            if total is not None and offset > 0:
                if offset == total:
                    self.metadata.emit(
                        self.download_id,
                        total,
                        self._ftp_content_type(),
                        True,
                    )
                    self._emit_progress(total, total, final=True)
                    return self._finalize()
                if offset > total:
                    logger.info(
                        "Partial FTP data for %s is larger than the remote file; "
                        "restarting.",
                        self.filename,
                    )
                    discard_partial(self.part_path)
                    offset = 0

            self.metadata.emit(
                self.download_id, total or 0, self._ftp_content_type(), True
            )
            self.state.emit(self.download_id, DownloadStatus.DOWNLOADING, "")
            self._speed_samples.clear()
            self._emit_progress(offset, total, final=True)

            downloaded = offset
            last_emit = time.monotonic()

            def consume(chunk: bytes) -> None:
                nonlocal downloaded, last_emit
                if self._interrupted():
                    raise _FtpAborted()
                if not self._limiter.throttle(len(chunk), self._interrupted):
                    raise _FtpAborted()
                if not self._local_limiter.throttle(len(chunk), self._interrupted):
                    raise _FtpAborted()
                handle.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_emit >= _PROGRESS_INTERVAL:
                    self._emit_progress(downloaded, total)
                    last_emit = now

            mode = "ab" if offset > 0 else "wb"
            try:
                with open(self.part_path, mode) as handle:
                    client.retrbinary(
                        f"RETR {remote_path}",
                        consume,
                        blocksize=CHUNK_SIZE,
                        rest=offset if offset > 0 else None,
                    )
                    self._flush(handle)
            except OSError as exc:
                raise _FatalError(f"Could not write the downloaded data: {exc}") from exc

            self._emit_progress(downloaded, total, final=True)
            if total is not None:
                try:
                    actual = self.part_path.stat().st_size
                except OSError:
                    actual = 0
                if actual != total:
                    raise _RetryableError(
                        "The FTP transfer ended before the whole file arrived."
                    )
            return self._finalize()
        except _FtpAborted:
            return (
                self._terminal_status_if_requested() or DownloadStatus.STOPPED
            )
        except ftplib.error_perm as exc:
            message = str(exc)
            if allow_restart and offset > 0 and message.startswith(
                ("500", "502", "504")
            ):
                logger.info(
                    "The FTP server rejected REST for %s; restarting from zero.",
                    self.filename,
                )
                discard_partial(self.part_path)
                return self._ftp_transfer(allow_restart=False)
            raise _FatalError(self._ftp_error(message)) from exc
        except ftplib.error_temp as exc:
            raise _RetryableError(f"FTP server error: {exc}") from exc
        except (ftplib.error_proto, EOFError) as exc:
            raise _RetryableError(
                f"The FTP connection was interrupted: {_clean_error(exc)}"
            ) from exc
        except ssl.SSLError as exc:
            raise _FatalError(
                "TLS verification failed for this FTPS server."
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise _RetryableError(
                f"FTP connection error: {_clean_error(exc)}"
            ) from exc
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:  # pragma: no cover - defensive cleanup
                    try:
                        client.close()
                    except Exception:
                        pass

    def _open_ftp_client(self) -> ftplib.FTP:
        parsed = urlparse(self.url)
        host = parsed.hostname
        if not host:
            raise _FatalError("The FTP link is missing a host name.")
        try:
            port = parsed.port or 21
        except ValueError as exc:
            raise _FatalError("The FTP link contains an invalid port.") from exc
        timeout = self.network.connect_timeout
        if parsed.scheme.lower() == "ftps":
            client: ftplib.FTP = ftplib.FTP_TLS(
                context=ssl.create_default_context(), timeout=timeout
            )
        else:
            client = ftplib.FTP(timeout=timeout)
        client.connect(host, port)
        credentials = self.network.auth
        if credentials is not None:
            client.login(credentials[0], credentials[1])
        else:
            client.login()
        if isinstance(client, ftplib.FTP_TLS):
            client.prot_p()
        client.set_pasv(True)
        client.voidcmd("TYPE I")
        return client

    @staticmethod
    def _ftp_size(client: ftplib.FTP, remote_path: str) -> int | None:
        try:
            size = client.size(remote_path)
        except ftplib.Error:
            return None
        if size is None:
            return None
        try:
            value = int(size)
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    def _ftp_content_type(self) -> str:
        guessed, _encoding = mimetypes.guess_type(self.filename)
        return guessed or "application/octet-stream"

    @staticmethod
    def _ftp_error(message: str) -> str:
        if message.startswith("530"):
            return "The FTP server rejected the user name or password."
        if message.startswith("550"):
            return "The file was not found or access was denied on the FTP server."
        if message.startswith("421"):
            return "The FTP server is busy. Try again later."
        return f"FTP error: {message}"

    def _get_stream(
        self,
        session: requests.Session,
        url: str,
        headers: dict[str, str],
        *,
        segment: bool = False,
    ):
        """Request a streamed response, following redirects under our own rules.

        Handing redirects to the HTTP library means thirty hops before it gives
        up and only the final address being checked, so a misconfigured server
        can hold a worker for minutes and the request can be bounced through
        hosts the user never chose.
        """
        timed_out = (
            "A segment connection timed out." if segment else "The connection timed out."
        )
        tls_failed = (
            "TLS certificate verification failed while downloading a segment."
            if segment
            else "TLS certificate verification failed. The server could not be trusted."
        )
        prefix = "Network error on a segment: " if segment else "Network error: "
        hops = 0
        while True:
            try:
                response = session.get(
                    url,
                    headers=headers,
                    stream=True,
                    timeout=self.network.timeout,
                    allow_redirects=False,
                )
            except requests.exceptions.SSLError as exc:
                raise _FatalError(tls_failed) from exc
            except requests.exceptions.Timeout as exc:
                raise _RetryableError(timed_out) from exc
            except (
                requests.exceptions.InvalidURL,
                requests.exceptions.InvalidSchema,
            ) as exc:
                raise _FatalError("The download link is not valid.") from exc
            except requests.exceptions.RequestException as exc:
                raise _RetryableError(f"{prefix}{_clean_error(exc)}") from exc

            location = _redirect_location(response)
            if location is None:
                return response
            hops += 1
            if hops > _MAX_REDIRECT_HOPS:
                response.close()
                raise _FatalError("The server redirected too many times.")
            next_url = urljoin(url, location)
            try:
                self._validate_redirect(next_url)
            except ValueError:
                response.close()
                raise _FatalError(
                    "The server redirected to an unsupported address."
                ) from None
            if urlparse(next_url).hostname != urlparse(url).hostname:
                # Site credentials belong to the host the user authenticated to.
                session.auth = None
            response.close()
            url = next_url

    def _open_transfer(self, offset: int) -> DownloadStatus:
        headers = {
            "User-Agent": APP_USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        }
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"

        response = self._get_stream(self._http_session(), self.url, headers)

        restart_single = False
        with response:
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
        self._configure_session(session)
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
            reassigned = False
            with self._segments_lock:
                if segment.finished:
                    taken = plan.replan_for(segment, MIN_SEGMENT_BYTES)
                    if taken is None:
                        return
                    segment = taken
                    reassigned = True
                else:
                    taken = None
            if reassigned:
                logger.info(
                    "Segment %s of %s picked up work from a slower connection",
                    taken.index + 1,
                    self.filename,
                )
                self._emit_segments(plan)
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
            # Only the next grant is claimed, so a connection that finishes
            # early can still be handed part of this segment.
            grant_end = min(segment.end, offset + _GRANT_BYTES - 1)
            segment.claimed_until = grant_end
            remaining = grant_end - offset + 1
        if remaining <= 0:
            return

        headers = {
            "User-Agent": APP_USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Range": f"bytes={offset}-{grant_end}",
        }
        response = self._get_stream(session, self.url, headers, segment=True)

        wrote = 0
        with response:
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
            digest = sha256_of(self.part_path)
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


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _redirect_location(response) -> str | None:
    """The next address in a redirect chain, or ``None`` for a final response."""
    if response.status_code not in _REDIRECT_STATUSES:
        return None
    return str(response.headers.get("Location") or "").strip() or None


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
    return scrub_secrets(text or exc.__class__.__name__)


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
