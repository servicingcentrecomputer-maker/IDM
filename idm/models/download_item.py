"""Domain model for a single download."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from ..constants import PRIORITY_NORMAL


class DownloadStatus(str, Enum):
    QUEUED = "Queued"
    CONNECTING = "Connecting"
    DOWNLOADING = "Downloading"
    RETRYING = "Retrying"
    PAUSING = "Pausing"
    PAUSED = "Paused"
    STOPPING = "Stopping"
    STOPPED = "Stopped"
    COMPLETED = "Completed"
    FAILED = "Failed"


ACTIVE_STATUSES = {
    DownloadStatus.CONNECTING,
    DownloadStatus.DOWNLOADING,
    DownloadStatus.RETRYING,
    DownloadStatus.PAUSING,
    DownloadStatus.STOPPING,
}

PAUSABLE_STATUSES = {
    DownloadStatus.QUEUED,
    DownloadStatus.CONNECTING,
    DownloadStatus.DOWNLOADING,
    DownloadStatus.RETRYING,
}

STOPPABLE_STATUSES = PAUSABLE_STATUSES | {DownloadStatus.PAUSED}

RESUMABLE_STATUSES = {
    DownloadStatus.PAUSED,
    DownloadStatus.STOPPED,
    DownloadStatus.FAILED,
}

IN_PROGRESS_STATUSES = ACTIVE_STATUSES | {DownloadStatus.QUEUED}


@dataclass
class DownloadItem:
    url: str
    filename: str
    folder: str
    category: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    priority: int = PRIORITY_NORMAL
    status: DownloadStatus = DownloadStatus.QUEUED
    total_bytes: int | None = None
    downloaded_bytes: int = 0
    speed: float = 0.0
    eta: float | None = None
    error: str = ""
    content_type: str = ""
    source_browser: str = ""
    referrer: str = ""
    range_supported: bool | None = None
    queue_seq: float = 0.0
    connections: int = 4
    speed_limit_kbps: int = 0
    etag: str = ""
    last_modified: str = ""
    retry_count: int = 0
    media_kind: str = ""
    page_url: str = ""
    page_title: str = ""
    source_domain: str = ""
    file_format: str = ""
    expected_sha256: str = ""
    checksum_status: str = "not-requested"
    integrity_verified_at: str = ""
    segments: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    last_try: datetime | None = None

    @property
    def path(self) -> Path:
        return Path(self.folder) / self.filename

    @property
    def part_path(self) -> Path:
        return Path(self.folder) / f"{self.filename}.idm.part"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_in_progress(self) -> bool:
        return self.status in IN_PROGRESS_STATUSES

    @property
    def can_pause(self) -> bool:
        return self.status in PAUSABLE_STATUSES

    @property
    def can_resume(self) -> bool:
        return self.status in RESUMABLE_STATUSES

    @property
    def can_stop(self) -> bool:
        return self.status in STOPPABLE_STATUSES

    @property
    def is_completed(self) -> bool:
        return self.status == DownloadStatus.COMPLETED

    @property
    def progress(self) -> float | None:
        if not self.total_bytes or self.total_bytes <= 0:
            return None
        return max(0.0, min(1.0, self.downloaded_bytes / self.total_bytes))

    @property
    def is_video(self) -> bool:
        return self.media_kind == "video" or self.category == "Videos"

    @property
    def is_audio(self) -> bool:
        return self.media_kind == "audio" or self.category == "Music"

    @property
    def media_label(self) -> str:
        label = self.file_format.upper()
        if label:
            return label
        if self.content_type:
            return self.content_type.split("/")[-1].split(";")[0].upper()
        return "FILE"

    @property
    def integrity_label(self) -> str:
        if self.checksum_status == "verified":
            return "Verified"
        if self.checksum_status == "mismatch":
            return "Checksum mismatch"
        if self.checksum_status == "pending":
            return "Pending"
        return ""
