# IDM Update System

This document describes the implemented About / Check for Updates / automatic
update system, how to configure it, how to sign and publish releases, and what
has and has not been verified.

> **Status: implemented, but not operational out of the box.**
> No update endpoint, publisher or manifest key is baked into a source build.
> IDM reports “Updates are not configured.” until `GITHUB_OWNER` and
> `EXPECTED_PUBLISHER` are set in `config.py`, the manifest URL is set in
> **Options → Updates**, or environment variables provide them. Source builds
> cannot install updates because they have no `IDM_Updater.exe`; only the
> packaged build (`build_windows.ps1`) contains it. Nothing in the UI pretends
> otherwise.

## What is implemented

- **About window** (`Help → About IDM`) with logo, application name, installed
  version and channel, copyright, developer and storage information, release
  notes and the update panel.
- **Check for Updates** (`Help → Check for Updates…` or the button in About).
  The network request runs on a background `QThread`; the UI shows a busy
  indicator and stays responsive.
- **Version comparison** using semantic versioning (MAJOR.MINOR.PATCH with
  optional pre-release/build metadata). Downgrades are never offered, even if a
  manifest asks for one.
- **Stable and beta channels.** A stable installation only accepts `stable`
  manifests; a beta installation accepts `beta` and `stable` manifests.
- **Exact status text** for the no-update case:
  “You are using the latest version of IDM.”
- **Update available** shows the latest and installed versions, release date,
  mandatory note, release notes, and an **Update Now** button with a download
  progress bar. The latest version text is also clickable and starts the same
  installation workflow.
- **Strict manifest validation**: unknown fields, duplicate keys, `NaN` and
  `Infinity`, wrong types, an invalid channel, a malformed date, an untrusted
  download host, non-HTTPS URLs and malformed SHA-256 values are all rejected.
- **Optional Ed25519 manifest authentication**: when a public key is embedded in
  the application, every manifest must carry a valid `manifest_signature`.
- **Resumable download** of the installer to `%TEMP%\IDM-Update-*` with HTTP
  Range resume, retry, timeouts, redirect-chain validation, a size cap and
  cancellation.
- **SHA-256 verification** before anything is executed; a mismatch deletes the
  package and refuses installation.
- **Windows Authenticode verification** with an exact signer-name match. Both
  IDM and the standalone updater verify the package again before installing.
- **Separate updater executable** (`IDM_Updater.exe`) copied into the temporary
  update folder so it does not lock files in the installation directory. It
  waits for IDM to exit (without killing it), re-verifies the package, runs the
  signed Inno Setup installer silently, honours cancellation, restarts IDM only
  when requested, and cleans temporary files.
- **State preservation**: settings and queue are flushed, the SQLite database is
  backed up, and user data remains under `%APPDATA%\IDM Download Manager`.
- **No fake operations**: if the endpoint, publisher, manifest key or updater
  component is missing, the UI explains exactly what is missing and installation
  does not start.

## Central configuration

[`config.py`](../config.py) is the only place where the production endpoint and
trust anchors are declared. No update URL is hardcoded in another module.

| Constant | Purpose |
| --- | --- |
| `APP_NAME`, `CURRENT_VERSION` | Imported from `idm/version.py`; single version source. |
| `GITHUB_OWNER` | **REQUIRED.** GitHub user or organization that owns `IDM-Update-Server`. Empty in a source checkout. |
| `GITHUB_REPO` | Update-server repository name, default `IDM-Update-Server`. |
| `GITHUB_MANIFEST_BRANCH`, `GITHUB_MANIFEST_PATH` | Default `main` and `latest.json`. |
| `UPDATE_MANIFEST_URL` | Derived public HTTPS URL. Empty while `GITHUB_OWNER` is empty, which produces the “not configured” state instead of contacting a fake server. |
| `ALLOWED_MANIFEST_HOSTS` | `raw.githubusercontent.com`, `github.com`, `api.github.com`. |
| `ALLOWED_DOWNLOAD_HOSTS` | `github.com` plus the GitHub asset CDN hosts `objects.githubusercontent.com` and `release-assets.githubusercontent.com`. |
| `EXPECTED_PUBLISHER` | **REQUIRED for installation.** Exact Authenticode signer name for `IDM_Setup.exe`. |
| `MANIFEST_PUBLIC_KEY` | Optional base64 Ed25519 public key. When set, manifests must be signed. |
| `UPDATE_CHANNEL` | Default channel: `stable` or `beta`. |
| `UPDATE_CONNECT_TIMEOUT`, `UPDATE_READ_TIMEOUT` | 10 s connect, 30 s read. |
| `UPDATE_MAX_MANIFEST_BYTES`, `UPDATE_MAX_INSTALLER_BYTES` | 512 KiB and 512 MiB. |

