"""Manifest fetching, redirect validation and update decisions."""

from __future__ import annotations

import json

import pytest
import requests

from idm.updater.errors import (
    ChannelMismatchError,
    NetworkError,
    UpdateConfigurationError,
)
from idm.updater.update_checker import check_for_updates, fetch_manifest
from tests.update_helpers import (
    MANIFEST_URL,
    FakeResponse,
    FakeSession,
    make_config,
    manifest_data,
)


def _manifest_response(**overrides) -> FakeResponse:
    return FakeResponse(json.dumps(manifest_data(**overrides)).encode("utf-8"))


def test_fetch_manifest_success_and_request_options():
    session = FakeSession(_manifest_response())
    manifest = fetch_manifest(make_config(), session=session)
    assert manifest.latest_version == "1.1.0"
    assert session.calls[0]["timeout"] == make_config().timeout
    assert session.calls[0]["stream"] is True
    assert session.calls[0]["allow_redirects"] is True
    assert session.calls[0]["url"] == MANIFEST_URL


def test_fetch_manifest_closes_response():
    response = _manifest_response()
    fetch_manifest(make_config(), session=FakeSession(response))
    assert response.closed is True


def test_fetch_manifest_requires_configuration():
    with pytest.raises(UpdateConfigurationError):
        fetch_manifest(make_config(manifest_url=""))


@pytest.mark.parametrize(
    "url",
    [
        "http://updates.example.com/latest.json",
        "https://user:pass@updates.example.com/latest.json",
        "https://127.0.0.1/latest.json",
        "https://evil.example.com/latest.json",
    ],
)
def test_fetch_manifest_rejects_unsafe_endpoints(url):
    with pytest.raises(UpdateConfigurationError):
        fetch_manifest(make_config(manifest_url=url))


def test_fetch_manifest_reports_http_error():
    session = FakeSession(FakeResponse(b"missing", status_code=404))
    with pytest.raises(NetworkError, match="HTTP 404"):
        fetch_manifest(make_config(), session=session)


@pytest.mark.parametrize(
    "error",
    [
        requests.Timeout("slow"),
        requests.ConnectionError("offline"),
        requests.exceptions.SSLError("bad certificate"),
        requests.RequestException("generic"),
    ],
)
def test_fetch_manifest_maps_network_errors(error):
    with pytest.raises(NetworkError):
        fetch_manifest(make_config(), session=FakeSession(error))


def test_fetch_manifest_rejects_declared_oversize_body():
    response = FakeResponse(b"{}", headers={"Content-Length": "999999"})
    with pytest.raises(NetworkError, match="large"):
        fetch_manifest(
            make_config(max_manifest_bytes=1024), session=FakeSession(response)
        )


def test_fetch_manifest_rejects_streamed_oversize_body():
    response = FakeResponse(b"x" * 2048)
    with pytest.raises(NetworkError, match="large"):
        fetch_manifest(
            make_config(max_manifest_bytes=1024), session=FakeSession(response)
        )


def test_fetch_manifest_rejects_untrusted_redirect():
    history = [FakeResponse(url="https://evil.example.com/latest.json")]
    response = FakeResponse(
        json.dumps(manifest_data()).encode("utf-8"), history=history
    )
    with pytest.raises(NetworkError, match="untrusted host"):
        fetch_manifest(make_config(), session=FakeSession(response))


def test_fetch_manifest_rejects_insecure_redirect():
    history = [FakeResponse(url="http://updates.example.com/latest.json")]
    response = FakeResponse(
        json.dumps(manifest_data()).encode("utf-8"), history=history
    )
    with pytest.raises(NetworkError, match="insecure"):
        fetch_manifest(make_config(), session=FakeSession(response))


def test_fetch_manifest_rejects_untrusted_final_url():
    response = FakeResponse(
        json.dumps(manifest_data()).encode("utf-8"),
        url="https://evil.example.com/latest.json",
    )
    with pytest.raises(NetworkError, match="untrusted host"):
        fetch_manifest(make_config(), session=FakeSession(response))


def test_check_for_updates_no_update():
    current = manifest_data(latest_version="1.0.0", minimum_supported_version="1.0.0")
    session = FakeSession(FakeResponse(json.dumps(current).encode("utf-8")))
    result = check_for_updates(make_config(), "1.0.0", session=session)
    assert not result.update_available
    assert not result.mandatory
    assert not result.installed_is_newer


def test_check_for_updates_available():
    session = FakeSession(_manifest_response())
    result = check_for_updates(make_config(), "1.0.0", session=session)
    assert result.update_available
    assert result.latest_version > result.current_version
    assert result.manifest.release_date == "2026-10-31"


def test_check_for_updates_mandatory():
    session = FakeSession(_manifest_response(mandatory=True))
    result = check_for_updates(make_config(), "1.0.0", session=session)
    assert result.update_available
    assert result.mandatory


def test_check_for_updates_below_minimum_is_mandatory():
    session = FakeSession(
        _manifest_response(
            latest_version="2.0.0", minimum_supported_version="1.5.0"
        )
    )
    result = check_for_updates(make_config(), "1.0.0", session=session)
    assert result.update_available
    assert result.below_minimum
    assert result.mandatory


def test_check_for_updates_never_downgrades():
    session = FakeSession(
        _manifest_response(
            latest_version="1.0.0", minimum_supported_version="1.0.0"
        )
    )
    result = check_for_updates(make_config(), "2.0.0", session=session)
    assert not result.update_available
    assert result.installed_is_newer


def test_stable_installation_rejects_beta_manifest():
    session = FakeSession(_manifest_response(channel="beta"))
    with pytest.raises(ChannelMismatchError, match="stable channel"):
        check_for_updates(make_config(channel="stable"), "1.0.0", session=session)


def test_beta_installation_accepts_beta_manifest():
    session = FakeSession(_manifest_response(channel="beta"))
    result = check_for_updates(make_config(channel="beta"), "1.0.0", session=session)
    assert result.update_available
    assert result.manifest.channel == "beta"


def test_beta_installation_accepts_stable_manifest():
    session = FakeSession(_manifest_response(channel="stable"))
    result = check_for_updates(make_config(channel="beta"), "1.0.0", session=session)
    assert result.update_available
    assert result.manifest.channel == "stable"


def test_fetch_manifest_uses_configured_public_key():
    import base64

    from idm.updater.errors import ManifestError

    data = manifest_data()
    data["manifest_signature"] = base64.b64encode(b"\x00" * 64).decode("ascii")
    public_key = base64.b64encode(b"\x01" * 32).decode("ascii")
    session = FakeSession(FakeResponse(json.dumps(data).encode("utf-8")))
    with pytest.raises(ManifestError, match="signature is invalid"):
        fetch_manifest(
            make_config(manifest_public_key=public_key), session=session
        )
