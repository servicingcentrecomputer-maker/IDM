"""Qt background workers for update checks and installer downloads."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.settings import AppSettings
from ..updater.config import UpdateConfig, build_update_config
from ..updater.errors import DownloadCancelled, UpdateError
from ..updater.manifest_validator import UpdateManifest
from ..updater.package_verifier import verify_installer
from ..updater.update_checker import UpdateCheckResult, check_for_updates
from ..updater.update_downloader import DownloadedInstaller, InstallerDownloader
from ..updater.version_manager import Version, current_version

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedUpdate:
    downloaded: DownloadedInstaller
    publisher: str
    size: int


def config_from_settings(settings: AppSettings) -> UpdateConfig:
    return build_update_config(
        getattr(settings, "update_manifest_url", ""),
        getattr(settings, "update_publisher", ""),
        getattr(settings, "update_channel", ""),
    )


class UpdateCheckWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, config: UpdateConfig, current: Version, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._current = current

    def run(self) -> None:
        try:
            result = check_for_updates(self._config, self._current)
        except UpdateError as exc:
            logger.warning("Update check failed: %s", exc)
            self.failed.emit(str(exc))
            return
        except Exception:
            logger.exception("Unexpected update check failure")
            self.failed.emit(
                "The update check failed unexpectedly. See the log for details."
            )
            return
        self.succeeded.emit(result)


class UpdateInstallWorker(QThread):
    progress = Signal(int, int)
    status = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        config: UpdateConfig,
        manifest: UpdateManifest,
        update_dir: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._manifest = manifest
        self._update_dir = Path(update_dir)
        self._cancel_event = threading.Event()
        self._downloader = InstallerDownloader(config, cancel_event=self._cancel_event)

    def cancel(self) -> None:
        self._cancel_event.set()
        self._downloader.cancel()

    def run(self) -> None:
        try:
            self.status.emit("Downloading update…")
            downloaded = self._downloader.download(
                self._manifest,
                self._update_dir,
                progress=lambda done, total: self.progress.emit(
                    done, -1 if total is None else total
                ),
            )
            if self._cancel_event.is_set():
                raise DownloadCancelled("The update download was cancelled.")

            self.status.emit("Verifying update package…")
            verified = verify_installer(
                downloaded.path,
                downloaded.sha256,
                self._config.expected_publisher,
            )
            self.status.emit("Preparing installation…")
            self.succeeded.emit(
                PreparedUpdate(
                    downloaded=downloaded,
                    publisher=verified.publisher,
                    size=verified.size,
                )
            )
        except DownloadCancelled:
            logger.info("Update download cancelled by the user")
            self.cancelled.emit()
        except UpdateError as exc:
            logger.warning("Update installation preparation failed: %s", exc)
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Unexpected update download failure")
            self.failed.emit(
                "The update could not be prepared. See the log for details."
            )


__all__ = [
    "PreparedUpdate",
    "UpdateCheckResult",
    "UpdateCheckWorker",
    "UpdateInstallWorker",
    "config_from_settings",
    "current_version",
]
