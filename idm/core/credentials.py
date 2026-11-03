"""Secret storage backed by the Windows Credential Manager.

Passwords for proxies and authenticated servers are never written to the
SQLite database or any configuration file.  They are stored as generic
credentials in the signed-in user's vault and read back only when a transfer
starts.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
_CRED_MAX_CREDENTIAL_BLOB_SIZE = 5 * 512
_CRED_MAX_TARGET_NAME = 32767
_CRED_MAX_USERNAME = 513

DEFAULT_PREFIX = "IDM"


class CredentialError(RuntimeError):
    """A credential could not be stored or read."""


class CredentialUnavailable(CredentialError):
    """The Windows Credential Manager is not available on this system."""


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_library: ctypes.WinDLL | None = None


def _advapi32() -> ctypes.WinDLL:
    global _library
    if sys.platform != "win32":
        raise CredentialUnavailable(
            "Secure credential storage requires Windows Credential Manager."
        )
    if _library is None:
        library = ctypes.WinDLL("advapi32", use_last_error=True)
        library.CredWriteW.argtypes = [
            ctypes.POINTER(_CREDENTIALW),
            wintypes.DWORD,
        ]
        library.CredWriteW.restype = wintypes.BOOL
        library.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        library.CredReadW.restype = wintypes.BOOL
        library.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        library.CredDeleteW.restype = wintypes.BOOL
        library.CredFree.argtypes = [ctypes.c_void_p]
        library.CredFree.restype = None
        _library = library
    return _library


def _validate_component(label: str, value: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise CredentialError(f"{label} cannot be empty.")
    if len(text) > maximum:
        raise CredentialError(f"{label} is too long.")
    if any(ord(character) < 32 for character in text):
        raise CredentialError(f"{label} contains control characters.")
    return text


def target_name(scope: str, name: str, prefix: str = DEFAULT_PREFIX) -> str:
    scope_text = _validate_component("Credential scope", scope, 64)
    name_text = _validate_component("Credential name", name, 512).casefold()
    target = f"{prefix}/{scope_text}/{name_text}"
    if len(target) > _CRED_MAX_TARGET_NAME:
        raise CredentialError("The credential name is too long.")
    return target


def set_secret(
    scope: str,
    name: str,
    username: str,
    password: str,
    prefix: str = DEFAULT_PREFIX,
) -> None:
    """Create or replace a generic credential."""
    library = _advapi32()
    target = target_name(scope, name, prefix)
    user = _validate_component("User name", username, _CRED_MAX_USERNAME)
    blob = str(password or "").encode("utf-16-le")
    if not blob:
        raise CredentialError("The password cannot be empty.")
    if len(blob) > _CRED_MAX_CREDENTIAL_BLOB_SIZE:
        raise CredentialError("The password is too long for Credential Manager.")

    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = _CREDENTIALW()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = user

    if not library.CredWriteW(ctypes.byref(credential), 0):
        error = ctypes.get_last_error()
        raise CredentialError(
            f"Windows Credential Manager rejected the credential (error {error})."
        )


def get_secret(
    scope: str, name: str, prefix: str = DEFAULT_PREFIX
) -> tuple[str, str] | None:
    """Return ``(username, password)`` or ``None`` when nothing is stored."""
    library = _advapi32()
    target = target_name(scope, name, prefix)
    pointer = ctypes.POINTER(_CREDENTIALW)()
    if not library.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return None
        raise CredentialError(
            f"Windows Credential Manager could not read the credential "
            f"(error {error})."
        )
    try:
        credential = pointer.contents
        size = int(credential.CredentialBlobSize)
        if size <= 0 or not credential.CredentialBlob:
            password = ""
        else:
            raw = ctypes.string_at(credential.CredentialBlob, size)
            password = raw.decode("utf-16-le", errors="replace")
        username = credential.UserName or ""
        return username, password
    finally:
        library.CredFree(pointer)


def delete_secret(scope: str, name: str, prefix: str = DEFAULT_PREFIX) -> bool:
    """Remove a credential.  Returns ``True`` when one was removed."""
    library = _advapi32()
    target = target_name(scope, name, prefix)
    if library.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        return True
    error = ctypes.get_last_error()
    if error == ERROR_NOT_FOUND:
        return False
    raise CredentialError(
        f"Windows Credential Manager could not remove the credential "
        f"(error {error})."
    )


def has_secret(scope: str, name: str, prefix: str = DEFAULT_PREFIX) -> bool:
    try:
        return get_secret(scope, name, prefix) is not None
    except CredentialUnavailable:
        return False


__all__ = [
    "CredentialError",
    "CredentialUnavailable",
    "DEFAULT_PREFIX",
    "delete_secret",
    "get_secret",
    "has_secret",
    "set_secret",
    "target_name",
]
