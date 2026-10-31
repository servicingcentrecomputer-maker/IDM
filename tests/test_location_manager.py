"""Download destination policy: modes, rules, validation and safety."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from downloads.location_manager import (
    MODE_ASK,
    MODE_DEFAULT,
    MODE_TYPE,
    DownloadLocationConfig,
    LocationError,
    LocationRule,
    WILDCARD,
    check_disk_space,
    default_rules_for,
    ensure_folder,
    environment_default_folder,
    is_within,
    normalize_extensions,
    resolve_destination,
    rule_category,
    safe_filename,
    safe_join,
    suggested_rules_for,
    validate_folder_path,
)

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="Download destination policy is Windows-specific"
)


def _missing(folder: Path) -> str:
    return str(folder.parent / f"{folder.name}-missing")


def test_validate_folder_path_normalises_valid_paths(tmp_path: Path) -> None:
    folder = tmp_path / "Downloads"
    assert validate_folder_path(f'  "{folder}"  ') == str(folder)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "relative\\folder",
        "D:relative",
        "C:\\folder\\..\\escape",
        "C:\\folder\x01bad",
    ],
)
def test_validate_folder_path_rejects_unsafe_paths(value: str) -> None:
    with pytest.raises(LocationError):
        validate_folder_path(value)


def test_validate_folder_path_rejects_reserved_names_and_files(tmp_path: Path) -> None:
    with pytest.raises(LocationError):
        validate_folder_path(str(tmp_path / "CON"))
    with pytest.raises(LocationError):
        validate_folder_path(str(tmp_path / "NUL" / "sub"))

    file_path = tmp_path / "already-a-file.txt"
    file_path.write_text("data", encoding="utf-8")
    with pytest.raises(LocationError):
        validate_folder_path(str(file_path))


def test_normalize_extensions_cleans_and_deduplicates() -> None:
    assert normalize_extensions(["ZIP", ".zip", " rar ", ""]) == ("zip", "rar")
    assert normalize_extensions(["*"]) == (WILDCARD,)
    with pytest.raises(LocationError):
        normalize_extensions(["bad extension"])
    with pytest.raises(LocationError):
        normalize_extensions(["a/b"])


def test_location_rule_round_trip_and_validation(tmp_path: Path) -> None:
    folder = str(tmp_path / "Archives")
    rule = LocationRule.from_dict({"folder": folder, "extensions": [".ZIP", "rar"]})
    assert rule.folder == folder
    assert rule.extensions == ("zip", "rar")
    assert LocationRule.from_dict(rule.to_dict()) == rule

    with pytest.raises(LocationError):
        LocationRule.from_dict({"folder": folder, "extensions": []})
    with pytest.raises(LocationError):
        LocationRule.from_dict({"folder": "relative", "extensions": ["zip"]})
    with pytest.raises(LocationError):
        LocationRule.from_dict(["not", "a", "mapping"])


def test_config_from_settings_skips_invalid_hand_edited_rules(tmp_path: Path) -> None:
    folder = str(tmp_path / "Archives")
    config = DownloadLocationConfig.from_settings(
        {
            "download_mode": "type",
            "download_type_rules": [
                {"folder": folder, "extensions": ["zip"]},
                {"folder": "relative", "extensions": ["rar"]},
                {"folder": folder, "extensions": []},
                "garbage",
            ],
        }
    )
    assert config.mode == MODE_TYPE
    assert len(config.rules) == 1
    assert config.to_settings()["download_type_rules"] == [
        {"folder": folder, "extensions": ["zip"]}
    ]


def test_config_unknown_mode_falls_back_to_default(tmp_path: Path) -> None:
    config = DownloadLocationConfig.from_settings({"download_mode": "nonsense"})
    assert config.mode == MODE_DEFAULT
    assert config.to_settings()["download_mode"] == MODE_DEFAULT


def test_config_validate_rejects_duplicate_extensions_and_wildcards(
    tmp_path: Path,
) -> None:
    first = LocationRule(str(tmp_path / "A"), ("zip",))
    second = LocationRule(str(tmp_path / "B"), ("zip",))
    with pytest.raises(LocationError):
        DownloadLocationConfig(MODE_TYPE, [first, second]).validate()

    wildcard_one = LocationRule(str(tmp_path / "A"), (WILDCARD,))
    wildcard_two = LocationRule(str(tmp_path / "B"), (WILDCARD,))
    with pytest.raises(LocationError):
        DownloadLocationConfig(MODE_TYPE, [wildcard_one, wildcard_two]).validate()

    DownloadLocationConfig(
        MODE_TYPE, [first, LocationRule(str(tmp_path / "B"), (WILDCARD,))]
    ).validate()


def test_folder_for_uses_rules_and_wildcard(tmp_path: Path) -> None:
    default_folder = str(tmp_path / "Downloads")
    archive_folder = str(tmp_path / "Archives")
    catch_all = str(tmp_path / "Other")
    config = DownloadLocationConfig(
        MODE_TYPE,
        [
            LocationRule(archive_folder, ("zip", "rar")),
            LocationRule(catch_all, (WILDCARD,)),
        ],
    )
    assert config.folder_for("file.zip", default_folder) == archive_folder
    assert config.folder_for("FILE.ZIP", default_folder) == archive_folder
    assert config.folder_for("movie.mkv", default_folder) == catch_all
    assert config.folder_for("no-extension", default_folder) == catch_all

    default_config = DownloadLocationConfig(MODE_DEFAULT, config.rules)
    assert default_config.folder_for("file.zip", default_folder) == default_folder


def test_ensure_folder_requires_approval_to_create(tmp_path: Path) -> None:
    missing = Path(_missing(tmp_path / "Downloads"))

    with pytest.raises(LocationError) as caught:
        ensure_folder(str(missing))
    assert caught.value.code == "folder_missing"
    assert not missing.exists()

    with pytest.raises(LocationError):
        ensure_folder(str(missing), approve_create=lambda _folder: False)
    assert not missing.exists()

    created: list[str] = []

    def approve(folder: str) -> bool:
        created.append(folder)
        return True

    assert ensure_folder(str(missing), approve_create=approve) == str(missing)
    assert missing.is_dir()
    assert created == [str(missing)]


def test_check_disk_space_uses_a_safety_margin(monkeypatch) -> None:
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _path: SimpleNamespace(free=100 * 1024 * 1024)
    )
    # 50 MiB plus a 2% margin fits.
    check_disk_space("C:\\Downloads", 50 * 1024 * 1024)

    with pytest.raises(LocationError) as caught:
        check_disk_space("C:\\Downloads", 100 * 1024 * 1024)
    assert caught.value.code == "insufficient_space"

    # Without a known size there is nothing to check.
    check_disk_space("C:\\Downloads", None)


def test_check_disk_space_reports_unreadable_volumes(monkeypatch) -> None:
    def explode(_path):
        raise OSError("denied")

    monkeypatch.setattr(shutil, "disk_usage", explode)
    with pytest.raises(LocationError) as caught:
        check_disk_space("C:\\Downloads", 1024)
    assert caught.value.code == "space_check_failed"


def test_safe_filename_and_join_block_traversal(tmp_path: Path) -> None:
    assert safe_filename(" report.pdf ") == "report.pdf"
    for bad in ("../escape.bin", "sub/dir.bin", "C:\\evil.bin", ""):
        with pytest.raises(LocationError):
            safe_filename(bad)
    # A name that sanitises to the fallback never escapes the folder.
    assert safe_filename("..") == "download"

    folder = tmp_path / "Downloads"
    folder.mkdir()
    joined = safe_join(str(folder), "report.pdf")
    assert joined == (folder / "report.pdf").resolve()

    with pytest.raises(LocationError):
        safe_join(str(folder), "..\\escape.bin")


def test_resolve_destination_modes(tmp_path: Path) -> None:
    default_folder = str(tmp_path / "Downloads")
    default_folder_path = Path(default_folder)
    default_folder_path.mkdir()

    folder, name = resolve_destination(
        DownloadLocationConfig(MODE_DEFAULT), "report.pdf", default_folder
    )
    assert folder == default_folder
    assert name == "report.pdf"

    archives = tmp_path / "Archives"
    config = DownloadLocationConfig(
        MODE_TYPE, [LocationRule(str(archives), ("zip",))]
    )
    folder, name = resolve_destination(
        config,
        "archive.zip",
        default_folder,
        approve_create=lambda _folder: True,
    )
    assert folder == str(archives)
    assert archives.is_dir()
    assert name == "archive.zip"

    asked = tmp_path / "Chosen"
    asked.mkdir()
    chosen: list[tuple[str, str]] = []

    def ask(name: str, suggested: str) -> str:
        chosen.append((name, suggested))
        return str(asked)

    folder, _ = resolve_destination(
        DownloadLocationConfig(MODE_ASK), "movie.mkv", default_folder, ask=ask
    )
    assert folder == str(asked)
    assert chosen == [("movie.mkv", default_folder)]

    with pytest.raises(LocationError) as caught:
        resolve_destination(
            DownloadLocationConfig(MODE_ASK),
            "movie.mkv",
            default_folder,
            ask=lambda _name, _suggested: None,
        )
    assert caught.value.code == "cancelled"

    with pytest.raises(LocationError) as caught:
        resolve_destination(
            DownloadLocationConfig(MODE_ASK), "movie.mkv", default_folder
        )
    assert caught.value.code == "ask_unavailable"


def test_resolve_destination_requires_approval_for_new_rule_folders(
    tmp_path: Path,
) -> None:
    default = tmp_path / "Downloads"
    default.mkdir()
    missing = Path(_missing(tmp_path / "Archives"))
    config = DownloadLocationConfig(
        MODE_TYPE, [LocationRule(str(missing), ("zip",))]
    )
    with pytest.raises(LocationError) as caught:
        resolve_destination(config, "archive.zip", str(default))
    assert caught.value.code == "folder_missing"

    folder, _ = resolve_destination(
        config,
        "archive.zip",
        str(default),
        approve_create=lambda _folder: True,
    )
    assert folder == str(missing)
    assert missing.is_dir()


def test_default_rules_cover_the_documented_categories(tmp_path: Path) -> None:
    rules = default_rules_for(str(tmp_path / "Downloads"))
    by_name = {Path(rule.folder).name: rule for rule in rules}
    assert set(by_name) == {"Archives", "Software", "Documents", "Media", "Images"}
    assert "zip" in by_name["Archives"].extensions
    assert "exe" in by_name["Software"].extensions
    assert "pdf" in by_name["Documents"].extensions
    assert "mp4" in by_name["Media"].extensions
    assert "png" in by_name["Images"].extensions
    assert rule_category(by_name["Media"]) == rule_category(
        LocationRule(str(tmp_path / "x"), ("mp4",))
    )


def test_suggested_rules_requires_an_extension(tmp_path: Path) -> None:
    rule = suggested_rules_for("report.PDF", str(tmp_path / "Documents"))
    assert rule.extensions == ("pdf",)
    with pytest.raises(LocationError):
        suggested_rules_for("README", str(tmp_path))


def test_is_within_and_environment_default(tmp_path: Path, monkeypatch) -> None:
    assert is_within(str(tmp_path / "a" / "b"), str(tmp_path))
    assert not is_within(str(tmp_path.parent), str(tmp_path))

    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    assert environment_default_folder() == str(
        tmp_path / "profile" / "Downloads"
    )
