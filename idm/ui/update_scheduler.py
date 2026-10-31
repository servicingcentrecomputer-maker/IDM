"""Background update checking: startup, interval and safe postponement.

The scheduler never downloads or installs anything by itself.  It only asks the
release server whether a newer version exists and reports the result to the
main window, which decides whether to notify the user or start an automatic
download according to Options → Updates.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.settings import AppSettings
from ..engine.manager import DownloadManager
from ..updater.schedule import evaluate_schedule
from ..updater.update_checker import UpdateCheckResult
from ..updater.version_manager import current_version
from .update_service import UpdateCheckWorker, config_from_settings

logger = logging.getLogger(__name__)

STARTUP_DELAY_MS = 20_000
TICK_INTERVAL_MS = 10 * 60 * 1000


class UpdateScheduler(QObject):
    update_available = Signal(object)
    no_update = Signal(object)
    check_failed = Signal(str)

    def __init__(
        self,
        settings: AppSettings,
        manager: DownloadManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._manager = manager
        self._worker: UpdateCheckWorker | None = None
        self._busy = False
        self._closing = False

        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self.tick)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(TICK_INTERVAL_MS)
        self._tick_timer.timeout.connect(self.tick)

    def start(self) -> None:
        if self._closing:
            return
        self._startup_timer.start(STARTUP_DELAY_MS)
        self._tick_timer.start()

    def stop(self) -> None:
        self._closing = True
        self._startup_timer.stop()
        self._tick_timer.stop()
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            if not worker.wait(2500):
                logger.warning("Terminating an unresponsive update check")
                worker.terminate()
                worker.wait(1000)
        self._busy = False

    def tick(self) -> None:
        if self._closing or self._busy:
            return
        config = config_from_settings(self._settings)
        decision = evaluate_schedule(
            enabled=bool(getattr(self._settings, "update_auto_check", True)),
            configured=config.configured,
            interval_hours=getattr(
                self._settings, "update_check_interval_hours", 24
            ),
            last_check=getattr(self._settings, "update_last_check", ""),
            active_downloads=self._manager.active_count,
        )
        if not decision.should_check:
            logger.debug("Background update check skipped: %s", decision.reason)
            return
        self._run_check()

    def _run_check(self) -> None:
        config = config_from_settings(self._settings)
        self._busy = True
        worker = UpdateCheckWorker(config, current_version(), self)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()

    def _on_succeeded(self, result: UpdateCheckResult) -> None:
        self._busy = False
        try:
            self._settings.note_update_check()
        except Exception:
            logger.debug("Could not record the update check time", exc_info=True)
        if result.update_available:
            logger.info(
                "Background check found IDM %s (installed %s)",
                result.latest_version,
                result.current_version,
            )
            self.update_available.emit(result)
        else:
            logger.info("Background check: IDM is up to date")
            self.no_update.emit(result)

    def _on_failed(self, message: str) -> None:
        self._busy = False
        try:
            self._settings.note_update_check()
        except Exception:
            logger.debug("Could not record the update check time", exc_info=True)
        logger.warning("Background update check failed: %s", message)
        self.check_failed.emit(message)

    def _on_finished(self) -> None:
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        if worker is self._worker:
            self._worker = None
