# IDM-Update-Server

Public update manifest repository for the IDM Windows desktop application.

IDM reads `latest.json` over HTTPS from a stable raw GitHub URL:

```
https://raw.githubusercontent.com/<owner>/IDM-Update-Server/main/latest.json
```

The repository must be **public** so the desktop application can perform an
unauthenticated read. The application never sends a GitHub token, PAT or other
credential.

## Repository contents

| Path | Purpose |
| --- | --- |
| `latest.json` | The live manifest consumed by IDM. |
| `releases/` | Notes and checksums only. **Never commit installer binaries here.** |
| `docs/` | Setup, publishing, Windows deployment and troubleshooting. |
| `manifest.schema.json` | JSON Schema used by CI validation. |
| `.github/workflows/validate-manifest.yml` | Validates `latest.json` on push/PR. |

Installer binaries are published as **GitHub Release assets**, not committed to
this repository. This keeps the repository small and lets GitHub host and CDN
the large files.

## Quick start

1. Create a public GitHub repository named `IDM-Update-Server` under your
   account or organization.
2. Push these files to the `main` branch.
3. Replace the placeholders in `latest.json` with a real release:
   - `latest_version`
   - `minimum_supported_version`
   - `release_date`
   - `release_notes`
   - `download_url` (the GitHub Release asset URL)
   - `sha256` (lowercase SHA-256 of the installer you uploaded)
   - `manifest_signature` (Ed25519, if `MANIFEST_PUBLIC_KEY` is configured)
4. In the IDM application, set `GITHUB_OWNER` in `config.py` to your GitHub
   user or organization. `UPDATE_MANIFEST_URL` is derived automatically. Set
   `EXPECTED_PUBLISHER` to the exact Authenticode signer name of your
   installer.
5. Verify the public manifest:

   ```powershell
   curl.exe -fsSL https://raw.githubusercontent.com/<owner>/IDM-Update-Server/main/latest.json
   ```

6. Run `Help > Check for Updates` in IDM.

The `latest.json` in this repository is a **template**. CI intentionally fails
on placeholder values until you replace them with a real, signed release.

## Security model

- HTTPS only. The client rejects HTTP, embedded credentials, IP literals and
  untrusted hosts, including untrusted redirect hops.
- SHA-256 from the manifest is verified before installation.
- The installer must have a valid Windows Authenticode signature from the
  configured `EXPECTED_PUBLISHER`.
- Optionally, the manifest itself is signed with Ed25519. Install
  `cryptography`, generate a key pair with
  `scripts/sign_manifest.py keygen`, embed only the public key in IDM's
  `config.py`, and keep the private key offline.
- The application never executes scripts or commands supplied by this server.
  It downloads a `.exe` installer, verifies it and launches it. Windows UAC is
  never bypassed.

## Documentation

- [Setup](docs/SETUP.md)
- [Publishing](docs/PUBLISHING.md)
- [Windows deployment](docs/DEPLOYMENT_WINDOWS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
