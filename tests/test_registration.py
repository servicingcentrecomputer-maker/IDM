"""Native messaging registration with an in-memory registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations import NATIVE_HOST_NAME, registration
from integrations.browser_registry import (
    CHROME_EXTENSION_ID,
    FIREFOX_EXTENSION_ID,
    NATIVE_HOST_NAME as REGISTRY_HOST_NAME,
    native_manifest,
)


class _FakeKey:
    def __init__(self, store: "_FakeWinreg", key: tuple[str, int]) -> None:
        self._store = store
        self.key = key

    def __enter__(self) -> "_FakeKey":
        return self

    def __exit__(self, *_args) -> bool:
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 0x20019
    KEY_SET_VALUE = 0x0002
    REG_SZ = 1
    KEY_WOW64_64KEY = 0x0100
    KEY_WOW64_32KEY = 0x0200

    def __init__(self) -> None:
        self.keys: set[tuple[str, int]] = set()
        self.values: dict[tuple[str, int], str] = {}

    @classmethod
    def view(cls, access: int) -> int:
        if access & cls.KEY_WOW64_32KEY:
            return cls.KEY_WOW64_32KEY
        return cls.KEY_WOW64_64KEY

    def OpenKey(self, _root, subkey, _reserved=0, access=0):
        key = (subkey, self.view(access))
        if key not in self.keys:
            raise FileNotFoundError(subkey)
        return _FakeKey(self, key)

    def CreateKeyEx(self, _root, subkey, _reserved=0, access=0):
        key = (subkey, self.view(access))
        self.keys.add(key)
        return _FakeKey(self, key)

    def QueryValueEx(self, key: _FakeKey, name):
        if name != "":
            raise FileNotFoundError(name)
        value = self.values.get(key.key)
        if value is None:
            raise FileNotFoundError("")
        return value, self.REG_SZ

    def SetValueEx(self, key: _FakeKey, name, _reserved, _kind, value) -> None:
        assert name == ""
        self.values[key.key] = value

    def DeleteValue(self, key: _FakeKey, name) -> None:
        if name != "" or key.key not in self.values:
            raise FileNotFoundError(name)
        self.values.pop(key.key)

    def QueryInfoKey(self, key: _FakeKey):
        values = 1 if key.key in self.values else 0
        return 0, values, 0

    def DeleteKeyEx(self, _root, subkey, access=0, _reserved=0) -> None:
        key = (subkey, self.view(access))
        if key not in self.keys:
            raise FileNotFoundError(subkey)
        self.keys.discard(key)
        self.values.pop(key, None)


@pytest.fixture
def fake_registry(monkeypatch, tmp_path: Path) -> _FakeWinreg:
    fake = _FakeWinreg()
    manifest_dir = tmp_path / "native_messaging"
    manifest_dir.mkdir()
    monkeypatch.setattr(registration, "winreg", fake)
    monkeypatch.setattr(
        registration,
        "manifest_file",
        lambda browser: manifest_dir / f"com.idm.native.{browser}.json",
    )
    monkeypatch.setattr(registration, "native_manifest_dir", lambda: manifest_dir)
    return fake


@pytest.fixture
def host(tmp_path: Path) -> Path:
    path = tmp_path / "IDM_NativeHost.exe"
    path.write_bytes(b"host")
    return path


def test_registry_subkeys_match_browser_documentation() -> None:
    assert registration.registry_subkey("chrome") == (
        rf"Software\Google\Chrome\NativeMessagingHosts\{NATIVE_HOST_NAME}"
    )
    assert registration.registry_subkey("edge") == (
        rf"Software\Microsoft\Edge\NativeMessagingHosts\{NATIVE_HOST_NAME}"
    )
    assert registration.registry_subkey("firefox") == (
        rf"Software\Mozilla\NativeMessagingHosts\{NATIVE_HOST_NAME}"
    )
    with pytest.raises(registration.RegistrationError):
        registration.registry_subkey("safari")


def test_install_chrome_writes_manifest_and_both_registry_views(
    fake_registry, host
) -> None:
    assert REGISTRY_HOST_NAME == NATIVE_HOST_NAME

    result = registration.install_browser("chrome", host)
    assert result["ok"] is True
    assert result["registered_views"] == ["64", "32"]

    manifest_path = Path(result["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == NATIVE_HOST_NAME
    assert manifest["type"] == "stdio"
    assert Path(manifest["path"]) == host
    assert manifest["allowed_origins"] == [
        f"chrome-extension://{CHROME_EXTENSION_ID}/"
    ]

    for view in (fake_registry.KEY_WOW64_64KEY, fake_registry.KEY_WOW64_32KEY):
        key = (registration.registry_subkey("chrome"), view)
        assert fake_registry.values[key] == str(manifest_path)

    status = registration.browser_status("chrome")
    assert status["installed"] is True
    assert status["registered_views"] == ["64", "32"]
    assert status["problems"] == []
    assert Path(status["host"]) == host


def test_install_firefox_uses_allowed_extensions(fake_registry, host) -> None:
    result = registration.install_browser("firefox", host)
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["allowed_extensions"] == [FIREFOX_EXTENSION_ID]
    assert "allowed_origins" not in manifest


def test_install_rejects_a_missing_or_relative_host(fake_registry, tmp_path) -> None:
    with pytest.raises(registration.RegistrationError):
        registration.install_browser("chrome", tmp_path / "missing.exe")
    with pytest.raises(registration.RegistrationError):
        registration.install_browser("chrome", Path("relative.exe"))


def test_uninstall_removes_only_our_registration(fake_registry, host) -> None:
    result = registration.install_browser("chrome", host)
    manifest = Path(result["manifest"])
    assert manifest.is_file()

    removed = registration.uninstall_browser("chrome")
    assert removed["ok"] is True
    assert removed["removed_manifest"] is True
    assert not manifest.exists()
    assert fake_registry.keys == set()
    assert fake_registry.values == {}

    # Uninstalling again is harmless.
    assert registration.uninstall_browser("chrome")["ok"] is True


def test_uninstall_leaves_a_foreign_value_untouched(fake_registry, host) -> None:
    subkey = registration.registry_subkey("chrome")
    foreign = str(Path(host).parent / "somebody-else.json")
    fake_registry.keys.add((subkey, fake_registry.KEY_WOW64_64KEY))
    fake_registry.values[(subkey, fake_registry.KEY_WOW64_64KEY)] = foreign

    result = registration.uninstall_browser("chrome")
    assert result["ok"] is False
    assert any("different manifest" in warning for warning in result["warnings"])
    assert (
        fake_registry.values[(subkey, fake_registry.KEY_WOW64_64KEY)] == foreign
    )
    assert (subkey, fake_registry.KEY_WOW64_64KEY) in fake_registry.keys


def test_status_reports_missing_manifest(fake_registry, host) -> None:
    status = registration.browser_status("edge")
    assert status["installed"] is False
    assert status["manifest_exists"] is False
    assert any("does not exist" in problem for problem in status["problems"])

    registration.install_browser("edge", host)
    Path(registration.manifest_file("edge")).unlink()
    status = registration.browser_status("edge")
    assert status["installed"] is False
    assert status["manifest_exists"] is False


def test_status_reports_a_missing_host(fake_registry, host) -> None:
    registration.install_browser("chrome", host)
    host.unlink()
    status = registration.browser_status("chrome")
    assert status["installed"] is False
    assert any("missing" in problem for problem in status["problems"])


def test_install_and_uninstall_many(fake_registry, host) -> None:
    results = registration.install(["chrome", "edge", "firefox"], host)
    assert [result["browser"] for result in results] == ["chrome", "edge", "firefox"]
    assert all(result["ok"] for result in results)

    removed = registration.uninstall(["chrome", "edge", "firefox"])
    assert all(result["ok"] for result in removed)


def test_find_host_path_prefers_the_built_layout(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    root = tmp_path / "project"
    assert registration.find_host_path(root) is None

    built = root / "dist" / "IDM" / "IDM_NativeHost.exe"
    built.parent.mkdir(parents=True)
    built.write_bytes(b"host")
    assert registration.find_host_path(root) == built


def test_installed_layout_registration_is_detected_and_reused(
    fake_registry, tmp_path: Path, monkeypatch
) -> None:
    install = tmp_path / "Programs" / "IDM"
    host = install / "IDM_NativeHost.exe"
    host.parent.mkdir(parents=True)
    host.write_bytes(b"host")

    monkeypatch.setattr(registration, "installed_root", lambda: install)
    manifest_path = registration.installed_manifest_file("chrome")
    assert manifest_path is not None
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(native_manifest("chrome", host)), encoding="utf-8"
    )

    values = fake_registry.values
    key = (registration.registry_subkey("chrome"), fake_registry.KEY_WOW64_64KEY)
    fake_registry.keys.add(key)
    fake_registry.keys.add(
        (registration.registry_subkey("chrome"), fake_registry.KEY_WOW64_32KEY)
    )
    values[key] = str(manifest_path)
    values[(registration.registry_subkey("chrome"), fake_registry.KEY_WOW64_32KEY)] = (
        str(manifest_path)
    )

    status = registration.browser_status("chrome")
    assert status["installed"] is True
    assert Path(status["manifest"]) == manifest_path
    assert status["registered_views"] == ["64", "32"]
    assert status["problems"] == []

    result = registration.install_browser("chrome", host)
    assert Path(result["manifest"]) == manifest_path
    assert not registration.manifest_file("chrome").exists()

    removed = registration.uninstall_browser("chrome")
    assert removed["ok"] is True
    assert manifest_path.is_file()
    assert fake_registry.values == {}


def test_extension_dir_and_frozen_host_path(
    tmp_path: Path, monkeypatch
) -> None:
    install = tmp_path / "Programs" / "IDM"
    extension = install / "BrowserExtension" / "IDMVideoAssistant"
    extension.mkdir(parents=True)
    (extension / "manifest.json").write_text("{}", encoding="utf-8")
    host = install / "IDM_NativeHost.exe"
    host.write_bytes(b"host")
    monkeypatch.setattr(registration, "installed_root", lambda: install)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert registration.extension_dir() == extension
    assert registration.find_host_path(tmp_path / "project") == host


def test_dev_launcher_points_at_the_checkout(fake_registry, tmp_path) -> None:
    root = tmp_path / "project"
    script = root / "integrations" / "native_host.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('host')", encoding="utf-8")

    launcher = registration.create_dev_launcher(root, python=str(tmp_path / "python.exe"))
    text = launcher.read_text(encoding="utf-8")
    assert launcher.name == f"{NATIVE_HOST_NAME}.cmd"
    assert str(script) in text
    assert "@echo off" in text
