#!/usr/bin/env python3
"""Generate Ed25519 keys and sign IDM release manifests.

The public key is embedded in ``config.py`` (``MANIFEST_PUBLIC_KEY``); the
private key never leaves the release environment.

Commands:
    python scripts/sign_manifest.py keygen --private-key C:\\secure\\idm-manifest.pem
    python scripts/sign_manifest.py sign --manifest latest.json --private-key C:\\secure\\idm-manifest.pem
    python scripts/sign_manifest.py verify --manifest latest.json --public-key <base64>

The signature covers canonical JSON of every field except manifest_signature.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idm.updater.errors import ManifestError  # noqa: E402
from idm.updater.manifest_validator import (  # noqa: E402
    canonical_manifest_bytes,
    verify_manifest_signature,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="Create an Ed25519 key pair")
    keygen.add_argument(
        "--private-key", type=Path, required=True, help="Output PEM private key"
    )
    keygen.add_argument(
        "--public-key",
        type=Path,
        default=None,
        help="Optional file for the base64 public key (also printed)",
    )

    sign = sub.add_parser("sign", help="Sign a manifest in place or to --output")
    sign.add_argument("--manifest", type=Path, required=True)
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--output", type=Path, default=None)

    verify = sub.add_parser("verify", help="Verify manifest_signature")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--public-key", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "keygen":
            return _keygen(args.private_key, args.public_key)
        if args.command == "sign":
            return _sign(args.manifest, args.private_key, args.output)
        if args.command == "verify":
            return _verify(args.manifest, args.public_key)
    except (OSError, ValueError, ManifestError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


def _keygen(private_path: Path, public_path: Path | None) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if private_path.exists():
        raise ValueError(
            f"{private_path} already exists. Refusing to overwrite a signing key."
        )
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(pem)
    _restrict_permissions(private_path)

    public_text = _public_key_text(private_key)
    if public_path is not None:
        public_path.write_text(public_text + "\n", encoding="ascii")
    print("Private key:", private_path)
    print("Public key (base64):")
    print(public_text)
    print("")
    print("Embed the public key in config.py as MANIFEST_PUBLIC_KEY.")
    return 0


def _sign(manifest_path: Path, private_path: Path, output: Path | None) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    data = _load_json(manifest_path)
    private_key = serialization.load_pem_private_key(
        private_path.read_bytes(), password=None
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("The private key is not an Ed25519 key.")

    unsigned = {key: value for key, value in data.items() if key != "manifest_signature"}
    signature = private_key.sign(canonical_manifest_bytes(unsigned))
    data["manifest_signature"] = base64.b64encode(signature).decode("ascii")

    target = output or manifest_path
    _write_json_atomic(target, data)
    print(f"Signed {target} with Ed25519")
    print("Public key (base64):")
    print(_public_key_text(private_key))
    return 0


def _verify(manifest_path: Path, public_key: str) -> int:
    data = _load_json(manifest_path)
    signature = data.get("manifest_signature")
    if not isinstance(signature, str) or not signature.strip():
        raise ManifestError("The manifest has no manifest_signature.")
    verify_manifest_signature(data, signature.strip(), public_key.strip())
    print("Signature OK")
    return 0


def _public_key_text(private_key) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _restrict_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
