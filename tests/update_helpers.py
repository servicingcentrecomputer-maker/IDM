"""Fakes for update networking tests (no external network access)."""

from __future__ import annotations

import hashlib
import re

import requests

from idm.updater.config import UpdateConfig
from idm.updater.manifest_validator import UpdateManifest

TRUSTED_HOST = "updates.example.com"
MANIFEST_URL = f"https://{TRUSTED_HOST}/latest.json"
DOWNLOAD_URL = f"https://{TRUSTED_HOST}/releases/IDM_Setup_1.1.0.exe"


def installer_bytes(version: str = "1.1.0", size: int = 4096) -> bytes:
    seed = f"IDM installer {version} ".encode("utf-8")
    return (b"MZ" + (seed * (size // len(seed) + 1))[: size - 2])


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_data(payload: bytes | None = None, **overrides) -> dict:
    data = {
        "app_name": "IDM",
        "channel": "stable",
        "latest_version": "1.1.0",
        "minimum_supported_version": "1.0.0",
        "release_date": "2026-10-31",
        "release_notes": ["Faster resume", "Fixed update checks"],
        "download_url": DOWNLOAD_URL,
        "sha256": sha256_bytes(payload or installer_bytes()),
        "mandatory": False,
        "manifest_signature": "",
    }
    data.update(overrides)
    return data


def make_config(**overrides) -> UpdateConfig:
    values = {
        "manifest_url": MANIFEST_URL,
        "expected_publisher": "IDM",
        "trusted_hosts": (TRUSTED_HOST,),
    }
    values.update(overrides)
    return UpdateConfig(**values)


def make_manifest(payload: bytes | None = None, **overrides) -> UpdateManifest:
    return UpdateManifest.from_dict(
        manifest_data(payload, **overrides), (TRUSTED_HOST,)
    )


class FakeResponse:
    """Minimal requests.Response stand-in with streaming support."""

    def __init__(
        self,
        body: bytes = b"",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        url: str = MANIFEST_URL,
        history: list[FakeResponse] | None = None,
        interrupt: bool = False,
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.url = url
        self.history = list(history or [])
        self.interrupt = interrupt
        self.closed = False

    def iter_content(self, chunk_size: int = 64 * 1024):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]
        if self.interrupt:
            raise requests.ConnectionError("Simulated connection drop")

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Return queued responses or raise queued exceptions."""

    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.headers: dict[str, str] = {}
        self.calls: list[dict] = []
        self.closed = False

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self._responses:
            raise AssertionError("The fake session has no response left")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(url, **kwargs)
        return item

    def close(self) -> None:
        self.closed = True


_RANGE_RE = re.compile(r"bytes=(\d+)-")


class RangeDownloadSession:
    """Serve real byte ranges for downloader resume tests."""

    def __init__(
        self,
        body: bytes,
        *,
        ignore_range: bool = False,
        interrupt_first_at: int | None = None,
        chunk_size: int = 128 * 1024,
    ) -> None:
        self.body = body
        self.ignore_range = ignore_range
        self.interrupt_first_at = interrupt_first_at
        self.chunk_size = chunk_size
        self.calls: list[dict[str, str]] = []
        self.headers: dict[str, str] = {}
        self.closed = False
        self._first = True

    def get(self, url: str, headers: dict[str, str] | None = None, **kwargs):
        request_headers = dict(headers or {})
        self.calls.append(request_headers)
        if self._first and self.interrupt_first_at is not None:
            self._first = False
            sent = self.body[: self.interrupt_first_at]
            return FakeResponse(
                sent,
                status_code=200,
                headers={"Content-Length": str(len(self.body))},
                url=url,
                interrupt=True,
            )
        self._first = False

        range_value = request_headers.get("Range")
        match = _RANGE_RE.fullmatch(range_value.strip()) if range_value else None
        if match and not self.ignore_range:
            start = int(match.group(1))
            if start >= len(self.body):
                return FakeResponse(
                    b"",
                    status_code=416,
                    headers={"Content-Range": f"bytes */{len(self.body)}"},
                    url=url,
                )
            chunk = self.body[start:]
            return FakeResponse(
                chunk,
                status_code=206,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": (
                        f"bytes {start}-{len(self.body) - 1}/{len(self.body)}"
                    ),
                },
                url=url,
            )

        return FakeResponse(
            self.body,
            status_code=200,
            headers={"Content-Length": str(len(self.body))},
            url=url,
        )

    def close(self) -> None:
        self.closed = True
