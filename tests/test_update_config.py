"""Central update configuration and precedence tests."""

from __future__ import annotations

import pytest

import config as app_config
from idm.updater.config import (
    UpdateConfig,
    build_update_config,
    normalize_channel,
)
from idm.updater.errors import UpdateConfigurationError


def test_application_identity_has_a_single_source():
    from idm.version import APP_NAME, CURRENT_VERSION

    assert app_config.APP_NAME == APP_NAME
    assert app_config.CURRENT_VERSION == CURRENT_VERSION


def test_manifest_url_is_derived_from_github_owner():
    expected = (
        f"https://raw.githubusercontent.com/{app_config.GITHUB_OWNER}/"
        f"{app_config.GITHUB_REPO}/{app_config.GITHUB_MANIFEST_BRANCH}/"
        f"{app_config.GITHUB_MANIFEST_PATH}"
    )
    if app_config.GITHUB_OWNER:
        assert app_config.UPDATE_MANIFEST_URL == expected
    else:
        assert app_config.UPDATE_MANIFEST_URL == ""


def test_github_hosts_are_trusted_by_default():
    values = app_config.ALLOWED_DOWNLOAD_HOSTS
    assert "github.com" in values
    assert "objects.githubusercontent.com" in values
    assert "release-assets.githubusercontent.com" in values


def test_environment_overrides_saved_values():
    config = build_update_config(
        "https://saved.example.com/latest.json",
        "Saved Publisher",
        "stable",
        "",
        environ={
            "IDM_UPDATE_MANIFEST_URL": "https://github.com/owner/repo/raw/main/latest.json",
            "IDM_UPDATE_PUBLISHER": "Env Publisher",
            "IDM_UPDATE_CHANNEL": "beta",
            "IDM_UPDATE_TRUSTED_HOSTS": "cdn.example.com;extra.example.com",
            "IDM_UPDATE_MANIFEST_PUBLIC_KEY": "abc",
        },
    )
    assert config.manifest_url.startswith("https://github.com/")
    assert config.expected_publisher == "Env Publisher"
    assert config.channel == "beta"
    assert config.manifest_public_key == "abc"
    assert "cdn.example.com" in config.trusted_hosts
    assert "extra.example.com" in config.trusted_hosts
    assert "github.com" in config.trusted_hosts


def test_saved_values_are_used_when_environment_is_empty():
    config = build_update_config(
        "https://updates.example.com/latest.json",
        "Saved Publisher",
        "beta",
        "saved-key",
        environ={},
    )
    assert config.manifest_url == "https://updates.example.com/latest.json"
    assert config.expected_publisher == "Saved Publisher"
    assert config.channel == "beta"
    assert config.manifest_public_key == "saved-key"
    assert "updates.example.com" in config.trusted_hosts


def test_baked_defaults_apply_when_nothing_is_saved():
    config = build_update_config(environ={})
    assert config.manifest_url == app_config.UPDATE_MANIFEST_URL
    assert config.channel == app_config.UPDATE_CHANNEL
    assert config.expected_publisher == app_config.EXPECTED_PUBLISHER
    assert config.manifest_public_key == app_config.MANIFEST_PUBLIC_KEY


def test_invalid_environment_channel_is_rejected():
    with pytest.raises(UpdateConfigurationError):
        build_update_config(environ={"IDM_UPDATE_CHANNEL": "nightly"})


@pytest.mark.parametrize("value", ["stable", "beta", "BETA", " Stable "])
def test_normalize_channel_accepts_supported_values(value):
    assert normalize_channel(value) in {"stable", "beta"}


@pytest.mark.parametrize("value", ["", "nightly", "rc"])
def test_normalize_channel_rejects_unknown_values(value):
    with pytest.raises(UpdateConfigurationError):
        normalize_channel(value)


def test_config_requires_endpoint():
    config = UpdateConfig(manifest_url="", expected_publisher="", trusted_hosts=())
    with pytest.raises(UpdateConfigurationError, match="No update server"):
        config.require_endpoint()


def test_install_trust_accepts_publisher_or_manifest_key():
    for config in (
        UpdateConfig(
            manifest_url="https://updates.example.com/latest.json",
            expected_publisher="IDM",
            trusted_hosts=(),
        ),
        UpdateConfig(
            manifest_url="https://updates.example.com/latest.json",
            expected_publisher="",
            trusted_hosts=(),
            manifest_public_key="key",
        ),
    ):
        config.require_install_trust()


def test_install_trust_requires_a_trust_anchor():
    config = UpdateConfig(
        manifest_url="https://updates.example.com/latest.json",
        expected_publisher="",
        trusted_hosts=(),
        manifest_public_key="",
    )
    with pytest.raises(UpdateConfigurationError, match="trusted update signature"):
        config.require_install_trust()


def test_installation_supported_needs_endpoint_and_a_trust_anchor():
    assert UpdateConfig(
        manifest_url="https://updates.example.com/latest.json",
        expected_publisher="IDM",
        trusted_hosts=(),
    ).installation_supported
    assert UpdateConfig(
        manifest_url="https://updates.example.com/latest.json",
        expected_publisher="",
        trusted_hosts=(),
        manifest_public_key="key",
    ).installation_supported
    assert not UpdateConfig(
        manifest_url="https://updates.example.com/latest.json",
        expected_publisher="",
        trusted_hosts=(),
        manifest_public_key="",
    ).installation_supported
    assert not UpdateConfig(
        manifest_url="",
        expected_publisher="IDM",
        trusted_hosts=(),
    ).installation_supported
