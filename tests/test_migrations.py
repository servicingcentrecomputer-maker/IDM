"""Versioned SQLite migration and new-table persistence tests."""

from __future__ import annotations

import sqlite3

from idm.core.database import (
    _SCHEMA_V1,
    _SCHEMA_V2,
    _SCHEMA_V4,
    _V2_DOWNLOAD_COLUMNS,
    _V3_DOWNLOAD_COLUMNS,
    _V4_DOWNLOAD_COLUMNS,
    SCHEMA_VERSION,
    Database,
)

_LEGACY_DOWNLOAD_SQL = """
INSERT INTO downloads (
    id, url, filename, folder, category, priority, status, total_bytes,
    downloaded_bytes, speed, eta, error, content_type, range_supported,
    created_at, completed_at, last_try, queue_seq
) VALUES (
    'legacy-1', 'https://example.com/old.bin', 'old.bin', 'C:/Downloads',
    'Other', 1, 'Completed', 1024, 1024, 0, NULL, '', 'application/octet-stream',
    1, '2024-01-01T10:00:00', '2024-01-01T10:01:00', NULL, 0
)
"""


def _create_legacy_database(path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_SCHEMA_V1)
        connection.execute(
            "INSERT INTO settings (key, value, kind) VALUES (?, ?, ?)",
            ("theme", '"dark"', "json"),
        )
        connection.execute(_LEGACY_DOWNLOAD_SQL)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    finally:
        connection.close()


def _columns(database: Database, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in database._connection.execute(f"PRAGMA table_info({table})")
    }


