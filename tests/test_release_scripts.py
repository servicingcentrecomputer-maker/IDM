"""Release tooling tests: manifest validator and Ed25519 signing CLI."""

from __future__ import annotations

import json

import pytest

from scripts.sign_manifest import main as sign_main
from scripts.validate_manifest import main as validate_main
from tests.update_helpers import installer_bytes, manifest_data

pytest.importorskip("cryptography")


@pytest.fixture(autouse=True)
def _isolate_manifest_trust(monkeypatch):
    """Ignore a developer's production key when testing the unsigned path."""
    monkeypatch.setattr("config.MANIFEST_PUBLIC_KEY", "")
    monkeypatch.delenv("IDM_UPDATE_MANIFEST_PUBLIC_KEY", raising=False)


@pytest.fixture
def installer(tmp_path):
    path = tmp_path / "IDM_Setup_1.1.0.exe"
    path.write_bytes(installer_bytes())
    return path


@pytest.fixture
def manifest_file(tmp_path, installer):
    data = manifest_data(installer.read_bytes())
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_validate_accepts_matching_installer(monkeypatch, manifest_file, installer):
    monkeypatch.setenv("IDM_UPDATE_TRUSTED_HOSTS", "updates.example.com")
    rc = validate_main(
        [str(manifest_file), "--allow-unsigned", "--installer", str(installer)]
    )
    assert rc == 0


def test_validate_rejects_hash_mismatch(monkeypatch, tmp_path, installer):
    monkeypatch.setenv("IDM_UPDATE_TRUSTED_HOSTS", "updates.example.com")
    data = manifest_data(b"different installer")
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    rc = validate_main([str(path), "--allow-unsigned", "--installer", str(installer)])
    assert rc == 2


def test_validate_accepts_matching_package_size(monkeypatch, tmp_path, installer):
    monkeypatch.setenv("IDM_UPDATE_TRUSTED_HOSTS", "updates.example.com")
    data = manifest_data(
        installer.read_bytes(), package_size=installer.stat().st_size
    )
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    rc = validate_main(
        [str(path), "--allow-unsigned", "--installer", str(installer)]
    )
    assert rc == 0


def test_validate_rejects_package_size_mismatch(monkeypatch, tmp_path, installer):
    monkeypatch.setenv("IDM_UPDATE_TRUSTED_HOSTS", "updates.example.com")
    data = manifest_data(
        installer.read_bytes(), package_size=installer.stat().st_size + 1
    )
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    rc = validate_main(
        [str(path), "--allow-unsigned", "--installer", str(installer)]
    )
    assert rc == 2


def test_validate_requires_explicit_unsigned_opt_in(monkeypatch, manifest_file):
    monkeypatch.setenv("IDM_UPDATE_TRUSTED_HOSTS", "updates.example.com")
    assert validate_main([str(manifest_file)]) == 2


def test_validate_rejects_channel_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("IDM_UPDATE_TRUSTED_HOSTS", "updates.example.com")
    data = manifest_data(channel="beta")
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert validate_main([str(path), "--allow-unsigned", "--channel", "stable"]) == 2


def test_validate_rejects_unknown_field(monkeypatch, tmp_path):
    monkeypatch.setenv("IDM_UPDATE_TRUSTED_HOSTS", "updates.example.com")
    data = manifest_data()
    data["extra"] = True
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert validate_main([str(path), "--allow-unsigned"]) == 2


def test_keygen_sign_and_verify_round_trip(monkeypatch, tmp_path, manifest_file):
    monkeypatch.setenv("IDM_UPDATE_TRUSTED_HOSTS", "updates.example.com")
    private_key = tmp_path / "manifest.pem"
    public_key = tmp_path / "manifest.pub"

    assert sign_main(
        [
            "keygen",
            "--private-key",
            str(private_key),
            "--public-key",
            str(public_key),
        ]
    ) == 0
    assert private_key.is_file()
    public_text = public_key.read_text(encoding="ascii").strip()
    assert public_text

    assert sign_main(
        ["sign", "--manifest", str(manifest_file), "--private-key", str(private_key)]
    ) == 0
    signed = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert signed["manifest_signature"]

    assert sign_main(
        [
            "verify",
            "--manifest",
            str(manifest_file),
            "--public-key",
            public_text,
        ]
    ) == 0
    assert validate_main(
        [str(manifest_file), "--public-key", public_text]
    ) == 0


def test_keygen_refuses_to_overwrite(tmp_path):
    private_key = tmp_path / "manifest.pem"
    args = ["keygen", "--private-key", str(private_key)]
    assert sign_main(args) == 0
    assert sign_main(args) == 2


def test_sign_rejects_tampered_manifest(monkeypatch, tmp_path, manifest_file):
    monkeypatch.setenv("IDM_UPDATE_TRUSTED_HOSTS", "updates.example.com")
    private_key = tmp_path / "manifest.pem"
    sign_main(["keygen", "--private-key", str(private_key)])
    sign_main(
        ["sign", "--manifest", str(manifest_file), "--private-key", str(private_key)]
    )

    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    data["download_url"] = data["download_url"].replace("1.1.0", "9.9.9")
    manifest_file.write_text(json.dumps(data), encoding="utf-8")
    assert validate_main([str(manifest_file), "--public-key", _public_from(private_key)]) == 2


def _public_from(private_key_path) -> str:
    from cryptography.hazmat.primitives import serialization
    import base64

    key = serialization.load_pem_private_key(
        private_key_path.read_bytes(), password=None
    )
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")
