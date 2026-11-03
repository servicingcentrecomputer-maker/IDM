"""SHA-256 helpers, including verification of files that are already on disk."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot, QThreadPool

logger = logging.getLogger(__name__)

_BLOCK_SIZE = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(_BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


class _JobSignals(QObject):
    finished = Signal(str, str, str)


class _HashJob(QRunnable):
    def __init__(self, key: str, path: Path, signals: _JobSignals) -> None:
        super().__init__()
        self.key = key
        self.path = path
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(self.key, sha256_of(self.path), "")
        except (OSError, ValueError) as exc:
            logger.debug("Checksum job failed for %s", self.path, exc_info=True)
            self.signals.finished.emit(self.key, "", str(exc))


class ChecksumVerifier(QObject):
    """Hashes files on a worker pool so the UI never stalls on big downloads."""

    finished = Signal(str, str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._jobs: dict[str, _JobSignals] = {}
        self.finished.connect(self._forget)

    def verify(self, key: str, path: Path) -> bool:
        """Start a hash for ``key``.  Returns False when one is already running."""
        if key in self._jobs or not Path(path).is_file():
            return False
        signals = _JobSignals(self)
        signals.finished.connect(self.finished)
        self._jobs[key] = signals
        self._pool.start(_HashJob(key, Path(path), signals))
        return True

    def is_running(self, key: str) -> bool:
        return key in self._jobs

    @Slot(str, str, str)
    def _forget(self, key: str, digest: str, error: str) -> None:
        signals = self._jobs.pop(key, None)
        if signals is not None:
            signals.deleteLater()

    def wait(self, timeout_ms: int = 5000) -> None:
        self._pool.waitForDone(timeout_ms)

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(5000)


__all__ = ["ChecksumVerifier", "sha256_of"]
