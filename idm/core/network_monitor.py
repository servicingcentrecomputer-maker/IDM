"""Connectivity notifications used to resume downloads after an outage.

Qt's network information backend reports reachability changes without
contacting a server.  When the backend is unavailable the monitor reports
``online`` and stays silent; the download manager then falls back to its own
periodic retry timer.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard for minimal Qt builds
    from PySide6.QtNetwork import QNetworkInformation
except Exception:  # pragma: no cover
    QNetworkInformation = None  # type: ignore[assignment]


class NetworkMonitor(QObject):
    online_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._info = None
        self._available = False
        self._online = True
        self._start()

    def _start(self) -> None:
        if QNetworkInformation is None:
            return
        try:
            info = QNetworkInformation.instance()
            if info is None:
                QNetworkInformation.loadDefaultBackend()
                info = QNetworkInformation.instance()
            if info is None:
                return
            if not info.supports(QNetworkInformation.Feature.Reachability):
                return
            self._info = info
            self._available = True
            self._online = self._read(info)
            info.reachabilityChanged.connect(self._on_reachability_changed)
        except Exception:
            logger.debug("Network reachability monitoring is unavailable", exc_info=True)
            self._info = None
            self._available = False

    @staticmethod
    def _read(info) -> bool:
        try:
            return info.reachability() == QNetworkInformation.Reachability.Online
        except Exception:
            return True

    def _on_reachability_changed(self, reachability) -> None:
        online = reachability == QNetworkInformation.Reachability.Online
        offline = reachability == QNetworkInformation.Reachability.Offline
        if not (online or offline):
            return
        if online != self._online:
            self._online = online
            logger.info(
                "Network reachability changed to %s",
                "online" if online else "offline",
            )
            self.online_changed.emit(online)

    @property
    def available(self) -> bool:
        return self._available

    @property
    def online(self) -> bool:
        return self._online