def _tables(database: Database) -> set[str]:
    return {
        str(row["name"])
        for row in database._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def test_v1_database_is_migrated_without_losing_records(tmp_path) -> None:
    path = tmp_path / "legacy.sqlite3"
    _create_legacy_database(path)

    database = Database(path)
    try:
        version = database._connection.execute("PRAGMA user_version").fetchone()[0]
        assert int(version) == SCHEMA_VERSION

        assert database.load_settings()["theme"] == "dark"

        records = database.load_downloads()
        assert len(records) == 1
        record = records[0]
        assert record["id"] == "legacy-1"
        assert record["status"] == "Completed"
        assert record["connections"] == 4
        assert record["speed_limit_kbps"] == 0
        assert record["etag"] == ""
        assert record["last_modified"] == ""
        assert record["retry_count"] == 0
        assert record["source_browser"] == ""
        assert record["referrer"] == ""

        assert {"download_segments", "download_queue", "download_logs"}.issubset(
            _tables(database)
        )
        assert {
            "connections",
            "speed_limit_kbps",
            "etag",
            "last_modified",
            "retry_count",
            "source_browser",
            "referrer",
        }.issubset(_columns(database, "downloads"))

        # Settings now live in app_settings, and writes still round-trip.
        database.save_settings({"connections_per_download": 6})
        assert database.load_settings()["connections_per_download"] == 6
    finally:
        database.close()


def test_fresh_database_starts_at_current_version(tmp_path) -> None:
    database = Database(tmp_path / "fresh.sqlite3")
    try:
        version = database._connection.execute("PRAGMA user_version").fetchone()[0]
        assert int(version) == SCHEMA_VERSION
        assert database.load_settings() == {}
        assert database.load_downloads() == []
    finally:
        database.close()


def test_segment_queue_and_log_tables_round_trip(tmp_path) -> None:
    database = Database(tmp_path / "records.sqlite3")
    try:
        database.save_download(
            {
                "id": "dl-1",
                "url": "https://example.com/file.bin",
                "filename": "file.bin",
                "folder": str(tmp_path),
                "category": "Other",
                "priority": 1,
                "status": "Downloading",
                "total_bytes": 4 * 1024 * 1024,
                "downloaded_bytes": 1024,
                "speed": 0,
                "eta": None,
                "error": "",
                "content_type": "application/octet-stream",
                "range_supported": 1,
                "created_at": "2026-01-01T10:00:00",
                "completed_at": None,
                "last_try": None,
                "queue_seq": 1,
                "connections": 4,
                "speed_limit_kbps": 128,
                "etag": '"v1"',
                "last_modified": "Wed, 01 Jan 2026 10:00:00 GMT",
                "retry_count": 2,
            }
        )
        segments = [
            {"index": 0, "start": 0, "end": 1023, "downloaded": 512, "status": "active"},
            {"index": 1, "start": 1024, "end": 2047, "downloaded": 0, "status": "active"},
        ]
        database.replace_segments("dl-1", segments)
        stored = database.load_segments("dl-1")
        assert len(stored) == 2
        assert stored[0]["downloaded_bytes"] == 512
        assert stored[1]["start_byte"] == 1024

        database.replace_queue(
            [{"download_id": "dl-1", "state": "waiting", "priority": 1}]
        )
        queue = database.load_queue()
        assert queue[0]["download_id"] == "dl-1"
        assert queue[0]["position"] == 0

        database.add_download_log("dl-1", "info", "Segment 1 started")
        logs = database.load_download_logs("dl-1")
        assert logs[0]["message"] == "Segment 1 started"

        # Removing the download cascades to segments and queue rows.
        database.delete_download("dl-1")
        assert database.load_segments("dl-1") == []
        assert database.load_queue() == []
    finally:
        database.close()


def test_records_without_browser_metadata_use_schema_defaults(tmp_path) -> None:
    database = Database(tmp_path / "compat.sqlite3")
    try:
        record = {
            "id": "dl-legacy",
            "url": "https://example.com/file.bin",
            "filename": "file.bin",
            "folder": str(tmp_path),
            "category": "Other",
            "priority": 1,
            "status": "Paused",
            "total_bytes": None,
            "downloaded_bytes": 0,
            "speed": 0,
            "eta": None,
            "error": "",
            "content_type": "",
            "range_supported": None,
            "created_at": "2026-01-01T10:00:00",
            "completed_at": None,
            "last_try": None,
            "queue_seq": 0,
            "connections": 4,
            "speed_limit_kbps": 0,
            "etag": "",
            "last_modified": "",
            "retry_count": 0,
        }
        database.save_download(record)
        stored = database.load_downloads()[0]
        assert stored["source_browser"] == ""
        assert stored["referrer"] == ""

        # Browser metadata survives a round trip.
        record["source_browser"] = "chrome"
        record["referrer"] = "https://example.com/page"
        database.save_download(record)
        stored = database.load_downloads()[0]
        assert stored["source_browser"] == "chrome"
        assert stored["referrer"] == "https://example.com/page"
    finally:
        database.close()


def _create_v3_database(path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_SCHEMA_V1)
        connection.executescript(_SCHEMA_V2)
        for name, declaration in _V2_DOWNLOAD_COLUMNS + _V3_DOWNLOAD_COLUMNS:
            connection.execute(
                f"ALTER TABLE downloads ADD COLUMN {name} {declaration}"
            )
        connection.execute(
            "INSERT INTO app_settings (key, value, kind) VALUES (?, ?, ?)",
            ("theme", '"dark"', "json"),
        )
        connection.execute(_LEGACY_DOWNLOAD_SQL)
        connection.execute("PRAGMA user_version = 3")
        connection.commit()
    finally:
        connection.close()


def _create_v4_database(path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_SCHEMA_V1)
        connection.executescript(_SCHEMA_V2)
        for name, declaration in (
            _V2_DOWNLOAD_COLUMNS + _V3_DOWNLOAD_COLUMNS + _V4_DOWNLOAD_COLUMNS
        ):
            connection.execute(
                f"ALTER TABLE downloads ADD COLUMN {name} {declaration}"
            )
        connection.executescript(_SCHEMA_V4)
        connection.execute(
            "INSERT INTO app_settings (key, value, kind) VALUES (?, ?, ?)",
            ("theme", '"dark"', "json"),
        )
        connection.execute(_LEGACY_DOWNLOAD_SQL)
        connection.execute("PRAGMA user_version = 4")
        connection.commit()
    finally:
        connection.close()


def test_v3_database_migrates_to_current_version_with_verified_backup(tmp_path) -> None:
    path = tmp_path / "v3.sqlite3"
    _create_v3_database(path)

    database = Database(path)
    try:
        assert SCHEMA_VERSION == 5
        version = database._connection.execute("PRAGMA user_version").fetchone()[0]
        assert int(version) == 5

        backup = database.migration_backup_path
        assert backup is not None and backup.is_file()
        assert backup.parent == tmp_path / "backups"
        check = sqlite3.connect(str(backup))
        try:
            assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert check.execute("PRAGMA user_version").fetchone()[0] == 3
            assert check.execute("SELECT COUNT(*) FROM downloads").fetchone()[0] == 1
        finally:
            check.close()

        record = database.load_downloads()[0]
        assert record["id"] == "legacy-1"
        assert record["media_kind"] == ""
        assert record["checksum_status"] == "not-requested"
        assert record["description"] == ""
        assert record["start_later"] == 0
        assert database.load_settings()["theme"] == "dark"
        assert {"media_metadata", "notifications", "download_events"}.issubset(
            _tables(database)
        )
        assert {
            "media_kind",
            "source_domain",
            "expected_sha256",
            "checksum_status",
            "description",
            "start_later",
        }.issubset(_columns(database, "downloads"))
    finally:
        database.close()


def test_v4_database_migrates_to_v5_and_keeps_media_data(tmp_path) -> None:
    path = tmp_path / "v4.sqlite3"
    _create_v4_database(path)

    database = Database(path)
    try:
        assert SCHEMA_VERSION == 5
        assert (
            int(database._connection.execute("PRAGMA user_version").fetchone()[0])
            == 5
        )

        backup = database.migration_backup_path
        assert backup is not None and backup.is_file()
        check = sqlite3.connect(str(backup))
        try:
            assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert check.execute("PRAGMA user_version").fetchone()[0] == 4
            assert check.execute("SELECT COUNT(*) FROM downloads").fetchone()[0] == 1
        finally:
            check.close()

        record = database.load_downloads()[0]
        assert record["id"] == "legacy-1"
        assert record["media_kind"] == ""
        assert record["checksum_status"] == "not-requested"
        assert record["description"] == ""
        assert record["start_later"] == 0
        assert database.load_settings()["theme"] == "dark"
        assert {"description", "start_later"}.issubset(
            _columns(database, "downloads")
        )
    finally:
        database.close()


def test_media_metadata_notifications_and_events_round_trip(tmp_path) -> None:
    database = Database(tmp_path / "media.sqlite3")
    try:
        record = {
            "id": "video-1",
            "url": "https://cdn.example.com/clip.mp4",
            "filename": "clip.mp4",
            "folder": str(tmp_path),
            "category": "Videos",
            "priority": 1,
            "status": "Completed",
            "total_bytes": 2048,
            "downloaded_bytes": 2048,
            "speed": 0,
            "eta": None,
            "error": "",
            "content_type": "video/mp4",
            "range_supported": 1,
            "created_at": "2026-01-01T10:00:00",
            "completed_at": "2026-01-01T10:01:00",
            "last_try": None,
            "queue_seq": 0,
            "connections": 4,
            "speed_limit_kbps": 0,
            "etag": "",
            "last_modified": "",
            "retry_count": 0,
            "media_kind": "video",
            "file_format": "mp4",
        }
        database.save_download(record)
        database.save_media_metadata(
            "video-1",
            {
                "media_kind": "video",
                "page_url": "https://example.com/watch",
                "page_title": "Example clip",
                "source_domain": "cdn.example.com",
                "quality_label": "720p",
                "duration_seconds": 42,
                "detected_by": "video-assistant",
            },
        )
        stored = database.load_media_metadata("video-1")
        assert stored["media_kind"] == "video"
        assert stored["quality_label"] == "720p"
        assert stored["duration_seconds"] == 42
        assert database.load_all_media_metadata()["video-1"]["page_title"] == "Example clip"

        notification_id = database.add_notification(
            "success", "Download complete", "clip.mp4", "video-1"
        )
        assert database.unread_notification_count() == 1
        database.mark_notification_read(notification_id)
        assert database.unread_notification_count() == 0
        assert database.load_notifications()[0]["read_at"]

        database.add_download_event("video-1", "completed", 2048)
        events = database.load_download_events()
        assert events[0]["event"] == "completed"
        assert events[0]["bytes"] == 2048
        summary = database.download_summary()
        assert summary["total"] == 1
        assert summary["completed"] == 1
        assert summary["completed_bytes"] == 2048

        database.delete_download("video-1")
        assert database.load_media_metadata("video-1") is None
        assert database.load_notifications()[0]["download_id"] == "video-1"
    finally:
        database.close()
