"""Desktop side of the browser integration.

``BrowserIntegrationService`` receives validated bridge requests, resolves the
destination folder through the download-location policy, adds the task to the
existing download manager and answers the native host.  All work happens on
the Qt GUI thread, so signals, dialogs and SQLite access stay consistent; the
actual transfer still runs on the engine's worker threads.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from downloads.location_manager import (
    MODE_ASK,
    DownloadLocationConfig,
    LocationError,
    environment_default_folder,
    resolve_destination,
)
from idm.core.settings import AppSettings
from idm.core.url_utils import guess_filename
from idm.engine.manager import DownloadManager
from idm.models.download_item import DownloadItem
from idm.version import APP_VERSION

from . import PROTOCOL_VERSION
from .bridge_server import BrowserBridgeServer
from .browser_registry import is_allowed_extension
from .browser_detector import browser_display_name
from .protocol import (
    DuplicateTracker,
    ValidationError,
    normalize_download_request,
    require_browser,
    require_extension_id,
    response_error,
    response_ok,
)

logger = logging.getLogger(__name__)

FolderPrompt = Callable[[str, str, str], str | None]
CreatePrompt = Callable[[str], bool]
SimpleCallback = Callable[[], None]

_MAX_LISTED_DOWNLOADS = 25
_STATUS_DOWNLOAD_LIMIT = 5


class BrowserIntegrationService(QObject):
    download_accepted = Signal(object)  # DownloadItem
    message = Signal(str)
    bridge_failed = Signal(str)

    def __init__(
        self,
        settings: AppSettings,
        manager: DownloadManager,
        *,
        folder_prompt: FolderPrompt | None = None,
        create_prompt: CreatePrompt | None = None,
        raise_window: SimpleCallback | None = None,
        open_settings: SimpleCallback | None = None,
        parent: QObject | None = None,
        descriptor_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._manager = manager
        self._folder_prompt = folder_prompt
        self._create_prompt = create_prompt
        self._raise_window = raise_window
        self._open_settings = open_settings
        self._dedupe = DuplicateTracker()
        self._queue: deque[tuple[dict[str, Any], Callable[[dict], None]]] = deque()
        self._busy = False
        self._bridge = BrowserBridgeServer(
            self.handle_request, self, descriptor_path=descriptor_path
        )
        self._bridge.failed.connect(self.bridge_failed)
        self._download_accepted_hook: Callable[[DownloadItem, dict], None] | None = None

    # ------------------------------------------------------------------ lifecycle
    @property
    def bridge(self) -> BrowserBridgeServer:
        return self._bridge

    @property
    def is_listening(self) -> bool:
        return self._bridge.is_running

    def start(self) -> bool:
        return self._bridge.start()

    def stop(self) -> None:
        self._bridge.stop()

    def set_accepted_hook(
        self, hook: Callable[[DownloadItem, dict[str, Any]], None] | None
    ) -> None:
        """Install a callback invoked after a browser download is accepted."""
        self._download_accepted_hook = hook

    # ------------------------------------------------------------------ requests
    def handle_request(
        self, request: dict[str, Any], respond: Callable[[dict[str, Any]], None]
    ) -> None:
        self._queue.append((request, respond))
        self._drain()

    def _drain(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            while self._queue:
                request, respond = self._queue.popleft()
                try:
                    response = self._dispatch(request)
                except ValidationError as exc:
                    response = response_error(
                        _request_id(request), exc.code, str(exc)
                    )
                except LocationError as exc:
                    response = response_error(
                        _request_id(request), exc.code, str(exc)
                    )
                except (ValueError, OSError) as exc:
                    response = response_error(
                        _request_id(request), "idm_rejected", str(exc)
                    )
                except Exception:
                    logger.exception("Browser integration request failed")
                    response = response_error(
                        _request_id(request),
                        "internal_error",
                        "IDM could not process the browser request.",
                    )
                try:
                    respond(response)
                except Exception:
                    logger.debug("Bridge response could not be delivered", exc_info=True)
        finally:
            self._busy = False

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        message_type = request.get("type")
        if not isinstance(message_type, str):
            raise ValidationError("The request has no type.", "invalid_message")

        browser = require_browser(request)
        extension_id = require_extension_id(request)
        if not is_allowed_extension(browser, extension_id):
            raise ValidationError(
                "This extension is not allowed to control IDM.",
                "unauthorized_extension",
            )

        if message_type in {"hello", "status"}:
            return self._status_response(_request_id(request), browser)
        if message_type == "request_download":
            return self._accept_download(request, browser)
        if message_type == "list_downloads":
            limit = request.get("limit", _MAX_LISTED_DOWNLOADS)
            try:
                limit = max(1, min(int(limit), _MAX_LISTED_DOWNLOADS))
            except (TypeError, ValueError):
                limit = _MAX_LISTED_DOWNLOADS
            return response_ok(
                _request_id(request),
                "downloads",
                downloads=self._download_list(limit),
                total=len(self._manager.items()),
                active=self._manager.active_count,
            )
        if message_type == "open_idm":
            self._schedule(self._raise_window)
            return response_ok(_request_id(request), "opened", target="idm")
        if message_type == "open_settings":
            self._schedule(self._open_settings)
            return response_ok(_request_id(request), "opened", target="settings")
        raise ValidationError(
            f"Unsupported message type “{message_type}”.", "unsupported_type"
        )

    @staticmethod
    def _schedule(callback: SimpleCallback | None) -> None:
        if callback is None:
            return
        QTimer.singleShot(0, callback)

    # ------------------------------------------------------------------ status
    def _status_response(self, request_id: str, browser: str) -> dict[str, Any]:
        items = self._manager.items()
        queued = sum(1 for item in items if item.status.value == "Queued")
        return response_ok(
            request_id,
            "status",
            status={
                "idm_running": True,
                "idm_version": APP_VERSION,
                "bridge_protocol": PROTOCOL_VERSION,
                "download_count": len(items),
                "active_count": self._manager.active_count,
                "queued_count": queued,
                "default_folder": self._settings.download_dir,
                "download_mode": self._settings.location_config.mode,
                "start_immediately": bool(self._settings.start_immediately),
                "browser": browser,
                "browser_display": browser_display_name(browser),
            },
            # The popup needs the transfer list too; returning it here keeps a
            # poll to one native host round trip instead of two.
            downloads=self._download_list(_STATUS_DOWNLOAD_LIMIT),
        )

    def _download_list(self, limit: int) -> list[dict[str, Any]]:
        items = sorted(
            self._manager.items(),
            key=lambda item: item.created_at,
            reverse=True,
        )[:limit]
        return [self._download_payload(item) for item in items]

    @staticmethod
    def _download_payload(item: DownloadItem) -> dict[str, Any]:
        progress = item.progress
        return {
            "id": item.id,
            "filename": item.filename,
            "folder": item.folder,
            "url": item.url,
            "status": item.status.value,
            "progress": round(progress * 100, 1) if progress is not None else None,
            "total_bytes": item.total_bytes,
            "downloaded_bytes": item.downloaded_bytes,
            "speed": round(float(item.speed), 1),
            "eta": item.eta,
            "error": item.error,
            "browser": item.source_browser,
            "browser_display": (
                browser_display_name(item.source_browser)
                if item.source_browser
                else ""
            ),
            "referrer": item.referrer,
            "media_kind": item.media_kind,
            "media_label": item.media_label,
            "page_url": item.page_url,
            "page_title": item.page_title,
            "source_domain": item.source_domain,
            "file_format": item.file_format,
        }

    # ------------------------------------------------------------------ downloads
    def _accept_download(self, request: dict[str, Any], browser: str) -> dict[str, Any]:
        normalized = normalize_download_request(request)
        request_id = normalized["request_id"]
        now = time.monotonic()

        cached = self._dedupe.get(request_id, now)
        if cached is not None:
            logger.info("Reused the response for browser request %s", request_id)
            return cached

        existing = self._manager.find_active_by_url(normalized["url"])
        if existing is not None:
            response = response_ok(
                request_id,
                "download_accepted",
                duplicate=True,
                download=self._download_payload(existing),
                message="This URL is already downloading in IDM.",
            )
            self._dedupe.put(request_id, response, now)
            logger.info(
                "Browser request %s matched existing download %s",
                request_id,
                existing.id,
            )
            return response

        config: DownloadLocationConfig = self._settings.location_config.normalized()
        if normalized["ask_folder"] and config.mode != MODE_ASK:
            # The user asked for a folder picker on this specific download, so
            # it overrides the saved default/file-type policy for this request.
            config = DownloadLocationConfig(MODE_ASK, list(config.rules))
        default_folder = self._settings.download_dir.strip() or environment_default_folder()
        filename = normalized["filename"] or guess_filename(
            normalized["url"], "download"
        )

        ask = None
        if config.mode == MODE_ASK:
            ask = lambda name, suggested: self._ask_for_folder(  # noqa: E731
                name, suggested, browser
            )

        folder, safe_name = resolve_destination(
            config,
            filename,
            default_folder,
            total_bytes=normalized["total_bytes"],
            ask=ask,
            approve_create=self._create_prompt,
        )

        item = self._manager.add_download(
            url=normalized["url"],
            filename=safe_name,
            folder=folder,
            start_immediately=bool(self._settings.start_immediately),
            source_browser=browser,
            referrer=normalized["referrer"],
            content_type=normalized["mime"],
            page_url=normalized["page_url"],
            page_title=normalized["page_title"],
            quality_label=normalized["quality_label"],
            duration_seconds=normalized["duration_seconds"],
            detected_by=normalized["detected_by"],
            media_kind_hint=normalized["media_kind"],
        )
        logger.info(
            "Accepted %s download %s (%s) from %s",
            browser,
            item.id,
            item.filename,
            normalized["url"],
        )

        response = response_ok(
            request_id,
            "download_accepted",
            duplicate=False,
            download=self._download_payload(item),
        )
        self._dedupe.put(request_id, response, now)
        self.download_accepted.emit(item)
        self.message.emit(
            f"Added “{_shorten(item.filename, 48)}” from "
            f"{browser_display_name(browser)}."
        )
        if self._download_accepted_hook is not None:
            try:
                self._download_accepted_hook(item, normalized)
            except Exception:
                logger.debug("Accepted-download hook failed", exc_info=True)
        return response

    def _ask_for_folder(
        self, filename: str, default_folder: str, browser: str
    ) -> str | None:
        if self._folder_prompt is None:
            raise LocationError(
                "IDM needs to ask for a folder, but no dialog is available.",
                "ask_unavailable",
            )
        # Interactive prompts run on the GUI thread while the bridge request is
        # pending.  Additional browser requests are queued, not lost.
        return self._folder_prompt(
            filename, default_folder, browser_display_name(browser)
        )


def _request_id(request: dict[str, Any]) -> str | None:
    value = request.get("request_id")
    return value if isinstance(value, str) and value else None


def _shorten(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


__all__ = ["BrowserIntegrationService"]