The desktop application never contains a GitHub token, PFX password or private
signing key. `scripts/build_release.ps1` reads those from the local certificate
store or environment variables only.

## Configuration

### Options → Updates

| Setting | Purpose |
| --- | --- |
| Update server (manifest URL) | HTTPS URL of `latest.json`. Leave blank to use the value derived in `config.py`. |
| Trusted publisher | Exact Authenticode signer name or full certificate subject. Required to install. |
| Update channel | `Stable releases` or `Beta releases`. |

Settings are stored in the SQLite settings table with the rest of the
application preferences. An administrator can use the baked `config.py` values
instead, in which case the Options fields may stay blank.

### Environment overrides

Environment variables take precedence over saved settings and baked defaults,
which is useful for managed deployments and testing:

| Variable | Purpose |
| --- | --- |
| `IDM_UPDATE_MANIFEST_URL` | Manifest endpoint. |
| `IDM_UPDATE_PUBLISHER` | Exact signer name that must match the installer signature. |
| `IDM_UPDATE_CHANNEL` | `stable` or `beta` (case-insensitive). |
| `IDM_UPDATE_MANIFEST_PUBLIC_KEY` | Base64 Ed25519 public key; enables mandatory manifest signature verification. |
| `IDM_UPDATE_TRUSTED_HOSTS` | Extra comma/semicolon-separated download hosts, for example a CDN. |

The manifest host is always trusted automatically. GitHub-hosted manifests also
trust the standard GitHub release-asset CDN hosts. Every other download host must
be listed in `ALLOWED_DOWNLOAD_HOSTS` or `IDM_UPDATE_TRUSTED_HOSTS`.

The publisher is **not** optional for installation. A check can run without it,
but **Update Now** refuses to download until a publisher is configured.

### Safe defaults

- No default endpoint, publisher or manifest key.
- HTTPS only; plain HTTP, embedded credentials and IP-literal URLs are rejected.
- The manifest is limited to 512 KiB and the installer to 512 MiB.
- Timeouts are 10 seconds to connect and 30 seconds per read.

## Manifest format

The complete schema lives in
[`IDM-Update-Server/manifest.schema.json`](../IDM-Update-Server/manifest.schema.json).
The client accepts exactly these fields; anything else is an error.

```json
{
  "app_name": "IDM",
  "channel": "stable",
  "latest_version": "1.1.0",
  "minimum_supported_version": "1.0.0",
  "release_date": "2026-11-15",
  "release_notes": [
    "Faster pause/resume handling",
    "Fixed a queue ordering issue"
  ],
  "download_url": "https://github.com/<owner>/IDM-Update-Server/releases/download/v1.1.0/IDM_Setup_1.1.0.exe",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "mandatory": false,
  "manifest_signature": ""
}
```

| Field | Rules |
| --- | --- |
| `app_name` | Must be exactly `IDM`. Prevents serving another product's update. |
| `channel` | Exactly `stable` or `beta`. Stable installs reject beta manifests. |
| `latest_version` | Semantic version, for example `1.1.0` or `2.0.0-rc.1`. |
| `minimum_supported_version` | Semantic version no newer than `latest_version`. An installed version below this is treated as mandatory. |
| `release_date` | ISO 8601 date (`2026-11-15`) or date-time; normalized to `YYYY-MM-DD`. |
| `release_notes` | Optional. String or list of strings, up to 20,000 characters. NUL characters are removed. |
| `download_url` | HTTPS, DNS host, no credentials or fragment, ends in `.exe`, on a trusted host, at most 2,048 characters. |
| `sha256` | Exactly 64 hexadecimal characters. Case-insensitive; normalized to lowercase. |
| `mandatory` | Strict JSON boolean. Mandatory updates still require explicit user consent. |
| `manifest_signature` | Required string. Empty for an unsigned manifest; base64 Ed25519 signature otherwise. |

