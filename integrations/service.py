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
from idm.core.categories import detect_category
from idm.core.url_utils import guess_filename, redact_url
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
    normalize_capture_request,
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
DownloadSubmit = Callable[[dict[str, Any]], DownloadItem]
DownloadPrompt = Callable[
    [dict[str, Any], DownloadSubmit], tuple[dict[str, Any], DownloadItem] | None
]
CapturePrompt = Callable[[dict[str, Any]], list[dict[str, str]] | None]

_MAX_LISTED_DOWNLOADS = 25
_STATUS_DOWNLOAD_LIMIT = 5
# Page capture answers list every file in one reply; a longer list would make
# the native messaging frame needlessly large for the extension popup.
_MAX_REPORTED_CAPTURES = 20


class BrowserIntegrationService(QObject):
    download_accepted = Signal(object)  # DownloadItem
    message = Signal(str)
    bridge_failed = Signal(str)
    # Emitted for every validated request the bridge accepts, so the UI can
    # show that a browser is really talking to IDM without polling.
    bridge_activity = Signal(str)

    def __init__(
        self,
        settings: AppSettings,
        manager: DownloadManager,
        *,
        folder_prompt: FolderPrompt | None = None,
        create_prompt: CreatePrompt | None = None,
        download_prompt: DownloadPrompt | None = None,
        capture_prompt: CapturePrompt | None = None,
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
        self._download_prompt = download_prompt
        self._capture_prompt = capture_prompt
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
        if message_type == "capture_page_links":
            return self._accept_capture(request, browser)
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

        if self._download_prompt is not None:
            return self._accept_with_dialog(
                request_id,
                normalized,
                browser,
                config,
                default_folder,
                filename,
                now,
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
            redact_url(normalized["url"]),
        )

        response = response_ok(
            request_id,
            "download_accepted",
            duplicate=False,
            download=self._download_payload(item),
        )
        self._dedupe.put(request_id, response, now)
        self._announce_accepted(item, normalized, browser)
        return response

    def _accept_with_dialog(
        self,
        request_id: str,
        normalized: dict[str, Any],
        browser: str,
        config: DownloadLocationConfig,
        default_folder: str,
        filename: str,
        now: float,
    ) -> dict[str, Any]:
        """Let the user review the browser download before IDM takes it.

        The dialog creates the task itself through ``submit`` so it only closes
        after the database row exists.  A cancelled dialog answers with the
        ``cancelled`` code, which tells the extension to resume the original
        browser download instead of discarding it.
        """
        custom = getattr(self._settings, "custom_categories", [])
        category = detect_category(filename, normalized["mime"], custom)
        remembered = self._settings.remembered_folder(category)
        suggested_folder = remembered or config.folder_for(filename, default_folder)

        payload = {
            "url": normalized["url"],
            "filename": filename,
            "folder": suggested_folder,
            "category": category,
            "content_type": normalized["mime"],
            "total_bytes": normalized["total_bytes"],
            "source_browser": browser,
            "referrer": normalized["referrer"],
            "page_url": normalized["page_url"],
            "page_title": normalized["page_title"],
            "ask_folder": normalized["ask_folder"],
        }

        def submit(values: dict[str, Any]) -> DownloadItem:
            merged = dict(values)
            merged.update(
                {
                    "source_browser": browser,
                    "referrer": normalized["referrer"],
                    "content_type": (
                        normalized["mime"] or str(values.get("content_type") or "")
                    ),
                    "page_url": normalized["page_url"],
                    "page_title": normalized["page_title"],
                    "quality_label": normalized["quality_label"],
                    "duration_seconds": normalized["duration_seconds"],
                    "detected_by": normalized["detected_by"],
                    "media_kind_hint": normalized["media_kind"],
                }
            )
            merged.pop("source_browser_override", None)
            return self._manager.add_download(**merged)

        result = self._download_prompt(payload, submit)  # type: ignore[misc]
        if result is None:
            response = response_error(
                request_id, "cancelled", "The download was cancelled in IDM."
            )
            self._dedupe.put(request_id, response, now)
            logger.info(
                "Browser request %s was cancelled in the Download File Info dialog",
                request_id,
            )
            return response

        _values, item = result
        response = response_ok(
            request_id,
            "download_accepted",
            duplicate=False,
            download=self._download_payload(item),
        )
        self._dedupe.put(request_id, response, now)
        logger.info(
            "Accepted %s download %s (%s) from %s",
            browser,
            item.id,
            item.filename,
            redact_url(normalized["url"]),
        )
        self._announce_accepted(item, normalized, browser)
        return response

    def _accept_capture(
        self, request: dict[str, Any], browser: str
    ) -> dict[str, Any]:
        """Queue the links a page capture selected.

        The whole page is confirmed once and, in ask-every-time mode, answered
        with one folder: a hundred links must not become a hundred dialogs.
        """
        normalized = normalize_capture_request(request)
        request_id = normalized["request_id"]
        now = time.monotonic()
        cached = self._dedupe.get(request_id, now)
        if cached is not None:
            return cached

        links = normalized["links"]
        if self._capture_prompt is not None:
            chosen = self._capture_prompt(
                {
                    "page_url": normalized["page_url"],
                    "page_title": normalized["page_title"],
                    "browser_display": browser_display_name(browser),
                    "links": links,
                }
            )
            if chosen is None:
                return self._remember(
                    request_id,
                    response_error(
                        request_id, "cancelled", "The page capture was cancelled in IDM."
                    ),
                    now,
                )
            selected = [entry for entry in chosen if entry.get("url")]
        else:
            selected = links

        config: DownloadLocationConfig = self._settings.location_config.normalized()
        default_folder = self._settings.download_dir.strip() or environment_default_folder()
        memo: dict[str, str] = {}

        def ask_once(filename: str, suggested: str) -> str | None:
            if "folder" not in memo:
                chosen_folder = self._ask_for_folder(filename, suggested, browser)
                if not chosen_folder:
                    return None
                memo["folder"] = chosen_folder
            return memo["folder"]

        added: list[dict[str, Any]] = []
        skipped = rejected = 0
        for entry in selected:
            url = str(entry["url"])
            filename = str(entry.get("filename") or "") or guess_filename(url, "download")
            if self._manager.find_active_by_url(url) is not None:
                skipped += 1
                continue
            try:
                folder, safe_name = resolve_destination(
                    config,
                    filename,
                    default_folder,
                    ask=ask_once,
                    approve_create=self._create_prompt,
                )
                item = self._manager.add_download(
                    url=url,
                    filename=safe_name,
                    folder=folder,
                    start_immediately=bool(self._settings.start_immediately),
                    source_browser=browser,
                    referrer=normalized["page_url"],
                    page_url=normalized["page_url"],
                    page_title=normalized["page_title"],
                    detected_by="link",
                )
            except LocationError as exc:
                if exc.code == "cancelled":
                    # The user backed out of the folder prompt; stop the batch
                    # rather than falling back to a folder they did not choose.
                    raise
                rejected += 1
                logger.info("Capture skipped %s: %s", redact_url(url), exc)
                continue
            except (ValueError, OSError) as exc:
                rejected += 1
                logger.info("Capture skipped %s: %s", redact_url(url), exc)
                continue
            added.append(self._download_payload(item))

        logger.info(
            "Page capture from %s added %s of %s links (%s already active, %s rejected)",
            redact_url(normalized["page_url"]) or normalized["page_url"] or "the page",
            len(added),
            len(selected),
            skipped,
            rejected,
        )
        response = response_ok(
            request_id,
            "page_captured",
            requested=len(selected),
            added=len(added),
            skipped=skipped,
            rejected=rejected,
            downloads=added[:_MAX_REPORTED_CAPTURES],
        )
        if added:
            self.message.emit(
                f"Captured {len(added)} link{'s' if len(added) != 1 else ''} from "
                f"{normalized['page_title'] or normalized['page_url'] or 'the page'}."
            )
        return self._remember(request_id, response, now)

    def _remember(
        self, request_id: str, response: dict[str, Any], now: float
    ) -> dict[str, Any]:
        self._dedupe.put(request_id, response, now)
        return response

    def _announce_accepted(
        self, item: DownloadItem, normalized: dict[str, Any], browser: str
    ) -> None:
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
