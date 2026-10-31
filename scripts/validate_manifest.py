#!/usr/bin/env python3
"""Validate an IDM release manifest before it is published.

Examples:
    python scripts/validate_manifest.py IDM-Update-Server/latest.json
    python scripts/validate_manifest.py latest.json --installer IDM_Setup_1.1.0.exe
    python scripts/validate_manifest.py latest.json --channel beta --allow-unsigned

The command exits 0 only when the manifest is structurally valid, belongs to
the requested channel, uses a trusted download host and (when configured) has
a valid Ed25519 signature.  If --installer is supplied, its SHA-256 and size
are checked as well.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config as app_config  # noqa: E402
from idm.updater.config import build_update_config  # noqa: E402
from idm.updater.errors import UpdateError  # noqa: E402
from idm.updater.manifest_validator import UpdateManifest  # noqa: E402
from idm.updater.package_verifier import (  # noqa: E402
    compute_sha256,
    validate_installer_file,
)

ENV_MANIFEST_PUBLIC_KEY = "IDM_UPDATE_MANIFEST_PUBLIC_KEY"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate an IDM latest.json release manifest."
    )
    parser.add_argument("manifest", type=Path, help="Path to latest.json")
    parser.add_argument(
        "--channel",
        choices=("stable", "beta"),
        default=app_config.UPDATE_CHANNEL,
        help="Channel the installation follows (default: %(default)s)",
    )
    parser.add_argument(
        "--public-key",
        default="",
        help="Base64 Ed25519 manifest public key (default: config.py value)",
    )
    parser.add_argument(
        "--allow-unsigned",
        action="store_true",
        help="Allow a manifest with no configured signing key",
    )
    parser.add_argument(
        "--installer",
        type=Path,
        default=None,
        help="Optional installer file whose SHA-256 must match the manifest",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the normalized manifest as JSON",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        text = args.manifest.read_bytes()
    except OSError as exc:
        return _fail(f"Cannot read {args.manifest}: {exc}")

    public_key = (
        args.public_key
        or os.environ.get(ENV_MANIFEST_PUBLIC_KEY, "")
        or app_config.MANIFEST_PUBLIC_KEY
    ).strip()
    if not public_key and not args.allow_unsigned:
        return _fail(
            "No manifest public key is configured. Set MANIFEST_PUBLIC_KEY in "
            "config.py, pass --public-key, or pass --allow-unsigned if this "
            "release deliberately uses an unsigned manifest."
        )

    config = build_update_config(
        manifest_url=app_config.UPDATE_MANIFEST_URL,
        channel=args.channel,
    )
    try:
        manifest = UpdateManifest.from_json(
            text,
            config.trusted_hosts,
            max_bytes=config.max_manifest_bytes,
            public_key=public_key,
        )
    except UpdateError as exc:
        return _fail(str(exc))

    if args.channel == "stable" and manifest.channel != "stable":
        return _fail(
            "The manifest is on the beta channel but this validation is for "
            "the stable channel."
        )

    if args.installer is not None:
        try:
            size = validate_installer_file(
                args.installer, max_bytes=config.max_installer_bytes
            )
            digest = compute_sha256(args.installer)
        except (OSError, UpdateError) as exc:
            return _fail(f"Installer validation failed: {exc}")
        if digest.lower() != manifest.sha256:
            return _fail(
                "Installer SHA-256 does not match the manifest.\n"
                f"  manifest: {manifest.sha256}\n"
                f"  installer: {digest}"
            )
        print(f"Installer OK: {args.installer} ({size} bytes, sha256={digest})")
    elif not args.json:
        print("Installer not checked (no --installer supplied).")

    signature = (
        "verified (Ed25519)"
        if public_key
        else "UNSIGNED (no public key configured; accepted with --allow-unsigned)"
    )
    print("Manifest OK")
    print(f"  app:      {manifest.app_name}")
    print(f"  channel:  {manifest.channel}")
    print(f"  version:  {manifest.latest_version}")
    print(f"  minimum:  {manifest.minimum_supported_version}")
    print(f"  released: {manifest.release_date}")
    print(f"  url:      {manifest.download_url}")
    print(f"  sha256:   {manifest.sha256}")
    print(f"  signature: {signature}")

    if args.json:
        import json

        print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
