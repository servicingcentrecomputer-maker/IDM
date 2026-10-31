"""SHA-256 and Authenticode verification tests (signature runner is faked)."""

from __future__ import annotations

import pytest

from idm.updater.errors import SignatureVerificationError
from idm.updater.package_verifier import (
    SignatureInfo,
    compute_sha256,
    parse_signature_output,
    publisher_matches,
    validate_installer_file,
    verify_authenticode,
    verify_installer,
)
from tests.update_helpers import sha256_bytes


def _write_exe(tmp_path, data: bytes = b"MZ" + b"\x00" * 128):
    path = tmp_path / "IDM_Setup_1.1.0.exe"
    path.write_bytes(data)
    return path


def _valid_runner(publisher: str = "IDM"):
    def runner(_path):
        return SignatureInfo(
            status="Valid",
            subject=f"CN={publisher}, O=Example",
            simple_name=publisher,
            thumbprint="ABC",
        )

    return runner


def test_compute_sha256(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"hello")
    assert compute_sha256(path) == sha256_bytes(b"hello")


def test_validate_installer_file_accepts_windows_executable(tmp_path):
    path = _write_exe(tmp_path)
    assert validate_installer_file(path) == path.stat().st_size


def test_validate_installer_file_rejects_missing_file(tmp_path):
    with pytest.raises(SignatureVerificationError, match="does not exist"):
        validate_installer_file(tmp_path / "missing.exe")


def test_validate_installer_file_rejects_wrong_extension(tmp_path):
    path = tmp_path / "setup.msi"
    path.write_bytes(b"MZdata")
    with pytest.raises(SignatureVerificationError, match="not a .exe"):
        validate_installer_file(path)


def test_validate_installer_file_rejects_empty_file(tmp_path):
    path = _write_exe(tmp_path, b"")
    with pytest.raises(SignatureVerificationError, match="empty"):
        validate_installer_file(path)


def test_validate_installer_file_rejects_non_executable(tmp_path):
    path = _write_exe(tmp_path, b"PK\x03\x04 not an exe")
    with pytest.raises(SignatureVerificationError, match="not a Windows executable"):
        validate_installer_file(path)


def test_validate_installer_file_rejects_oversize(tmp_path):
    path = _write_exe(tmp_path)
    with pytest.raises(SignatureVerificationError, match="size limit"):
        validate_installer_file(path, max_bytes=10)


def test_verify_installer_accepts_hash_and_exact_publisher(tmp_path):
    data = b"MZ" + b"signed" * 20
    path = _write_exe(tmp_path, data)
    result = verify_installer(
        path,
        sha256_bytes(data),
        "IDM",
        signature_runner=_valid_runner("IDM"),
    )
    assert result.publisher == "IDM"
    assert result.sha256 == sha256_bytes(data)
    assert result.size == len(data)


def test_verify_installer_rejects_hash_mismatch_before_signature(tmp_path):
    data = b"MZ" + b"data" * 20
    path = _write_exe(tmp_path, data)
    calls: list = []

    def runner(file_path):
        calls.append(file_path)
        return _valid_runner("IDM")(file_path)

    with pytest.raises(SignatureVerificationError, match="SHA-256"):
        verify_installer(path, "0" * 64, "IDM", signature_runner=runner)
    assert calls == []


def test_verify_installer_rejects_wrong_publisher(tmp_path):
    data = b"MZ" + b"data" * 20
    path = _write_exe(tmp_path, data)
    with pytest.raises(SignatureVerificationError, match="was signed by"):
        verify_installer(
            path,
            sha256_bytes(data),
            "IDM Ltd",
            signature_runner=_valid_runner("Evil Corp"),
        )


def test_verify_installer_rejects_invalid_signature_status(tmp_path):
    data = b"MZ" + b"data" * 20
    path = _write_exe(tmp_path, data)
    with pytest.raises(SignatureVerificationError, match="Authenticode"):
        verify_installer(
            path,
            sha256_bytes(data),
            "IDM",
            signature_runner=lambda _path: SignatureInfo(
                status="NotSigned", message="No signature"
            ),
        )


def test_verify_installer_requires_expected_publisher(tmp_path):
    data = b"MZ" + b"data" * 20
    path = _write_exe(tmp_path, data)
    with pytest.raises(SignatureVerificationError, match="No trusted publisher"):
        verify_installer(path, sha256_bytes(data), "", signature_runner=_valid_runner())


def test_verify_installer_wraps_runner_failure(tmp_path):
    data = b"MZ" + b"data" * 20
    path = _write_exe(tmp_path, data)

    def runner(_path):
        raise RuntimeError("PowerShell exploded")

    with pytest.raises(SignatureVerificationError, match="could not be verified"):
        verify_installer(path, sha256_bytes(data), "IDM", signature_runner=runner)


def test_publisher_matches_is_exact_not_substring():
    info = SignatureInfo(status="Valid", simple_name="IDM Download Manager")
    assert publisher_matches("IDM Download Manager", info)
    assert not publisher_matches("IDM", info)
    assert publisher_matches("idm download manager", info)


def test_publisher_matches_accepts_full_subject():
    info = SignatureInfo(status="Valid", subject="CN=IDM, O=Example")
    assert publisher_matches("CN=IDM, O=Example", info)
    assert not publisher_matches("IDM", info)


def test_verify_authenticode_accepts_full_subject(tmp_path):
    path = _write_exe(tmp_path)
    info = verify_authenticode(
        path,
        "CN=IDM, O=Example",
        runner=lambda _path: SignatureInfo(
            status="Valid", subject="CN=IDM, O=Example", simple_name="IDM"
        ),
    )
    assert info.subject == "CN=IDM, O=Example"


def test_parse_signature_output():
    output = (
        "noise from PowerShell\n"
        'IDM_SIGNATURE:{"status":"Valid","message":"","subject":"CN=IDM",'
        '"simple_name":"IDM","thumbprint":"ABC"}\n'
    )
    info = parse_signature_output(output)
    assert info.status == "Valid"
    assert info.simple_name == "IDM"
    assert info.thumbprint == "ABC"


def test_parse_signature_output_rejects_missing_marker():
    with pytest.raises(SignatureVerificationError, match="did not return"):
        parse_signature_output("nothing useful")


def test_parse_signature_output_rejects_bad_json():
    with pytest.raises(SignatureVerificationError, match="unreadable"):
        parse_signature_output("IDM_SIGNATURE:{not json")


def test_parse_signature_output_rejects_non_object():
    with pytest.raises(SignatureVerificationError, match="unreadable"):
        parse_signature_output('IDM_SIGNATURE:["Valid"]')
