"""SHA-256 and Windows Authenticode verification for update packages."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import SignatureVerificationError

logger = logging.getLogger(__name__)

_DEFAULT_MAX_BYTES = 512 * 1024 * 1024
_SIGNATURE_MARKER = "IDM_SIGNATURE:"
_VERIFY_TIMEOUT = 90

# Static local script. The file path is passed through an environment variable
# so no server-controlled value is ever interpolated into PowerShell code.
_PS_VERIFY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$path = $env:IDM_VERIFY_PATH
if ([string]::IsNullOrWhiteSpace($path)) { throw 'No installer path was supplied.' }
$signature = Get-AuthenticodeSignature -LiteralPath $path
$certificate = $signature.SignerCertificate
$subject = ''
$simpleName = ''
$thumbprint = ''
if ($certificate -ne $null) {
    $subject = [string]$certificate.Subject
    $simpleName = [string]$certificate.GetNameInfo(
        [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName,
        $false)
    $thumbprint = [string]$certificate.Thumbprint
}
$result = [ordered]@{
    status = [string]$signature.Status
    message = [string]$signature.StatusMessage
    subject = $subject
    simple_name = $simpleName
    thumbprint = $thumbprint
}
Write-Output ('IDM_SIGNATURE:' + ($result | ConvertTo-Json -Compress))
"""


@dataclass(frozen=True)
class SignatureInfo:
    status: str
    message: str = ""
    subject: str = ""
    simple_name: str = ""
    thumbprint: str = ""


@dataclass(frozen=True)
class VerifiedInstaller:
    path: Path
    sha256: str
    size: int
    publisher: str


SignatureRunner = Callable[[Path], SignatureInfo]


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_installer_file(
    path: Path, max_bytes: int = _DEFAULT_MAX_BYTES
) -> int:
    file_path = Path(path)
    if not file_path.is_file():
        raise SignatureVerificationError("The installer file does not exist.")
    if file_path.suffix.casefold() != ".exe":
        raise SignatureVerificationError("The update package is not a .exe file.")
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise SignatureVerificationError(
            "The installer file could not be inspected."
        ) from exc
    if size <= 0:
        raise SignatureVerificationError("The installer file is empty.")
    if size > max_bytes:
        raise SignatureVerificationError(
            "The installer is larger than the configured size limit."
        )
    try:
        with open(file_path, "rb") as handle:
            magic = handle.read(2)
    except OSError as exc:
        raise SignatureVerificationError(
            "The installer file could not be read."
        ) from exc
    if magic != b"MZ":
        raise SignatureVerificationError(
            "The update package is not a Windows executable."
        )
    return size


def verify_installer(
    path: Path,
    expected_sha256: str,
    expected_publisher: str,
    signature_runner: SignatureRunner | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> VerifiedInstaller:
    size = validate_installer_file(path, max_bytes=max_bytes)
    digest = compute_sha256(path)
    if not hmac.compare_digest(digest.lower(), str(expected_sha256).lower()):
        logger.warning("Installer SHA-256 mismatch: %s", Path(path).name)
        raise SignatureVerificationError(
            "The installer failed SHA-256 verification and will not be installed."
        )

    expected = (expected_publisher or "").strip().strip('"')
    if not expected:
        logger.info(
            "Installer verified against the signed manifest SHA-256 only "
            "(no Authenticode publisher configured): %s",
            digest,
        )
        return VerifiedInstaller(
            path=Path(path), sha256=digest, size=size, publisher=""
        )

    info = verify_authenticode(path, expected, runner=signature_runner)
    logger.info(
        "Installer signature verified (publisher=%s, sha256=%s)",
        info.simple_name or info.subject,
        digest,
    )
    return VerifiedInstaller(
        path=Path(path),
        sha256=digest,
        size=size,
        publisher=info.simple_name or info.subject,
    )


def verify_authenticode(
    path: Path,
    expected_publisher: str,
    runner: SignatureRunner | None = None,
) -> SignatureInfo:
    expected = (expected_publisher or "").strip().strip('"')
    if not expected:
        raise SignatureVerificationError(
            "No trusted publisher is configured, so the installer signature "
            "cannot be accepted. Set the Authenticode signer name in "
            "Options → Updates."
        )
    if sys.platform != "win32" and runner is None:
        raise SignatureVerificationError(
            "Windows Authenticode verification is only available on Windows."
        )

    signature_runner = runner or _run_powershell_signature
    try:
        info = signature_runner(Path(path))
    except SignatureVerificationError:
        raise
    except Exception as exc:
        logger.exception("Authenticode verification failed")
        raise SignatureVerificationError(
            "The installer signature could not be verified."
        ) from exc

    status = (info.status or "").strip()
    if status.casefold() != "valid":
        detail = f"Signature status: {status or 'Unknown'}."
        if info.message:
            detail += f" {info.message}"
        raise SignatureVerificationError(
            "The installer does not have a valid Windows Authenticode "
            "signature. " + detail
        )

    if not publisher_matches(expected, info):
        actual = info.simple_name or info.subject or "unknown publisher"
        logger.warning(
            "Installer publisher mismatch: expected %s, got %s",
            expected,
            actual,
        )
        raise SignatureVerificationError(
            f"The installer was signed by “{actual}”, not the configured "
            f"publisher “{expected}”. Installation was refused."
        )
    return info


def publisher_matches(expected: str, info: SignatureInfo) -> bool:
    expected_value = (expected or "").strip().strip('"').casefold()
    if not expected_value:
        return False
    simple_name = (info.simple_name or "").strip().casefold()
    subject = (info.subject or "").strip().casefold()
    return expected_value in {simple_name, subject}


def parse_signature_output(output: str) -> SignatureInfo:
    marker_index = output.find(_SIGNATURE_MARKER)
    if marker_index < 0:
        raise SignatureVerificationError(
            "Windows did not return signature information for the installer."
        )
    payload = output[marker_index + len(_SIGNATURE_MARKER) :].strip()
    payload = payload.splitlines()[0].strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SignatureVerificationError(
            "Windows returned unreadable signature information."
        ) from exc
    if not isinstance(data, dict):
        raise SignatureVerificationError(
            "Windows returned unreadable signature information."
        )
    return SignatureInfo(
        status=str(data.get("status") or ""),
        message=str(data.get("message") or ""),
        subject=str(data.get("subject") or ""),
        simple_name=str(data.get("simple_name") or ""),
        thumbprint=str(data.get("thumbprint") or ""),
    )


def _run_powershell_signature(path: Path) -> SignatureInfo:
    powershell = _powershell_path()
    if powershell is None:
        raise SignatureVerificationError(
            "Windows PowerShell is not available, so the installer signature "
            "cannot be verified."
        )

    environment = os.environ.copy()
    environment["IDM_VERIFY_PATH"] = str(Path(path).resolve())
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _PS_VERIFY_SCRIPT,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_VERIFY_TIMEOUT,
            env=environment,
            creationflags=creationflags,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SignatureVerificationError(
            "Windows signature verification timed out."
        ) from exc
    except OSError as exc:
        raise SignatureVerificationError(
            "Windows signature verification could not be started."
        ) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip().splitlines()
        detail = stderr[-1] if stderr else "no details were provided"
        logger.warning("PowerShell signature check failed: %s", detail)
        raise SignatureVerificationError(
            "Windows could not inspect the installer signature."
        )
    return parse_signature_output(result.stdout or "")


def _powershell_path() -> Path | None:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if candidate.is_file():
        return candidate
    located = shutil.which("powershell.exe")
    return Path(located) if located else None
