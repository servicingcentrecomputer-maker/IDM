"""SQLite storage for application settings and download history.

The database lives in the user's AppData directory.  All access happens on the
GUI thread; the download workers only emit signals, so no cross-thread SQLite
access is required.

Schema changes are applied through numbered migrations recorded in
``PRAGMA user_version``.  Existing rows are preserved; new columns are added in
place and the legacy ``settings`` table is copied into ``app_settings`` once.
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import database_backup_dir, database_file, ensure_app_layout

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 5

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    kind  TEXT NOT NULL DEFAULT 'json'
);

CREATE TABLE IF NOT EXISTS downloads (
    id               TEXT PRIMARY KEY,
    url              TEXT NOT NULL,
    filename         TEXT NOT NULL,
    folder           TEXT NOT NULL,
    category         TEXT NOT NULL DEFAULT 'Other',
    priority         INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'Queued',
    total_bytes      INTEGER,
    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
    speed            REAL NOT NULL DEFAULT 0,
    eta              REAL,
    error            TEXT NOT NULL DEFAULT '',
    content_type     TEXT NOT NULL DEFAULT '',
    range_supported  INTEGER,
    created_at       TEXT NOT NULL,
    completed_at     TEXT,
    last_try         TEXT,
    queue_seq        REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_downloads_created
    ON downloads(created_at);
CREATE INDEX IF NOT EXISTS idx_downloads_status
    ON downloads(status);
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    kind  TEXT NOT NULL DEFAULT 'json'
);

INSERT OR IGNORE INTO app_settings (key, value, kind)
    SELECT key, value, kind FROM settings;

CREATE TABLE IF NOT EXISTS download_segments (
    download_id      TEXT NOT NULL,
    segment_index    INTEGER NOT NULL,
    start_byte       INTEGER NOT NULL,
    end_byte         INTEGER NOT NULL,
    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active',
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (download_id, segment_index),
    FOREIGN KEY (download_id) REFERENCES downloads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_segments_download
    ON download_segments(download_id);

CREATE TABLE IF NOT EXISTS download_queue (
    download_id TEXT PRIMARY KEY,
    position    INTEGER NOT NULL,
    state       TEXT NOT NULL DEFAULT 'waiting',
    priority    INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (download_id) REFERENCES downloads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_queue_position
    ON download_queue(position);

CREATE TABLE IF NOT EXISTS download_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    download_id TEXT,
    level       TEXT NOT NULL DEFAULT 'info',
    message     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_download_logs_download
    ON download_logs(download_id, created_at);
"""

# Columns added in schema version 2.  Declarations are constants, not user data.
_V2_DOWNLOAD_COLUMNS = (
    ("connections", "INTEGER NOT NULL DEFAULT 4"),
    ("speed_limit_kbps", "INTEGER NOT NULL DEFAULT 0"),
    ("etag", "TEXT NOT NULL DEFAULT ''"),
    ("last_modified", "TEXT NOT NULL DEFAULT ''"),
    ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
)

# Schema version 3 records where a download came from: the browser name shown
# in the UI and the HTTP referrer supplied by the extension.  Both are
# informational and default to empty for downloads added in IDM itself.
_V3_DOWNLOAD_COLUMNS = (
    ("source_browser", "TEXT NOT NULL DEFAULT ''"),
    ("referrer", "TEXT NOT NULL DEFAULT ''"),
)

# Schema version 4 adds media identification, source page metadata and
# optional integrity verification.  Every column has a default so V2 rows
# remain valid without rewriting them.
_V4_DOWNLOAD_COLUMNS = (
    ("media_kind", "TEXT NOT NULL DEFAULT ''"),
    ("page_url", "TEXT NOT NULL DEFAULT ''"),
    ("page_title", "TEXT NOT NULL DEFAULT ''"),
    ("source_domain", "TEXT NOT NULL DEFAULT ''"),
    ("file_format", "TEXT NOT NULL DEFAULT ''"),
    ("expected_sha256", "TEXT NOT NULL DEFAULT ''"),
    ("checksum_status", "TEXT NOT NULL DEFAULT 'not-requested'"),
    ("integrity_verified_at", "TEXT NOT NULL DEFAULT ''"),
)

