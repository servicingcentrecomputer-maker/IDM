"""Resumable, hash-verified download of the release installer."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests

from ..version import CURRENT_VERSION
from .config import UpdateConfig, host_is_trusted, is_ip_literal
from .errors import (
    DownloadCancelled,
    DownloadError,
    HashMismatchError,
    NetworkError,
)
from .manifest_validator import UpdateManifest
from .update_checker import _validate_response_chain

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 128 * 1024
_CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$")
_SAFE_FILENAME_RE = re.compile(r"[^0-9A-Za-z._-]+")
_USER_AGENT = f"IDM/{CURRENT_VERSION} Updater"
_REQUEST_HEADERS = {
    "Accept": "application/octet-stream",
    "Accept-Encoding": "identity",
    "User-Agent": _USER_AGENT,
}

ProgressCallback = Callable[[int, int | None], None]


@dataclass(frozen=True)
class DownloadedInstaller:
    path: Path
    sha256: str
    size: int
    manifest: UpdateManifest


class InstallerDownloader:
    """Stream the installer to disk and verify its hash before returning it."""

    def __init__(
        self,
        config: UpdateConfig,
        cancel_event: threading.Event | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._cancel = cancel_event or threading.Event()
        self._session = session

    def cancel(self) -> None:
        self._cancel.set()

    def download(
        self,
        manifest: UpdateManifest,
        directory: Path,
        progress: ProgressCallback | None = None,
        attempts: int = 2,
    ) -> DownloadedInstaller:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        _validate_download_target(manifest.download_url, self._config)

        filename = f"IDM_Setup_{_safe_component(manifest.latest_version)}.exe"
        final_path = directory / filename
        part_path = directory / f"{filename}.part"

        own_session = self._session is None
        session = self._session if self._session is not None else requests.Session()
        if own_session:
            session.headers.update(_REQUEST_HEADERS)

        try:
            self._download_with_retries(
                session, manifest, part_path, progress, max(1, attempts)
            )
        finally:
            if own_session:
                session.close()

        if self._cancel.is_set():
            _remove(part_path)
            _remove(final_path)
            raise DownloadCancelled("The update download was cancelled.")

        try:
            size = part_path.stat().st_size
        except OSError as exc:
            raise DownloadError("The downloaded installer is missing.") from exc
        if size == 0:
            _remove(part_path)
            raise DownloadError("The update server returned an empty installer.")

        from .package_verifier import compute_sha256

        digest = compute_sha256(part_path)
        if digest.lower() != manifest.sha256.lower():
            _remove(part_path)
            _remove(final_path)
            logger.warning(
                "Installer SHA-256 mismatch for version %s", manifest.latest_version
            )
            raise HashMismatchError(
                "The downloaded installer failed SHA-256 verification. It was "
                "deleted and will not be installed."
            )

        try:
            os.replace(part_path, final_path)
        except OSError as exc:
            _remove(part_path)
            raise DownloadError(
                "The downloaded installer could not be finalized on disk."
            ) from exc

        logger.info(
            "Installer %s downloaded and SHA-256 verified (%d bytes)",
            final_path.name,
            size,
        )
        return DownloadedInstaller(
            path=final_path, sha256=digest, size=size, manifest=manifest
        )

    # ------------------------------------------------------------------ internals
    def _download_with_retries(
        self,
        session: requests.Session,
        manifest: UpdateManifest,
        part_path: Path,
        progress: ProgressCallback | None,
        attempts: int,
    ) -> None:
        last_error = "The update download failed."
        completed = False
        for attempt in range(1, attempts + 1):
            if self._cancel.is_set():
                raise DownloadCancelled("The update download was cancelled.")
            try:
                completed = self._download_once(
                    session, manifest, part_path, progress
                )
                if completed:
                    return
            except requests.RequestException as exc:
                last_error = _describe_request_error(exc)
                logger.warning(
                    "Installer download attempt %d/%d failed: %s",
                    attempt,
                    attempts,
                    last_error,
                )
            except DownloadError as exc:
                last_error = str(exc)
                logger.warning(
                    "Installer download attempt %d/%d failed: %s",
                    attempt,
                    attempts,
                    last_error,
                )
            if attempt < attempts:
                wait = 0.5 * attempt
                deadline = time.monotonic() + wait
                while time.monotonic() < deadline:
                    if self._cancel.is_set():
                        raise DownloadCancelled(
                            "The update download was cancelled."
                        )
                    time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        if not completed:
            raise DownloadError(last_error)

    def _download_once(
        self,
        session: requests.Session,
        manifest: UpdateManifest,
        part_path: Path,
        progress: ProgressCallback | None,
    ) -> bool:
        offset = part_path.stat().st_size if part_path.exists() else 0
        headers = dict(_REQUEST_HEADERS)
        if offset:
            headers["Range"] = f"bytes={offset}-"

        try:
            response = session.get(
                manifest.download_url,
                headers=headers,
                timeout=self._config.timeout,
                stream=True,
                allow_redirects=True,
            )
        except requests.RequestException:
            raise
        except Exception as exc:
            raise DownloadError("The installer request could not be created.") from exc

        try:
            try:
                _validate_response_chain(response, self._config)
            except NetworkError as exc:
                raise DownloadError(str(exc)) from exc

            status = int(getattr(response, "status_code", 0))
            if status == 416:
                _remove(part_path)
                return False
            if status not in (200, 206):
                raise DownloadError(
                    f"The update server returned HTTP {status} for the installer."
                )

            total: int | None
            if status == 206:
                if offset == 0:
                    raise DownloadError(
                        "The update server returned a partial installer for a "
                        "full request."
                    )
                content_range = _parse_content_range(response)
                if content_range is None or content_range[0] != offset:
                    _remove(part_path)
                    return False
                total = content_range[2]
            else:
                if offset:
                    logger.info(
                        "The update server ignored the resume request; "
                        "restarting the installer download."
                    )
                offset = 0
                total = _content_length(response)

            if total is not None:
                if total > self._config.max_installer_bytes:
                    raise DownloadError(
                        "The installer is larger than the configured size limit."
                    )
                if total < offset:
                    _remove(part_path)
                    return False

            mode = "ab" if status == 206 and offset else "wb"
            written = 0
            try:
                with open(part_path, mode) as handle:
                    for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                        if self._cancel.is_set():
                            raise DownloadCancelled(
                                "The update download was cancelled."
                            )
                        if not chunk:
                            continue
                        handle.write(chunk)
                        written += len(chunk)
                        downloaded = offset + written
                        if downloaded > self._config.max_installer_bytes:
                            raise DownloadError(
                                "The installer exceeded the configured size limit."
                            )
                        if progress is not None:
                            progress(downloaded, total)
                    handle.flush()
                    os.fsync(handle.fileno())
            except DownloadCancelled:
                _remove(part_path)
                raise
            except OSError as exc:
                raise DownloadError(
                    "The installer could not be written to the update folder."
                ) from exc

            downloaded_total = offset + written
            if total is not None and downloaded_total != total:
                raise DownloadError(
                    "The connection closed before the installer finished "
                    f"downloading ({downloaded_total} of {total} bytes)."
                )
            if downloaded_total == 0:
                raise DownloadError("The update server returned an empty installer.")
            return True
        finally:
            try:
                response.close()
            except Exception:
                logger.debug("Could not close the installer response", exc_info=True)


def _parse_content_range(response) -> tuple[int, int, int | None] | None:
    value = (getattr(response, "headers", {}) or {}).get("Content-Range")
    if not isinstance(value, str):
        return None
    match = _CONTENT_RANGE_RE.fullmatch(value.strip())
    if match is None:
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    total = None if match.group(3) == "*" else int(match.group(3))
    if end < start or (total is not None and end >= total):
        return None
    return start, end, total


def _content_length(response) -> int | None:
    value = (getattr(response, "headers", {}) or {}).get("Content-Length")
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _validate_download_target(url: str, config: UpdateConfig) -> None:
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise DownloadError("The installer URL is invalid.") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise DownloadError("The installer URL must use HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise DownloadError("The installer URL must not contain credentials.")
    if is_ip_literal(parsed.hostname):
        raise DownloadError("The installer URL must not use an IP address.")
    if not host_is_trusted(parsed.hostname, config.trusted_hosts):
        raise DownloadError(
            "The installer host is not in the trusted download host list."
        )


def _describe_request_error(exc: requests.RequestException) -> str:
    if isinstance(exc, requests.Timeout):
        return "The installer download timed out. You can retry the download."
    if isinstance(exc, requests.exceptions.SSLError):
        return (
            "A secure connection to the download server could not be established."
        )
    if isinstance(exc, requests.ConnectionError):
        return (
            "The connection to the download server was interrupted. Retry to "
            "resume from the last byte."
        )
    return "The installer download was interrupted. Retry to resume it."


def _safe_component(value: str) -> str:
    cleaned = _SAFE_FILENAME_RE.sub("_", value).strip("._")
    return cleaned or "update"


def _remove(path: Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not remove %s", path, exc_info=True)