The sample in [`update/latest.json`](../update/latest.json) and the
`IDM-Update-Server` template intentionally contain `updates.example.com` and an
all-zero hash. They are templates, **not working releases**.

### Signed manifests

Signing the manifest protects the URL and hash even if the repository or CDN is
compromised. SHA-256 alone is not trusted when a key is configured.

1. Generate a key pair once, on a trusted offline machine:

   ```powershell
   .\.venv\Scripts\python.exe scripts\sign_manifest.py keygen `
     --private-key C:\secure\idm-manifest.pem
   ```

   The command prints the base64 public key and refuses to overwrite an existing
   private key. Keep the PEM offline.

2. Put the printed public key into `MANIFEST_PUBLIC_KEY` in `config.py` and into
   the update-server repository variable `MANIFEST_PUBLIC_KEY` used by CI.

3. Sign after every manifest change:

   ```powershell
   .\.venv\Scripts\python.exe scripts\sign_manifest.py sign `
     --manifest .\IDM-Update-Server\latest.json `
     --private-key C:\secure\idm-manifest.pem
   ```

   `scripts/build_release.ps1` does this automatically when
   `MANIFEST_PUBLIC_KEY` is set and `-ManifestPrivateKey` is supplied.

The signed bytes are the canonical JSON of every field except
`manifest_signature`: UTF-8, sorted keys, compact separators, no ASCII escaping.
`scripts/sign_manifest.py verify` and `scripts/validate_manifest.py` reproduce the
same verification locally.

## Hosting: GitHub Releases + `IDM-Update-Server`

The recommended layout is the one in
[`IDM-Update-Server/`](../IDM-Update-Server):

```
IDM-Update-Server/
  latest.json                 # public manifest, served from raw.githubusercontent.com
  manifest.schema.json        # Draft 2020-12 schema used by CI
  README.md
  releases/README.md          # installers belong in GitHub Releases, not the repo
  docs/                       # setup, publishing, deployment, troubleshooting
  .github/workflows/validate-manifest.yml
```

1. Create the public repository `IDM-Update-Server`. Public read access is
   required; the desktop client sends no credentials.
2. Create a release tagged `v1.1.0` and upload the signed `IDM_Setup_1.1.0.exe`
   as a release asset. Never commit installers to the repository.
3. Point `download_url` at
   `https://github.com/<owner>/IDM-Update-Server/releases/download/v1.1.0/IDM_Setup_1.1.0.exe`.
   GitHub redirects to `objects.githubusercontent.com` or
   `release-assets.githubusercontent.com`; both are trusted for GitHub manifests.
4. Publish `latest.json` at the repository root on `main`:
   `https://raw.githubusercontent.com/<owner>/IDM-Update-Server/main/latest.json`.
   Do not use a short-lived asset URL that changes on every publish.
5. Keep old installer assets available; a rollback publishes an older manifest,
   but IDM will still never downgrade below the installed version.

The workflow in `.github/workflows/validate-manifest.yml` validates the schema,
rejects the template placeholders, and verifies the Ed25519 signature when the
`MANIFEST_PUBLIC_KEY` repository variable is set. See
[`IDM-Update-Server/docs/SETUP.md`](../IDM-Update-Server/docs/SETUP.md),
[`PUBLISHING.md`](../IDM-Update-Server/docs/PUBLISHING.md),
[`DEPLOYMENT_WINDOWS.md`](../IDM-Update-Server/docs/DEPLOYMENT_WINDOWS.md) and
[`TROUBLESHOOTING.md`](../IDM-Update-Server/docs/TROUBLESHOOTING.md) for the
server-side walkthrough, Windows 10/11 deployment and diagnostics.

### Alternative: custom HTTPS server

1. Serve `latest.json` from a stable HTTPS address and add that host to
   `ALLOWED_MANIFEST_HOSTS` or `IDM_UPDATE_TRUSTED_HOSTS`.
2. Serve the signed installer from the same host or add the download host to
   `ALLOWED_DOWNLOAD_HOSTS`.
3. Use a valid TLS certificate. TLS verification is never disabled.
4. Do not require interactive authentication or custom tokens: the client does
   not send credentials, and embedding secrets in URLs is rejected.