# Schema version 5 adds the optional per-download description shown in the
# Download File Info dialog and the "Download Later" hold flag.  A held
# download stays in the queue without starting until the user releases it.
_V5_DOWNLOAD_COLUMNS = (
    ("description", "TEXT NOT NULL DEFAULT ''"),
    ("start_later", "INTEGER NOT NULL DEFAULT 0"),
)

_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS media_metadata (
    download_id      TEXT PRIMARY KEY,
    media_kind       TEXT NOT NULL DEFAULT '',
    page_url         TEXT NOT NULL DEFAULT '',
    page_title       TEXT NOT NULL DEFAULT '',
    source_domain    TEXT NOT NULL DEFAULT '',
    quality_label    TEXT NOT NULL DEFAULT '',
    duration_seconds INTEGER,
    detected_by      TEXT NOT NULL DEFAULT '',
    detected_at      TEXT NOT NULL,
    FOREIGN KEY (download_id) REFERENCES downloads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_media_kind
    ON media_metadata(media_kind);

CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL DEFAULT 'info',
    title       TEXT NOT NULL,
    message     TEXT NOT NULL DEFAULT '',
    download_id TEXT,
    created_at  TEXT NOT NULL,
    read_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_notifications_created
    ON notifications(created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_unread
    ON notifications(read_at);

CREATE TABLE IF NOT EXISTS download_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    download_id TEXT,
    event       TEXT NOT NULL,
    bytes       INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_download_events_created
    ON download_events(created_at);
CREATE INDEX IF NOT EXISTS idx_download_events_download
    ON download_events(download_id);
"""

_DOWNLOAD_COLUMNS = (
    "id",
    "url",
    "filename",
    "folder",
    "category",
    "priority",
    "status",
    "total_bytes",
    "downloaded_bytes",
    "speed",
    "eta",
    "error",
    "content_type",
    "range_supported",
    "created_at",
    "completed_at",
    "last_try",
    "queue_seq",
    "connections",
    "speed_limit_kbps",
    "etag",
    "last_modified",
    "retry_count",
    "source_browser",
    "referrer",
    "media_kind",
    "page_url",
    "page_title",
    "source_domain",
    "file_format",
    "expected_sha256",
    "checksum_status",
    "integrity_verified_at",
    "description",
    "start_later",
)

# Fields that older callers may omit; their columns are NOT NULL.
_DOWNLOAD_DEFAULTS = {
    "source_browser": "",
    "referrer": "",
    "media_kind": "",
    "page_url": "",
    "page_title": "",
    "source_domain": "",
    "file_format": "",
    "expected_sha256": "",
    "checksum_status": "not-requested",
    "integrity_verified_at": "",
    "description": "",
    "start_later": 0,
}

_UPSERT_DOWNLOAD = f"""
INSERT INTO downloads ({", ".join(_DOWNLOAD_COLUMNS)})
VALUES ({", ".join("?" for _ in _DOWNLOAD_COLUMNS)})
ON CONFLICT(id) DO UPDATE SET
{", ".join(f"{column} = excluded.{column}" for column in _DOWNLOAD_COLUMNS[1:])}
"""


class Database:
    """Small SQLite wrapper with settings and download-record helpers."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            ensure_app_layout()
        self._uses_default_path = path is None
        self.path = Path(path) if path is not None else database_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migration_backup_path: Path | None = None
        connection = sqlite3.connect(str(self.path), timeout=8)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            from_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if 0 < from_version < SCHEMA_VERSION:
                self.migration_backup_path = self._backup_before_migration(
                    connection, from_version
                )
            self._migrate(connection)
        except Exception:
            connection.close()
            raise
        self._connection: sqlite3.Connection | None = connection
        logger.debug("SQLite database ready at %s", self.path)

    def _backup_before_migration(
        self, connection: sqlite3.Connection, from_version: int
    ) -> Path:
        """Write and verify a consistent copy before any schema change."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        directory = (
            database_backup_dir()
            if self._uses_default_path
            else self.path.parent / "backups"
        )
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / (
            f"pre-migration-v{from_version}-{stamp}.sqlite3"
        )
        target = sqlite3.connect(str(destination))
        try:
            connection.backup(target)
            target.commit()
            integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
            if str(integrity).casefold() != "ok":
                raise RuntimeError(
                    f"Pre-migration backup failed its integrity check: {integrity}"
                )
        except Exception:
            target.close()
            destination.unlink(missing_ok=True)
            raise
        target.close()
        logger.info(
            "Verified pre-migration backup of schema %s at %s",
            from_version,
            destination,
        )
        return destination

    # ------------------------------------------------------------------ migrations
    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        try:
            if version < 1:
                connection.executescript(_SCHEMA_V1)
                logger.info("Created SQLite schema version 1")
                version = 1
            if version < 2:
                connection.executescript(_SCHEMA_V2)
                existing = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(downloads)")
                }
                for name, declaration in _V2_DOWNLOAD_COLUMNS:
                    if name not in existing:
                        connection.execute(
                            f"ALTER TABLE downloads ADD COLUMN {name} {declaration}"
                        )
                connection.execute("PRAGMA user_version = 2")
                connection.commit()
                logger.info("Migrated SQLite schema to version 2")
                version = 2
            if version < 3:
                existing = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(downloads)")
                }
                for name, declaration in _V3_DOWNLOAD_COLUMNS:
                    if name not in existing:
                        connection.execute(
                            f"ALTER TABLE downloads ADD COLUMN {name} {declaration}"
                        )
                connection.execute("PRAGMA user_version = 3")
                connection.commit()
                logger.info("Migrated SQLite schema to version 3")
                version = 3
            if version < 4:
                existing = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(downloads)")
                }
                for name, declaration in _V4_DOWNLOAD_COLUMNS:
                    if name not in existing:
                        connection.execute(
                            f"ALTER TABLE downloads ADD COLUMN {name} {declaration}"
                        )
                connection.executescript(_SCHEMA_V4)
                connection.execute("PRAGMA user_version = 4")
                connection.commit()
                logger.info("Migrated SQLite schema to version 4")
                version = 4
            if version < 5:
                existing = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(downloads)")
                }
                for name, declaration in _V5_DOWNLOAD_COLUMNS:
                    if name not in existing:
                        connection.execute(
                            f"ALTER TABLE downloads ADD COLUMN {name} {declaration}"
                        )
                connection.execute("PRAGMA user_version = 5")
                connection.commit()
                logger.info("Migrated SQLite schema to version 5")
                version = 5
            if version < SCHEMA_VERSION:
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
                version = SCHEMA_VERSION
            if version > SCHEMA_VERSION:
                logger.warning(
                    "Database schema version %s is newer than this build (%s)",
                    version,
                    SCHEMA_VERSION,
                )
        except sqlite3.Error:
            connection.rollback()
            raise

    def schema_version(self) -> int:
        connection = self._connection_or_raise()
        row = connection.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def quick_check(self) -> None:
        """Raise when SQLite reports any database corruption."""
        connection = self._connection_or_raise()
        row = connection.execute("PRAGMA quick_check").fetchone()
        result = str(row[0]) if row else "missing"
        if result.casefold() != "ok":
            raise RuntimeError(f"SQLite quick_check failed: {result}")

    # ------------------------------------------------------------------ settings
    def setting_count(self) -> int:
        connection = self._connection_or_raise()
        row = connection.execute("SELECT COUNT(*) AS count FROM app_settings").fetchone()
        return int(row["count"]) if row else 0

    def load_settings(self) -> dict[str, Any]:
        connection = self._connection_or_raise()
        values: dict[str, Any] = {}
        for row in connection.execute("SELECT key, value, kind FROM app_settings"):
            try:
                if row["kind"] == "bytes":
                    values[row["key"]] = base64.b64decode(row["value"])
                else:
                    values[row["key"]] = json.loads(row["value"])
            except (ValueError, TypeError, json.JSONDecodeError):
                logger.warning("Ignoring unreadable setting %s", row["key"])
        return values

    def save_settings(self, values: dict[str, Any]) -> None:
        connection = self._connection_or_raise()
        payload: list[tuple[str, str, str]] = []
        for key, value in values.items():
            if isinstance(value, (bytes, bytearray)):
                payload.append(
                    (key, base64.b64encode(bytes(value)).decode("ascii"), "bytes")
                )
            else:
                payload.append((key, json.dumps(value), "json"))
        with connection:
            connection.executemany(
                """
                INSERT INTO app_settings (key, value, kind) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    kind = excluded.kind
                """,
                payload,
            )

    def delete_setting(self, key: str) -> None:
        connection = self._connection_or_raise()
        with connection:
            connection.execute("DELETE FROM app_settings WHERE key = ?", (key,))

    # ------------------------------------------------------------------ downloads
    def load_downloads(self) -> list[dict[str, Any]]:
        connection = self._connection_or_raise()
        rows = connection.execute(
            "SELECT * FROM downloads ORDER BY created_at ASC, rowid ASC"
        ).fetchall()
        return [dict(row) for row in rows]

    def save_download(self, record: dict[str, Any]) -> None:
        connection = self._connection_or_raise()
        values = tuple(
            record.get(column, _DOWNLOAD_DEFAULTS.get(column))
            for column in _DOWNLOAD_COLUMNS
        )
        with connection:
            connection.execute(_UPSERT_DOWNLOAD, values)

    def save_downloads(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        connection = self._connection_or_raise()
        payload = [
            tuple(
                record.get(column, _DOWNLOAD_DEFAULTS.get(column))
                for column in _DOWNLOAD_COLUMNS
            )
            for record in records
        ]
        with connection:
            connection.executemany(_UPSERT_DOWNLOAD, payload)

    def delete_download(self, download_id: str) -> None:
        connection = self._connection_or_raise()
        with connection:
            connection.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
            connection.execute(
                "DELETE FROM download_segments WHERE download_id = ?", (download_id,)
            )
            connection.execute(
                "DELETE FROM download_queue WHERE download_id = ?", (download_id,)
            )

    # ------------------------------------------------------------------ segments
    def replace_segments(
        self, download_id: str, segments: Iterable[dict[str, Any]]
    ) -> None:
        rows = []
        now = datetime.now().isoformat(timespec="seconds")
        for segment in segments:
            try:
                rows.append(
                    (
                        download_id,
                        int(segment["index"]),
                        int(segment["start"]),
                        int(segment["end"]),
                        int(segment.get("downloaded", 0)),
                        str(segment.get("status") or "active"),
                        now,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        connection = self._connection_or_raise()
        with connection:
            connection.execute(
                "DELETE FROM download_segments WHERE download_id = ?", (download_id,)
            )
            if rows:
                connection.executemany(
                    """
                    INSERT INTO download_segments (
                        download_id, segment_index, start_byte, end_byte,
                        downloaded_bytes, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

    def load_segments(self, download_id: str) -> list[dict[str, Any]]:
        connection = self._connection_or_raise()
        rows = connection.execute(
            """
            SELECT segment_index, start_byte, end_byte, downloaded_bytes, status,
                   updated_at
              FROM download_segments
             WHERE download_id = ?
             ORDER BY segment_index
            """,
            (download_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_segments(self, download_id: str) -> None:
        connection = self._connection_or_raise()
        with connection:
            connection.execute(
                "DELETE FROM download_segments WHERE download_id = ?", (download_id,)
            )

    # ------------------------------------------------------------------ queue
    def replace_queue(self, entries: Iterable[dict[str, Any]]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for position, entry in enumerate(entries):
            download_id = str(entry.get("download_id") or "")
            if not download_id:
                continue
            rows.append(
                (
                    download_id,
                    position,
                    str(entry.get("state") or "waiting"),
                    int(entry.get("priority") or 1),
                    now,
                )
            )
        connection = self._connection_or_raise()
        with connection:
            connection.execute("DELETE FROM download_queue")
            if rows:
                connection.executemany(
                    """
                    INSERT INTO download_queue (
                        download_id, position, state, priority, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    rows,
                )

    def load_queue(self) -> list[dict[str, Any]]:
        connection = self._connection_or_raise()
        rows = connection.execute(
            "SELECT * FROM download_queue ORDER BY position"
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ logs
    def add_download_log(
        self, download_id: str | None, level: str, message: str
    ) -> None:
        connection = self._connection_or_raise()
        with connection:
            connection.execute(
                """
                INSERT INTO download_logs (download_id, level, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    download_id,
                    str(level or "info"),
                    str(message or ""),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def load_download_logs(
        self, download_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        connection = self._connection_or_raise()
        limit = max(1, min(int(limit), 5000))
        if download_id is None:
            rows = connection.execute(
                "SELECT * FROM download_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM download_logs
                 WHERE download_id = ?
                 ORDER BY id DESC LIMIT ?
                """,
                (download_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ media metadata
    def save_media_metadata(self, download_id: str, record: dict[str, Any]) -> None:
        connection = self._connection_or_raise()
        now = datetime.now().isoformat(timespec="seconds")
        duration = record.get("duration_seconds")
        try:
            duration_value = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_value = None
        with connection:
            connection.execute(
                """
                INSERT INTO media_metadata (
                    download_id, media_kind, page_url, page_title, source_domain,
                    quality_label, duration_seconds, detected_by, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(download_id) DO UPDATE SET
                    media_kind = excluded.media_kind,
                    page_url = excluded.page_url,
                    page_title = excluded.page_title,
                    source_domain = excluded.source_domain,
                    quality_label = excluded.quality_label,
                    duration_seconds = excluded.duration_seconds,
                    detected_by = excluded.detected_by,
                    detected_at = excluded.detected_at
                """,
                (
                    download_id,
                    str(record.get("media_kind") or "")[:32],
                    str(record.get("page_url") or "")[:8192],
                    str(record.get("page_title") or "")[:1024],
                    str(record.get("source_domain") or "")[:255],
                    str(record.get("quality_label") or "")[:64],
                    duration_value,
                    str(record.get("detected_by") or "")[:64],
                    str(record.get("detected_at") or now),
                ),
            )

    def load_media_metadata(self, download_id: str) -> dict[str, Any] | None:
        connection = self._connection_or_raise()
        row = connection.execute(
            "SELECT * FROM media_metadata WHERE download_id = ?", (download_id,)
        ).fetchone()
        return dict(row) if row else None

    def load_all_media_metadata(self) -> dict[str, dict[str, Any]]:
        connection = self._connection_or_raise()
        rows = connection.execute("SELECT * FROM media_metadata").fetchall()
        return {str(row["download_id"]): dict(row) for row in rows}

    def delete_media_metadata(self, download_id: str) -> None:
        connection = self._connection_or_raise()
        with connection:
            connection.execute(
                "DELETE FROM media_metadata WHERE download_id = ?", (download_id,)
            )

    # ------------------------------------------------------------------ notifications
    def add_notification(
        self,
        kind: str,
        title: str,
        message: str = "",
        download_id: str | None = None,
    ) -> int:
        connection = self._connection_or_raise()
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO notifications (kind, title, message, download_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(kind or "info")[:32],
                    str(title or "")[:255],
                    str(message or "")[:2000],
                    download_id,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        return int(cursor.lastrowid or 0)

    def load_notifications(
        self, limit: int = 100, unread_only: bool = False
    ) -> list[dict[str, Any]]:
        connection = self._connection_or_raise()
        limit = max(1, min(int(limit), 1000))
        query = "SELECT * FROM notifications"
        if unread_only:
            query += " WHERE read_at IS NULL"
        query += " ORDER BY id DESC LIMIT ?"
        rows = connection.execute(query, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def unread_notification_count(self) -> int:
        connection = self._connection_or_raise()
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM notifications WHERE read_at IS NULL"
        ).fetchone()
        return int(row["count"]) if row else 0

    def mark_notification_read(self, notification_id: int) -> None:
        connection = self._connection_or_raise()
        with connection:
            connection.execute(
                "UPDATE notifications SET read_at = ? WHERE id = ? AND read_at IS NULL",
                (datetime.now().isoformat(timespec="seconds"), int(notification_id)),
            )

    def mark_all_notifications_read(self) -> int:
        connection = self._connection_or_raise()
        with connection:
            cursor = connection.execute(
                "UPDATE notifications SET read_at = ? WHERE read_at IS NULL",
                (datetime.now().isoformat(timespec="seconds"),),
            )
        return int(cursor.rowcount or 0)

    def delete_notification(self, notification_id: int) -> None:
        connection = self._connection_or_raise()
        with connection:
            connection.execute(
                "DELETE FROM notifications WHERE id = ?", (int(notification_id),)
            )

    def clear_notifications(self) -> int:
        connection = self._connection_or_raise()
        with connection:
            cursor = connection.execute("DELETE FROM notifications")
        return int(cursor.rowcount or 0)

    # ------------------------------------------------------------------ analytics
    def add_download_event(
        self, download_id: str | None, event: str, byte_count: int = 0
    ) -> None:
        connection = self._connection_or_raise()
        with connection:
            connection.execute(
                """
                INSERT INTO download_events (download_id, event, bytes, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    download_id,
                    str(event or "event")[:64],
                    max(0, int(byte_count)),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def load_download_events(self, limit: int = 200) -> list[dict[str, Any]]:
        connection = self._connection_or_raise()
        limit = max(1, min(int(limit), 2000))
        rows = connection.execute(
            "SELECT * FROM download_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def download_summary(self) -> dict[str, Any]:
        connection = self._connection_or_raise()
        row = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN status IN ('Queued', 'Connecting', 'Downloading',
                                           'Retrying', 'Pausing', 'Stopping')
                            THEN 1 ELSE 0 END) AS active,
                   COALESCE(SUM(CASE WHEN status = 'Completed' THEN total_bytes ELSE 0 END), 0)
                            AS completed_bytes,
                   MIN(created_at) AS first_at,
                   MAX(completed_at) AS last_completed_at
              FROM downloads
            """
        ).fetchone()
        return dict(row) if row else {}

    def daily_activity(self, days: int = 14) -> list[dict[str, Any]]:
        connection = self._connection_or_raise()
        days = max(1, min(int(days), 365))
        rows = connection.execute(
            """
            SELECT substr(COALESCE(completed_at, created_at), 1, 10) AS day,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) AS failed,
                   COALESCE(SUM(CASE WHEN status = 'Completed' THEN total_bytes ELSE 0 END), 0)
                       AS bytes
              FROM downloads
             WHERE substr(COALESCE(completed_at, created_at), 1, 10) >= date('now', ?)
             GROUP BY day
             ORDER BY day
            """,
            (f"-{days} days",),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ lifecycle
    def backup(self, destination: Path) -> Path:
        """Write a consistent copy of the database using SQLite's online backup."""
        connection = self._connection_or_raise()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(destination))
        try:
            connection.backup(target)
            target.commit()
        finally:
            target.close()
        return destination

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                logger.debug("Could not close the database cleanly", exc_info=True)

    def _connection_or_raise(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("The database connection is closed.")
        return self._connection
