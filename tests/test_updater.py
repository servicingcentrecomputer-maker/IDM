"""Handoff, staging, updater process and install-argument tests."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from idm.updater import launcher
from idm.updater.errors import UpdaterError
from idm.updater.handoff import (
    COMPLETION_MARKER,
    UpdateHandoff,
    has_completion_marker,
    read_handoff,
    safe_remove_update_dir,
    write_completion_marker,
    write_handoff,
)
from idm.updater.launcher import (
    InstallRequest,
    cleanup_stale_update_directories,
    create_update_directory,
    stage_and_launch,
    stage_updater,
    updater_executable,
)
from idm.updater.package_verifier import SignatureInfo
from idm.updater.state import read_install_result
from idm.updater.updater import (
    _installer_error_text,
    installer_arguments,
    machine_wide_install,
    main,
    run_update,
)
from idm.version import CURRENT_VERSION
from tests.update_helpers import sha256_bytes

PAYLOAD = b"MZ" + b"installer payload" * 64


def _signed(_path):
    return SignatureInfo(
        status="Valid", subject="CN=IDM, O=Example", simple_name="IDM"
    )


@pytest.fixture
def update_dir():
    directory = Path(tempfile.mkdtemp(prefix="IDM-Update-"))
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def handoff(update_dir, tmp_path):
    installer = update_dir / "IDM_Setup_1.1.0.exe"
    installer.write_bytes(PAYLOAD)
    return UpdateHandoff(
        installer=installer,
        sha256=sha256_bytes(PAYLOAD),
        publisher="IDM",
        parent_pid=os.getpid(),
        app_exe=Path(sys.executable),
        target_version="1.1.0",
        restart=True,
        update_dir=update_dir,
        log_file=tmp_path / "logs" / "updater.log",
    )


def _run(handoff, **overrides):
    values = {
        "signature_runner": _signed,
        "wait_for_parent": lambda *_args: True,
        "installer_runner": lambda _cmd: 0,
        "restart_app": lambda _exe: None,
        "cleanup": lambda _path: True,
        "notify": lambda *_args, **_kwargs: None,
        "result_writer": lambda *_args, **_kwargs: None,
    }
    values.update(overrides)
    return run_update(handoff, **values)


# ------------------------------------------------------------------ handoff


def test_handoff_round_trip(handoff, update_dir):
    path = update_dir / "update-handoff.json"
    write_handoff(path, handoff)
    loaded = read_handoff(path)
    assert loaded == handoff
    assert loaded.app_dir == handoff.app_exe.parent


def test_handoff_rejects_installer_outside_update_dir(handoff, tmp_path):
    outside = tmp_path / "IDM_Setup.exe"
    outside.write_bytes(PAYLOAD)
    with pytest.raises(UpdaterError, match="not inside"):
        write_handoff(
            handoff.update_dir / "update-handoff.json",
            replace(handoff, installer=outside),
        )


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"sha256": "abc"}, "SHA-256"),
        ({"target_version": "1.0"}, "target version"),
        ({"installer": Path("relative.exe")}, "absolute"),
        ({"update_dir": Path("relative")}, "absolute"),
    ],
)
def test_handoff_validation_rejects_bad_values(handoff, changes, match):
    with pytest.raises(UpdaterError, match=match):
        write_handoff(
            handoff.update_dir / "update-handoff.json",
            replace(handoff, **changes),
        )


def test_handoff_accepts_sha256_only_trust(handoff, update_dir):
    path = update_dir / "update-handoff.json"
    write_handoff(path, replace(handoff, publisher=""))
    assert read_handoff(path).publisher == ""


def test_handoff_round_trip_preserves_reinstall(handoff, update_dir):
    path = update_dir / "update-handoff.json"
    write_handoff(path, replace(handoff, reinstall=True))
    assert read_handoff(path).reinstall is True


def test_read_handoff_rejects_missing_file(tmp_path):
    with pytest.raises(UpdaterError, match="missing"):
        read_handoff(tmp_path / "missing.json")


def test_read_handoff_rejects_invalid_json(update_dir):
    path = update_dir / "update-handoff.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(UpdaterError, match="not valid JSON"):
        read_handoff(path)


def test_read_handoff_rejects_unknown_schema(handoff, update_dir):
    path = update_dir / "update-handoff.json"
    write_handoff(path, handoff)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(UpdaterError, match="schema"):
        read_handoff(path)


def test_read_handoff_rejects_oversized_file(update_dir):
    path = update_dir / "update-handoff.json"
    path.write_text("x" * 70000, encoding="utf-8")
    with pytest.raises(UpdaterError, match="large"):
        read_handoff(path)


def test_completion_marker(update_dir):
    assert not has_completion_marker(update_dir)
    marker = write_completion_marker(update_dir, "1.1.0")
    assert marker is not None
    assert marker.name == COMPLETION_MARKER
    assert has_completion_marker(update_dir)
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["target_version"] == "1.1.0"


def test_safe_remove_update_dir_only_removes_our_temp_folders(tmp_path, monkeypatch):
    temp_root = tmp_path / "temp-root"
    temp_root.mkdir()
    monkeypatch.setattr(
        "idm.updater.handoff.tempfile.gettempdir", lambda: str(temp_root)
    )

    ours = temp_root / "IDM-Update-abc"
    ours.mkdir()
    (ours / "file.txt").write_text("x", encoding="utf-8")
    assert safe_remove_update_dir(ours)
    assert not ours.exists()

    unrelated = temp_root / "user-folder"
    unrelated.mkdir()
    assert not safe_remove_update_dir(unrelated)
    assert unrelated.exists()

    outside_root = tmp_path / "elsewhere"
    outside_root.mkdir()
    outside = outside_root / "IDM-Update-xyz"
    outside.mkdir()
    assert not safe_remove_update_dir(outside)
    assert outside.exists()


def test_cleanup_stale_update_directories(tmp_path, monkeypatch):
    temp_root = tmp_path / "temp-root"
    temp_root.mkdir()
    monkeypatch.setattr(
        "idm.updater.handoff.tempfile.gettempdir", lambda: str(temp_root)
    )
    monkeypatch.setattr(
        "idm.updater.launcher.tempfile.gettempdir", lambda: str(temp_root)
    )

    marked = temp_root / "IDM-Update-marked"
    marked.mkdir()
    write_completion_marker(marked, "1.1.0")

    old = temp_root / "IDM-Update-old"
    old.mkdir()
    stale = 10_000
    os.utime(old, (stale, stale))

    fresh = temp_root / "IDM-Update-fresh"
    fresh.mkdir()

    unrelated = temp_root / "IDM-Other"
    unrelated.mkdir()

    removed = cleanup_stale_update_directories(max_age_seconds=60)
    assert removed == 2
    assert not marked.exists()
    assert not old.exists()
    assert fresh.exists()
    assert unrelated.exists()


def test_create_update_directory_uses_prefix(tmp_path):
    directory = create_update_directory(tmp_path)
    try:
        assert directory.is_dir()
        assert directory.name.startswith("IDM-Update-")
        assert directory.parent == tmp_path
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_stage_updater_copies_component(tmp_path):
    updater = tmp_path / "IDM_Updater.exe"
    updater.write_bytes(b"updater-binary")
    update_dir = tmp_path / "update"
    staging = stage_updater(updater, update_dir)
    assert staging.name == "IDM_Updater.exe"
    assert staging.read_bytes() == b"updater-binary"


def test_stage_updater_requires_source(tmp_path):
    with pytest.raises(UpdaterError, match="missing"):
        stage_updater(tmp_path / "missing.exe", tmp_path / "update")


def test_stage_and_launch_writes_handoff_and_launches_staged_updater(
    handoff, monkeypatch
):
    updater = handoff.update_dir / "source" / "IDM_Updater.exe"
    updater.parent.mkdir()
    updater.write_bytes(b"updater")
    launched: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        launcher,
        "launch_updater",
        lambda staged, path: launched.append((staged, path)) or 1234,
    )
    request = InstallRequest(
        installer=handoff.installer,
        sha256=handoff.sha256,
        publisher=handoff.publisher,
        target_version=handoff.target_version,
        update_dir=handoff.update_dir,
        restart=True,
    )
    result = stage_and_launch(
        request, updater, handoff.app_exe, handoff.log_file
    )
    assert result == handoff
    staged, handoff_path = launched[0]
    assert staged == handoff.update_dir / "IDM_Updater.exe"
    assert staged.is_file()
    assert read_handoff(handoff_path) == handoff


def test_updater_executable_env_override(tmp_path, monkeypatch):
    updater = tmp_path / "IDM_Updater.exe"
    updater.write_bytes(b"binary")
    monkeypatch.setenv(launcher.ENV_UPDATER_EXE, str(updater))
    assert updater_executable() == updater
    monkeypatch.setenv(launcher.ENV_UPDATER_EXE, str(tmp_path / "missing.exe"))
    assert updater_executable() is None


def test_updater_executable_requires_frozen_build(monkeypatch):
    monkeypatch.delenv(launcher.ENV_UPDATER_EXE, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert updater_executable() is None


def test_updater_version_flag(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == CURRENT_VERSION


def test_updater_requires_handoff_without_version_flag():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


# ------------------------------------------------------------------ run_update


def test_run_update_success_restarts(handoff):
    commands = []
    restarted = []
    notified = []
    result = _run(
        handoff,
        installer_runner=lambda command: commands.append(command) or 0,
        restart_app=lambda exe: restarted.append(exe),
        notify=lambda *_args, **_kwargs: notified.append(True),
    )
    assert result == 0
    assert commands[0][0] == str(handoff.installer)
    assert restarted == [handoff.app_exe]
    assert notified == []


def test_run_update_success_without_restart_notifies(handoff):
    restarted = []
    notified = []
    result = _run(
        replace(handoff, restart=False),
        restart_app=lambda exe: restarted.append(exe),
        notify=lambda title, message, error: notified.append((title, message, error)),
    )
    assert result == 0
    assert restarted == []
    assert notified and notified[0][2] is False
    assert "1.1.0" in notified[0][1]


def test_run_update_waits_for_idm_to_close(handoff):
    called = []
    result = _run(
        handoff,
        wait_for_parent=lambda *_args: False,
        installer_runner=lambda command: called.append(command) or 0,
    )
    assert result == 3
    assert called == []


def test_run_update_installs_sha256_only_package(handoff):
    commands = []
    signature_calls = []
    result = _run(
        replace(handoff, publisher=""),
        signature_runner=lambda path: signature_calls.append(path),
        installer_runner=lambda command: commands.append(command) or 0,
    )
    assert result == 0
    assert len(commands) == 1
    assert signature_calls == []


def test_run_update_refuses_invalid_signature(handoff):
    called = []
    cleaned = []
    result = _run(
        handoff,
        signature_runner=lambda _path: SignatureInfo(status="NotSigned"),
        installer_runner=lambda command: called.append(command) or 0,
        cleanup=lambda path: cleaned.append(path) or True,
    )
    assert result == 4
    assert called == []
    assert cleaned == []


def test_run_update_reports_cancelled_installer(handoff):
    restarted = []
    notified = []
    result = _run(
        handoff,
        installer_runner=lambda _command: 1223,
        restart_app=lambda exe: restarted.append(exe),
        notify=lambda _title, message, error: notified.append((message, error)),
    )
    assert result == 5
    assert restarted == [handoff.app_exe]
    assert notified and "cancelled" in notified[0][0].lower()


def test_run_update_marks_directory_when_cleanup_is_blocked(handoff):
    result = _run(handoff, cleanup=lambda _path: False)
    assert result == 0
    assert has_completion_marker(handoff.update_dir)


def test_run_update_records_reinstall_success(handoff, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    result = run_update(
        replace(handoff, reinstall=True),
        signature_runner=_signed,
        wait_for_parent=lambda *_args: True,
        installer_runner=lambda _command: 0,
        restart_app=lambda _exe: None,
        cleanup=lambda _path: True,
        notify=lambda *_args, **_kwargs: None,
    )
    assert result == 0
    receipt = read_install_result()
    assert receipt is not None
    assert receipt.reinstall is True
    assert receipt.success is True
    assert receipt.target_version == "1.1.0"


def test_run_update_records_cancelled_installer_result(handoff, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    result = run_update(
        replace(handoff, reinstall=True),
        signature_runner=_signed,
        wait_for_parent=lambda *_args: True,
        installer_runner=lambda _command: 1223,
        restart_app=lambda _exe: None,
        cleanup=lambda _path: True,
        notify=lambda *_args, **_kwargs: None,
    )
    assert result == 5
    receipt = read_install_result()
    assert receipt is not None
    assert receipt.success is False
    assert receipt.exit_code == 1223
    assert receipt.reinstall is True


def test_installer_arguments_for_user_install(handoff):
    args = installer_arguments(handoff.app_exe, handoff.update_dir / "install.log")
    assert "/ALLUSERS" not in args
    assert "/SILENT" in args
    assert "/CLOSEAPPLICATIONS" in args
    assert any(arg.startswith("/LOG=") for arg in args)


def test_installer_arguments_for_machine_install(tmp_path, monkeypatch):
    program_files = tmp_path / "ProgramFiles"
    program_files.mkdir()
    app_exe = program_files / "IDM" / "IDM.exe"
    app_exe.parent.mkdir()
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("ProgramW6432", str(program_files))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert machine_wide_install(app_exe)
    args = installer_arguments(app_exe, tmp_path / "install.log")
    assert args[0] == "/ALLUSERS"


def test_installer_error_text():
    assert "cancelled" in _installer_error_text(1223).lower()
    assert "cancelled" in _installer_error_text(1602).lower()
    assert "cancelled" in _installer_error_text(5).lower()
    assert "error code 7" in _installer_error_text(7)
