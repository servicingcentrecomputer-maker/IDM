"""Persistent one-off download schedules."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..engine.manager import DownloadManager
from .paths import schedules_file

logger = logging.getLogger(__name__)

SCHEDULE_ACTIONS = {
    "resume_all": "Resume all downloads",
    "pause_all": "Pause all downloads",
}


@dataclass
class ScheduleEntry:
    run_at: datetime
    action: str
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex


class DownloadScheduler(QObject):
    schedules_changed = Signal()
    schedule_fired = Signal(str)

    def __init__(self, manager: DownloadManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._path = schedules_file()
        self._entries: list[ScheduleEntry] = []
        self._load()

        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def entries(self) -> list[ScheduleEntry]:
        return sorted(self._entries, key=lambda entry: entry.run_at)

    def add(self, run_at: datetime, action: str) -> ScheduleEntry:
        if action not in SCHEDULE_ACTIONS:
            raise ValueError("Unknown schedule action.")
        if run_at <= datetime.now() + timedelta(seconds=1):
            raise ValueError("Choose a time in the future.")
        entry = ScheduleEntry(run_at=run_at.replace(microsecond=0), action=action)
        self._entries.append(entry)
        self._save()
        self.schedules_changed.emit()
        logger.info("Scheduled %s at %s", action, entry.run_at)
        return entry

    def remove(self, schedule_id: str) -> None:
        before = len(self._entries)
        self._entries = [entry for entry in self._entries if entry.id != schedule_id]
        if len(self._entries) != before:
            self._save()
            self.schedules_changed.emit()

    def _tick(self) -> None:
        now = datetime.now()
        due = [entry for entry in self._entries if entry.run_at <= now]
        if not due:
            return
        due_ids = {entry.id for entry in due}
        self._entries = [entry for entry in self._entries if entry.id not in due_ids]
        self._save()
        self.schedules_changed.emit()
        for entry in due:
            try:
                if entry.action == "resume_all":
                    self._manager.resume_all()
                else:
                    self._manager.pause_all()
            except Exception:
                logger.exception("Scheduled action failed: %s", entry.action)
            self.schedule_fired.emit(SCHEDULE_ACTIONS[entry.action])

    def _load(self) -> None:
        path = Path(self._path)
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Could not read schedules: %s", exc)
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                run_at = datetime.fromisoformat(str(item["run_at"]))
                action = str(item["action"])
                if action not in SCHEDULE_ACTIONS:
                    continue
                self._entries.append(
                    ScheduleEntry(run_at=run_at, action=action, id=str(item.get("id", "")))
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping invalid schedule: %s", exc)

    def _save(self) -> None:
        payload = [
            {
                "id": entry.id,
                "run_at": entry.run_at.isoformat(timespec="seconds"),
                "action": entry.action,
            }
            for entry in self._entries
        ]
        path = Path(self._path)
        temp = path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp.replace(path)
        except OSError as exc:
            logger.error("Could not save schedules: %s", exc)

    def shutdown(self) -> None:
        self._timer.stop()