5. Serve JSON with a normal content type and avoid stale caching
   (`Cache-Control: no-cache` is sent by IDM).

## Code signing

Automatic installation is designed around a code-signing certificate. An
unsigned installer is correctly refused with:

> The installer does not have a valid Windows Authenticode signature.

The expected publisher is compared **exactly** (case-insensitive) against either
the certificate's simple name (typically the subject CN) or the full subject
string. Partial matches such as expecting `IDM` when the signer is
`IDM Download Manager` are rejected on purpose.

Sign all three files:

1. `IDM.exe` (packaged application)
2. `IDM_Updater.exe` (standalone updater)
3. `IDM_Setup.exe` (final installer)

The application and updater are signed **before** Inno Setup packages them, and
the installer is signed after it is compiled. `scripts/build_release.ps1`
performs this order automatically. Manual equivalent:

```powershell
.\build_windows.ps1 -SkipInstaller -Force

signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /sha1 <THUMBPRINT> /d "IDM Internet Download Manager" .\dist\IDM\IDM.exe
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /sha1 <THUMBPRINT> /d "IDM Updater" .\dist\IDM\IDM_Updater.exe

& "C:\Program Files\Inno Setup 7\ISCC.exe" .\installer\IDM_Setup.iss

signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /sha1 <THUMBPRINT> /d "IDM Setup" .\dist-installer\IDM_Setup.exe
```

Configure the signer name that Windows reports, for example:

```powershell
(Get-AuthenticodeSignature .\dist-installer\IDM_Setup.exe).SignerCertificate.GetNameInfo(
  [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false)
```

Use that exact output as `EXPECTED_PUBLISHER`. Store the certificate and its
password outside the repository; never commit signing secrets.

## Publishing a release

The repeatable workflow is
[`scripts/publish_instructions.md`](../scripts/publish_instructions.md) and
[`scripts/build_release.ps1`](../scripts/build_release.ps1). Summary:

1. **Decide the version.** Release tags use stable `MAJOR.MINOR.PATCH`;
   `build_windows.ps1` rejects pre-release suffixes in packaged builds.
2. **Bump the version in all four places:**
   - `idm/version.py` → `CURRENT_VERSION`
   - `version_info.txt` → `filevers`, `prodvers`, `FileVersion`,
     `ProductVersion`
   - `version_info_updater.txt` → the same fields
   - `installer/IDM_Setup.iss` → `MyAppVersion`, `MyAppVerName`,
     `VersionInfoVersion`
   The build script fails if the source version, both version resources and the
   installer version disagree.
3. **Set the release identity** in `config.py`: `GITHUB_OWNER`,
   `EXPECTED_PUBLISHER` and, if used, `MANIFEST_PUBLIC_KEY`.
4. **Run the test suite**:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests -q
   ```

5. **Dry run** the release (builds, signs, writes and validates the manifest
   without uploading anything):

   ```powershell
   .\scripts\build_release.ps1 `
     -CertThumbprint <THUMBPRINT> `
     -Channel stable `
     -ReleaseNotes "Faster resume","Fixed queue ordering" `
     -ManifestPrivateKey C:\secure\idm-manifest.pem
   ```

   Use `-AllowUnsigned` only for an internal test build. A production release
   without a certificate fails.

6. **Validate before publishing.** The script runs
   [`scripts/validate_manifest.py`](../scripts/validate_manifest.py), which checks
   the schema, channel, signature, trusted host, SHA-256 and installer size. It
   can also be run alone:

   ```powershell
   .\.venv\Scripts\python.exe scripts\validate_manifest.py `
     .\IDM-Update-Server\latest.json `
     --channel stable --installer .\dist-installer\IDM_Setup_1.1.0.exe
   ```

7. **Publish** with `-Publish` (and `-PushManifest` to commit and push
   `latest.json`). The script uses the authenticated `gh` CLI and refuses to
   overwrite an existing release asset. It never uses `--clobber`.

8. **Verify the public endpoint and a real upgrade.**
   `curl.exe -fsSL https://raw.githubusercontent.com/<owner>/IDM-Update-Server/main/latest.json`
   must return the new manifest. Then install the previous build, run
   **Help → Check for Updates…**, and confirm the comparison, download, hash and
   signature verification, UAC behaviour, restart and preserved history.

