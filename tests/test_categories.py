"""Category detection, validation and remembered-folder policy tests."""

from __future__ import annotations

from idm.constants import (
    CATEGORIES,
    CATEGORY_COMPRESSED,
    CATEGORY_DOCUMENTS,
    CATEGORY_GENERAL,
    CATEGORY_IMAGES,
    CATEGORY_MUSIC,
    CATEGORY_OTHER,
    CATEGORY_PROGRAMS,
    CATEGORY_VIDEOS,
)
from idm.core.categories import (
    MAX_CUSTOM_CATEGORIES,
    category_for_extension,
    category_for_mime,
    category_names,
    describe_file_type,
    detect_category,
    ensure_filename_extension,
    normalize_category_name,
    normalize_category_paths,
    normalize_custom_categories,
    normalize_extensions,
    safe_category,
)
from idm.core.settings import AppSettings


def test_builtin_categories_cover_the_documented_set() -> None:
    assert CATEGORIES == (
        CATEGORY_GENERAL,
        CATEGORY_COMPRESSED,
        CATEGORY_DOCUMENTS,
        CATEGORY_MUSIC,
        CATEGORY_VIDEOS,
        CATEGORY_PROGRAMS,
        CATEGORY_IMAGES,
        CATEGORY_OTHER,
    )


def test_detection_prefers_extension_then_mime() -> None:
    assert detect_category("setup.exe") == CATEGORY_PROGRAMS
    assert detect_category("report.PDF") == CATEGORY_DOCUMENTS
    assert detect_category("song.flac") == CATEGORY_MUSIC
    assert detect_category("movie.mkv") == CATEGORY_VIDEOS
    assert detect_category("photo.webp") == CATEGORY_IMAGES
    assert detect_category("bundle.7z") == CATEGORY_COMPRESSED

    assert detect_category("download", "video/mp4") == CATEGORY_VIDEOS
    assert detect_category("download", "audio/mpeg") == CATEGORY_MUSIC
    assert detect_category("download", "application/pdf") == CATEGORY_DOCUMENTS
    assert detect_category("download", "application/zip") == CATEGORY_COMPRESSED
    assert detect_category("download", "image/avif") == CATEGORY_IMAGES
    assert (
        detect_category("download", "application/vnd.microsoft.portable-executable")
        == CATEGORY_PROGRAMS
    )


def test_detection_falls_back_to_general_without_evidence() -> None:
    assert detect_category("") == CATEGORY_GENERAL
    assert detect_category("unknown.zzz") == CATEGORY_GENERAL
    assert detect_category("download", "application/octet-stream") == CATEGORY_GENERAL
    assert category_for_mime("not-a-mime") is None
    assert category_for_extension("") is None


def test_custom_categories_win_over_builtin_extensions() -> None:
    custom = [{"name": "Books", "extensions": ["cbz"]}, {"name": "Raw", "extensions": ["cr2"]}]
    assert detect_category("novel.cbz", custom=custom) == "Books"
    assert detect_category("shot.cr2", custom=custom) == "Raw"
    assert detect_category("manual.pdf", custom=custom) == CATEGORY_DOCUMENTS
    assert category_names(custom)[-1] == "Raw"


def test_custom_categories_are_sanitised() -> None:
    values = [
        {"name": "Books", "extensions": [".EPUB", "epub", "../bad", "zip", "pdf"]},
        {"name": "books", "extensions": ["txt"]},
        {"name": "Documents", "extensions": ["rtf"]},
        {"name": "<script>", "extensions": ["js"]},
        {"name": "Bad", "extensions": "not-a-list"},
    ]
    cleaned = normalize_custom_categories(values)
    assert cleaned == [{"name": "script", "extensions": ["js"]}]


