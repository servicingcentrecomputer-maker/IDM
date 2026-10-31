"""Segment planning and crash-safe journaling for multi-connection downloads.

A segmented transfer writes directly into the ``.idm.part`` file at each
segment's byte offset.  Because the file is shared by several connections, a
small JSON journal next to the part file records how many bytes every segment
has durably written.  The journal is replaced atomically so a crash can never
leave a half-written record behind.

The journal is also the source of truth for recovery: the part file alone is
not enough, because a later segment may extend the file while earlier segments
are still missing.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MIN_SEGMENT_BYTES = 1024 * 1024
MAX_SEGMENTS = 16
_JOURNAL_VERSION = 1


@dataclass
class Segment:
    index: int
    start: int
    end: int
    done: int = 0

    @property
    def length(self) -> int:
        return max(0, self.end - self.start + 1)

    @property
    def next_offset(self) -> int:
        return self.start + self.done

    @property
    def finished(self) -> bool:
        return self.done >= self.length

    def snapshot(self, interrupted: bool = False) -> dict[str, Any]:
        if self.finished:
            status = "complete"
        elif interrupted:
            status = "paused"
        else:
            status = "active"
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "downloaded": self.done,
            "length": self.length,
            "status": status,
        }


@dataclass
class SegmentPlan:
    total: int
    url: str
    etag: str
    last_modified: str
    segments: list[Segment] = field(default_factory=list)
    version: int = _JOURNAL_VERSION

    @property
    def downloaded(self) -> int:
        return sum(segment.done for segment in self.segments)

    @property
    def complete(self) -> bool:
        return bool(self.segments) and all(segment.finished for segment in self.segments)

    @property
    def connection_count(self) -> int:
        return len(self.segments)

    def snapshot(self, interrupted: bool = False) -> list[dict[str, Any]]:
        return [segment.snapshot(interrupted) for segment in self.segments]

    def to_record(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "total": self.total,
            "url": self.url,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "segments": [
                {
                    "index": segment.index,
                    "start": segment.start,
                    "end": segment.end,
                    "done": segment.done,
                }
                for segment in self.segments
            ],
        }

    @classmethod
    def from_record(cls, record: Any) -> SegmentPlan | None:
        if not isinstance(record, dict):
            return None
        if record.get("version") != _JOURNAL_VERSION:
            return None
        try:
            total = int(record["total"])
        except (KeyError, TypeError, ValueError):
            return None
        if total <= 0:
            return None

        raw_segments = record.get("segments")
        if not isinstance(raw_segments, list) or not raw_segments:
            return None

        segments: list[Segment] = []
        expected_start = 0
        for raw in raw_segments:
            if not isinstance(raw, dict):
                return None
            try:
                index = int(raw["index"])
                start = int(raw["start"])
                end = int(raw["end"])
                done = int(raw["done"])
            except (KeyError, TypeError, ValueError):
                return None
            if index != len(segments) or start != expected_start:
                return None
            if end < start or end >= total:
                return None
            length = end - start + 1
            if done < 0 or done > length:
                return None
            segments.append(Segment(index=index, start=start, end=end, done=done))
            expected_start = end + 1
        if expected_start != total:
            return None

        return cls(
            total=total,
            url=str(record.get("url") or ""),
            etag=str(record.get("etag") or ""),
            last_modified=str(record.get("last_modified") or ""),
            segments=segments,
        )


def plan_segments(total: int, connections: int) -> list[Segment]:
    """Split ``total`` bytes into balanced non-empty segments."""
    if total <= 0:
        return []
    by_size = total // MIN_SEGMENT_BYTES
    count = max(1, min(int(connections), by_size, MAX_SEGMENTS))
    base, remainder = divmod(total, count)
    segments: list[Segment] = []
    start = 0
    for index in range(count):
        length = base + (1 if index < remainder else 0)
        segments.append(
            Segment(index=index, start=start, end=start + length - 1, done=0)
        )
        start += length
    return segments


def can_segment(total: int | None, connections: int) -> bool:
    return bool(
        total
        and total >= MIN_SEGMENT_BYTES * 2
        and connections >= 2
        and total // MIN_SEGMENT_BYTES >= 2
    )


def journal_path(part_path: Path) -> Path:
    return Path(str(part_path) + ".json")


def load_plan(part_path: Path) -> SegmentPlan | None:
    path = journal_path(part_path)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable segment journal %s: %s", path, exc)
        return None
    plan = SegmentPlan.from_record(raw)
    if plan is None:
        logger.warning("Ignoring invalid segment journal %s", path)
    return plan


def save_plan(part_path: Path, plan: SegmentPlan) -> bool:
    """Atomically replace the segment journal.  Safe to call repeatedly."""
    path = journal_path(part_path)
    temp = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(plan.to_record(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temp, path)
        return True
    except OSError as exc:
        logger.warning("Could not save the segment journal %s: %s", path, exc)
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def remove_journal(part_path: Path) -> None:
    try:
        journal_path(part_path).unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not remove the segment journal", exc_info=True)


def discard_partial(part_path: Path) -> None:
    try:
        Path(part_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove partial file %s", part_path, exc_info=True)
    remove_journal(part_path)


def inspect_partial(part_path: Path) -> tuple[int, int | None, SegmentPlan | None]:
    """Return ``(downloaded, total, plan)`` for an interrupted transfer.

    For segmented transfers the journal sum wins over the physical file size,
    because the file can be extended far ahead of completed segments.
    """
    part_path = Path(part_path)
    plan = load_plan(part_path)
    if plan is not None and part_path.exists():
        try:
            size = part_path.stat().st_size
        except OSError:
            size = 0
        if size > plan.total:
            logger.warning("Partial file %s is larger than the journal total", part_path)
            return 0, plan.total, None
        return plan.downloaded, plan.total, plan
    try:
        return (part_path.stat().st_size if part_path.exists() else 0), None, None
    except OSError:
        return 0, None, None