The release is not “operational” until steps 1–8 have been completed against the
real repository with a real signed installer.

Emergency rollback: publish a manifest with an older `latest_version` (IDM will
not downgrade an already-updated installation) or raise
`minimum_supported_version` and ship a fixed build. Do not lower the version in
a way that hides a security fix; increment normally.

## Runtime flow

```
Help → Check for Updates
  └─ HTTPS GET manifest (background thread, timeouts, redirect validation)
      ├─ schema / channel / signature validation
      ├─ no update → "You are using the latest version of IDM."
      └─ update → release notes + Update Now (and clickable latest version)
                    └─ confirmation (restart checkbox, default Cancel)
                        └─ download to %TEMP%\IDM-Update-* (Range resume)
                            └─ SHA-256 + Authenticode verification
                                └─ save settings, back up database
                                    └─ copy IDM_Updater.exe to the temp folder
                                        └─ write update-handoff.json, launch updater
                                            └─ IDM saves state and exits
                                                └─ updater waits for IDM (no kill)
                                                    └─ re-verifies package
                                                        └─ Inno Setup silent install
                                                            ├─ success → optional restart, cleanup
                                                            └─ failure → notification, old app kept
```

The updater is launched detached from the temporary folder, not from `{app}`.
This is deliberate: it lets the installer replace `IDM.exe` and
`IDM_Updater.exe` without a running process locking them. UAC is left entirely
to Windows and Inno Setup; the updater never elevates by itself.

### Installer arguments

```
/SILENT /SP- /NORESTART /CLOSEAPPLICATIONS /LOG=<update-dir>\installer-install.log
```

`/ALLUSERS` is added when the current application resides under a Program Files
directory. The installer also uses `UsePreviousPrivileges=yes`, so an automatic
update keeps the original per-user or all-users scope and does not silently move
an installation.

## Paths and cleanup