def test_custom_category_limits_are_enforced() -> None:
    entries = [
        {"name": f"Custom {index}", "extensions": [f"ext{index}"]}
        for index in range(MAX_CUSTOM_CATEGORIES + 5)
    ]
    assert len(normalize_custom_categories(entries)) == MAX_CUSTOM_CATEGORIES
    many = [f"e{index}" for index in range(100)]
    assert len(normalize_extensions(many)) == 64


def test_category_name_validation() -> None:
    assert normalize_category_name("  My   Files  ") == "My Files"
    assert normalize_category_name('Bad<>:"/\\|?*Name') == "BadName"
    assert normalize_category_name("") == ""
    assert normalize_category_name("x" * 33) == ""
    assert normalize_category_name("../escape") == "escape"


def test_safe_category_only_returns_known_names() -> None:
    custom = [{"name": "Books", "extensions": ["epub"]}]
    assert safe_category("books", custom) == "Books"
    assert safe_category("unknown") == CATEGORY_GENERAL
    assert safe_category("") == CATEGORY_GENERAL
    assert safe_category(CATEGORY_IMAGES) == CATEGORY_IMAGES


def test_file_type_and_extension_helpers() -> None:
    assert describe_file_type("a.pdf") == "PDF document"
    assert describe_file_type("a.zzz", "image/png") == "PNG image"
    assert describe_file_type("a.zzz", "application/octet-stream") == "Binary file"
    assert describe_file_type("a.zzz") == "ZZZ file"
    assert describe_file_type("", "") == "File"
    assert ensure_filename_extension("report", "application/pdf") == "report.pdf"
    assert ensure_filename_extension("report.pdf", "application/pdf") == "report.pdf"
    assert ensure_filename_extension("report", "application/octet-stream") == "report"


def test_remembered_folders_round_trip_and_filter(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    try:
        documents = tmp_path / "Docs"
        music = tmp_path / "Music"
        documents.mkdir()
        music.mkdir()
        settings.update(
            {
                "custom_categories": [
                    {"name": "Books", "extensions": ["cbz"]},
                ]
            }
        )
        settings.remember_category_folder("Documents", str(documents))
        settings.remember_category_folder("Books", str(music))
        assert settings.remembered_folder("Documents") == str(documents)
        assert settings.remembered_folder("Books") == str(music)

        settings.save()
        settings.close()

        restored = AppSettings()
        try:
            assert restored.remembered_folder("Documents") == str(documents)
            assert restored.remembered_folder("Books") == str(music)
            restored.forget_category_folder("Books")
            assert restored.remembered_folder("Books") == ""
        finally:
            restored.close()
    finally:
        try:
            settings.close()
        except Exception:
            pass


def test_remembered_folder_normalisation_drops_unknown_categories() -> None:
    paths = normalize_category_paths(
        {
            "Documents": r"C:\Downloads\Docs",
            "Unknown": r"C:\Downloads\Other",
            "Music": "",
        }
    )
    assert paths == {"Documents": r"C:\Downloads\Docs"}
    assert normalize_category_paths("not-a-mapping") == {}


def test_restored_records_without_a_category_use_the_general_bucket() -> None:
    from idm.engine.manager import _item_from_record

    item = _item_from_record(
        {
            "url": "https://example.com/mystery",
            "filename": "mystery",
            "folder": "C:/Downloads",
        }
    )
    assert item is not None
    assert item.category == CATEGORY_GENERAL


def test_every_builtin_category_has_a_navigation_entry() -> None:
    from idm.constants import CATEGORY_FILTER_KEYS
    from idm.ui.sidebar import _LIBRARY_ITEMS

    assert {key for key, _title, _icon in _LIBRARY_ITEMS} == set(CATEGORY_FILTER_KEYS)


def test_detection_and_restoration_agree_on_the_fallback_bucket() -> None:
    from idm.engine.manager import _item_from_record

    detected = detect_category("mystery")
    restored = _item_from_record(
        {
            "url": "https://example.com/mystery",
            "filename": "mystery",
            "folder": "C:/Downloads",
            "category": "",
        }
    )
    assert restored is not None
    assert restored.category == detected
