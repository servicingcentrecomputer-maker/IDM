"""Release manifest validation tests."""

from __future__ import annotations

import json

import pytest

from idm.updater.errors import ManifestError
from idm.updater.manifest_validator import UpdateManifest
from tests.update_helpers import DOWNLOAD_URL, TRUSTED_HOST, manifest_data

TRUSTED = (TRUSTED_HOST,)


def test_valid_manifest_is_normalized():
    data = manifest_data(
        release_date="2026-10-31T18:30:00Z",
        release_notes=["First", "Second"],
        sha256="A" * 64,
    )
    manifest = UpdateManifest.from_dict(data, TRUSTED)
    assert manifest.app_name == "IDM"
    assert manifest.channel == "stable"
    assert manifest.latest_version == "1.1.0"
    assert manifest.minimum_supported_version == "1.0.0"
    assert manifest.release_date == "2026-10-31"
    assert manifest.release_notes == "First\nSecond"
    assert manifest.sha256 == "a" * 64
    assert manifest.download_url == DOWNLOAD_URL
    assert manifest.mandatory is False
    assert manifest.latest > manifest.minimum_supported


def test_manifest_from_json_accepts_bom_and_text():
    text = "\ufeff" + json.dumps(manifest_data())
    manifest = UpdateManifest.from_json(text.encode("utf-8"), TRUSTED)
    assert manifest.latest_version == "1.1.0"
    manifest = UpdateManifest.from_json(text, TRUSTED)
    assert manifest.latest_version == "1.1.0"


def test_manifest_to_dict_round_trip():
    manifest = UpdateManifest.from_dict(manifest_data(), TRUSTED)
    again = UpdateManifest.from_dict(manifest.to_dict(), TRUSTED)
    assert again == manifest


def test_manifest_rejects_wrong_application():
    with pytest.raises(ManifestError, match="not IDM"):
        UpdateManifest.from_dict(manifest_data(app_name="OtherApp"), TRUSTED)


@pytest.mark.parametrize(
    "field", [key for key in manifest_data() if key != "release_notes"]
)
def test_manifest_requires_every_field(field):
    data = manifest_data()
    del data[field]
    with pytest.raises(ManifestError):
        UpdateManifest.from_dict(data, TRUSTED)


@pytest.mark.parametrize(
    "field,value",
    [
        ("latest_version", "1.0"),
        ("latest_version", "v1.1.0"),
        ("minimum_supported_version", "01.0.0"),
        ("latest_version", 110),
        ("mandatory", 0),
        ("mandatory", "false"),
        ("sha256", "abc"),
        ("sha256", "g" * 64),
        ("release_date", "31/10/2026"),
        ("channel", "nightly"),
        ("channel", "STABLE"),
        ("manifest_signature", 123),
    ],
)
def test_manifest_rejects_invalid_values(field, value):
    with pytest.raises(ManifestError):
        UpdateManifest.from_dict(manifest_data(**{field: value}), TRUSTED)


def test_minimum_cannot_exceed_latest():
    data = manifest_data(latest_version="1.0.0", minimum_supported_version="1.1.0")
    with pytest.raises(ManifestError, match="minimum_supported_version"):
        UpdateManifest.from_dict(data, TRUSTED)


@pytest.mark.parametrize(
    "url",
    [
        "http://updates.example.com/IDM_Setup.exe",
        "https:///IDM_Setup.exe",
        "https://user:pass@updates.example.com/IDM_Setup.exe",
        "https://updates.example.com/IDM_Setup.exe#fragment",
        "https://127.0.0.1/IDM_Setup.exe",
        "https://evil.example.com/IDM_Setup.exe",
        "https://updates.example.com/IDM_Setup.zip",
    ],
)
def test_manifest_rejects_unsafe_download_urls(url):
    with pytest.raises(ManifestError):
        UpdateManifest.from_dict(manifest_data(download_url=url), TRUSTED)


def test_manifest_rejects_too_long_download_url():
    url = "https://updates.example.com/" + "a" * 2100 + ".exe"
    with pytest.raises(ManifestError):
        UpdateManifest.from_dict(manifest_data(download_url=url), TRUSTED)


def test_manifest_requires_notes_to_be_text():
    with pytest.raises(ManifestError):
        UpdateManifest.from_dict(
            manifest_data(release_notes={"text": "not a list"}), TRUSTED
        )


def test_manifest_rejects_oversized_notes():
    with pytest.raises(ManifestError):
        UpdateManifest.from_dict(
            manifest_data(release_notes="x" * 20_001), TRUSTED
        )


def test_manifest_strips_null_characters_from_notes():
    manifest = UpdateManifest.from_dict(
        manifest_data(release_notes="one\x00two"), TRUSTED
    )
    assert manifest.release_notes == "onetwo"


def test_manifest_allows_missing_notes():
    data = manifest_data()
    del data["release_notes"]
    assert UpdateManifest.from_dict(data, TRUSTED).release_notes == ""


def test_manifest_rejects_invalid_json():
    with pytest.raises(ManifestError, match="not valid JSON"):
        UpdateManifest.from_json("{not json", TRUSTED)


def test_manifest_rejects_non_object_json():
    with pytest.raises(ManifestError, match="JSON object"):
        UpdateManifest.from_json("[]", TRUSTED)


def test_manifest_rejects_invalid_utf8():
    with pytest.raises(ManifestError, match="UTF-8"):
        UpdateManifest.from_json(b"\xff\xfe{}", TRUSTED)


def test_manifest_rejects_unknown_fields():
    data = manifest_data()
    data["_comment"] = "not part of the schema"
    with pytest.raises(ManifestError, match="unsupported field"):
        UpdateManifest.from_dict(data, TRUSTED)


def test_manifest_rejects_duplicate_fields():
    text = '{"app_name": "IDM", "app_name": "IDM"}'
    with pytest.raises(ManifestError, match="duplicate"):
        UpdateManifest.from_json(text, TRUSTED)


def test_manifest_rejects_non_standard_json_constants():
    text = '{"mandatory": NaN}'
    with pytest.raises(ManifestError, match="unsupported JSON constant"):
        UpdateManifest.from_json(text, TRUSTED)


def test_manifest_signature_field_is_required():
    data = manifest_data()
    del data["manifest_signature"]
    with pytest.raises(ManifestError, match="manifest_signature"):
        UpdateManifest.from_dict(data, TRUSTED)


def test_beta_manifest_is_valid_but_channel_is_preserved():
    manifest = UpdateManifest.from_dict(manifest_data(channel="beta"), TRUSTED)
    assert manifest.channel == "beta"


def test_manifest_size_limit_applies_to_bytes_and_text():
    payload = json.dumps(manifest_data()).encode("utf-8")
    with pytest.raises(ManifestError, match="too large"):
        UpdateManifest.from_json(payload, TRUSTED, max_bytes=10)
    with pytest.raises(ManifestError, match="too large"):
        UpdateManifest.from_json(payload.decode("utf-8"), TRUSTED, max_bytes=10)