| Item | Location |
| --- | --- |
| Update download and handoff | `%TEMP%\IDM-Update-*` |
| Updater log | `%APPDATA%\IDM Download Manager\logs\updater.log` |
| Application log | `%APPDATA%\IDM Download Manager\logs\idm.log` |
| Pre-update database backups | `%APPDATA%\IDM Download Manager\database\backups\` |
| Settings, history, queue | `%APPDATA%\IDM Download Manager\database\idm.sqlite3` |

- The five newest pre-update database backups are retained.
- On success the updater removes its temp folder. Its own executable is locked
  while running, so it leaves a completion marker; the next IDM start removes
  that folder. Abandoned update folders older than 24 hours are also removed at
  startup.
- Failure keeps the update folder and log for diagnosis; it is removed later as
  stale.
- Cleanup only accepts `IDM-Update-*` directories directly under the system temp
  folder and never follows symbolic links. User data, downloads and the
  installation directory are never deleted by this cleanup.

## Security invariants

- Never overwrite the running executable; a separate updater performs the
  installation after IDM exits.
- Never execute downloaded Python scripts, batch files or arbitrary commands
  from the server. Only a verified `.exe` installer is launched.
- HTTPS only, with full redirect-chain validation; redirects to HTTP or untrusted
  hosts are rejected.
- The manifest is strictly validated. Unknown fields, duplicate keys, `NaN` and
  `Infinity` are rejected so a malformed or ambiguous document cannot be
  interpreted differently by different tools.
- When `MANIFEST_PUBLIC_KEY` is set, an unsigned or tampered manifest is
  rejected. SHA-256 is not trusted alone in that mode.
- SHA-256 is verified before Authenticode, and both are verified again by the
  updater immediately before execution.
- The expected publisher must match exactly.
- No downgrade is offered, regardless of `mandatory` or the manifest contents.
- The user must confirm every installation. Mandatory updates are still
  cancelled by default and are never installed silently.
- Windows UAC is never bypassed; Defender and SmartScreen are never disabled.
- Logs contain versions, URLs without query strings, hashes and error details,
  but no credentials or tokens. No token support exists by design.
- A compromised manifest can at most cause a download from a trusted HTTPS host
  that fails hash, publisher or manifest-signature verification. It cannot
  inject commands or paths into PowerShell: the verification script is static
  and the file path is passed through an environment variable.
- User data is outside the installation directory and is never touched by
  install, update or default uninstall.

## Test coverage

`pytest tests -q` currently passes **252 tests**. Relevant files:

| Scenario | Coverage |
| --- | --- |
| No update available | `test_update_checker.py`, `test_update_ui.py` |
| Update available | `test_update_checker.py`, `test_update_ui.py` |
| Invalid JSON / invalid fields / unknown or duplicate fields | `test_update_manifest.py` |
| Signed manifest: valid, tampered, wrong key, unsigned-with-key | `test_signed_manifest.py` |
| Config precedence, derived endpoint, channel, trusted hosts | `test_update_config.py` |
| Release scripts: validator CLI, keygen/sign/verify, hash mismatch | `test_release_scripts.py` |
| No internet, timeout, TLS failure | `test_update_checker.py` (injected transport errors) |
| Interrupted download and Range resume | `test_update_downloader.py` |
| Wrong SHA-256 | `test_update_downloader.py`, `test_package_verifier.py` |
| Invalid or wrong signature | `test_package_verifier.py`, `test_updater.py` |
| Installer cancelled | `test_updater.py` |
| Redirect/host validation, size caps | `test_update_checker.py`, `test_update_downloader.py` |
| Version comparison, no downgrade, mandatory, channels | `test_version_manager.py`, `test_update_checker.py` |
| Handoff validation, updater run flow, args | `test_updater.py` |
| Settings/DB preservation, upgrade, uninstall | Existing packaging documentation; database backup and shutdown logic are exercised indirectly. |
| End-to-end signed update from a real server | **Not executed**: requires a code-signing certificate, a public HTTPS endpoint and the user's GitHub repository. |

To exercise the real signature path on a Windows development machine, build an
unsigned installer and configure the trusted publisher; the update must be
refused with a signature error, which is the expected safe result. A successful
end-to-end update requires signing as described above.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| “Updates are not configured.” | Set `GITHUB_OWNER` in `config.py`, or the manifest URL in Options → Updates, or `IDM_UPDATE_MANIFEST_URL`. |
| “No trusted update publisher is configured.” | Set the exact signer name in Options → Updates or `IDM_UPDATE_PUBLISHER`. |
| “The Updater component is missing.” | You are running from source or a broken install. Use the packaged build/reinstall. |
| “The update server returned HTTP 404 …” | The manifest URL is wrong or the release was not published. |
| “The download host … is not trusted.” | Put the installer on a GitHub release or add the CDN host with `IDM_UPDATE_TRUSTED_HOSTS`. |
| “The update manifest contains unsupported field(s) …” | Remove the extra field; the client rejects unknown keys on purpose. |
| “channel must be either ‘stable’ or ‘beta’.” | Set `channel` exactly to `stable` or `beta` in `latest.json`. |
| “The update manifest is unsigned, but this build requires a signed manifest.” | Sign `latest.json` with `scripts/sign_manifest.py` or clear `MANIFEST_PUBLIC_KEY` for an unsigned test build. |
| “The update manifest signature is invalid.” | The manifest changed after signing or was signed with a different key. Re-sign the exact bytes. |
| “MANIFEST_PUBLIC_KEY must decode to exactly 32 …” | Use the base64 public key printed by `sign_manifest.py keygen`. |
| “failed SHA-256 verification” | The manifest hash does not match the uploaded installer. Recompute it; do not bypass. |
| “does not have a valid Windows Authenticode signature” | Sign the installer and upload the signed file. |
| “was signed by X, not the configured publisher Y” | Use the exact signer name reported by `Get-AuthenticodeSignature`. |
| Update folder remains in `%TEMP%` | The updater’s own executable was locked during cleanup. It is removed on the next IDM start once older than the marked/stale threshold. |
| Installer shows UAC | Expected for an all-users installation. IDM never bypasses UAC. |

## Limitations

- Full-installer updates only; no delta patching.
- No background polling or silent automatic checks. Checks are user initiated,
  as required.
- The update server must be publicly reachable over HTTPS; private tokens and
  authenticated endpoints are not supported.
- A signed release requires a code-signing certificate and a manually controlled
  signing step; the build script does not hold signing secrets.
- Authenticode verification is Windows-specific. Other platforms are not
  supported for installation.
- Windows 11 is the tested platform. The code and installer target Windows 10
  as well, but Windows 10 was not available for end-to-end verification.
