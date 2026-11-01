# IDM 2.0.1 — Release Notes

**Release date:** 2026-11-01
**Platform:** Windows 10/11 x64
**Channel:** stable

2.0.1 connects the update system to the published GitHub repository and makes
**Check for Updates** work in packaged builds. Every 2.0.0 download,
browser-integration and recovery behaviour is unchanged.

## What changed

- **Update endpoint configured** — packaged builds read the signed manifest at
  `https://raw.githubusercontent.com/servicingcentrecomputer-maker/IDM/main/update/latest.json`.
  The About window and Help → Check for Updates no longer report
  “Updates are not configured.”
- **Ed25519 manifest verification** — the application embeds the manifest
  public key, so every update manifest must carry a valid signature. The
  matching private key is kept outside the repository.
- **Manual download for unsigned builds** — because this build has no CA-issued
  Authenticode certificate, IDM replaces **Update Now** with **Download
  Installer**. That button opens the manifest’s GitHub release asset in the
  browser; the application never downloads or runs an unsigned installer by
  itself. The same applies to the update notification, and automatic download
  is skipped in this state.
- **Clearer security messaging** — when automatic installation is unavailable,
  the UI explains that a trusted code-signing certificate is required instead
  of showing a generic configuration error.
- **Version metadata** — application, updater, native host, installer and
  browser extensions report 2.0.1.

## Existing features

- Multi-connection download engine with up to 16 segmented HTTP Range
  connections, resumable after pause, restart or power loss.
- Safe completion through `.idm.part` files; existing files are never
  overwritten.
- Persistent queue, retry with backoff, `Retry-After` support and scheduled
  pause/resume.
- Classic interface with **Classic Light**, **Modern Light** and **Modern
  Dark** themes.
- Chrome, Edge and Firefox integration with a native messaging host.
- Verified pre-update backups, pending-update recovery and rollback.
- Import/export of JSON snapshots and URL lists.

## Install

1. Verify the package contents against `SHA256SUMS.txt`.
2. Run `IDM_Setup_2.0.1.exe`.
3. Optionally select the browser-integration tasks for the browsers you use.
4. Launch IDM from the Start Menu or desktop shortcut.

Installing 2.0.1 over 2.0.0 or 1.0.0 upgrades in place. Settings, history,
schedules and partial downloads under `%APPDATA%\IDM Download Manager` are
preserved.

If you are running 1.0.0 or 2.0.0, install 2.0.1 manually once. Older builds
have no update endpoint baked in, so they cannot discover 2.0.1 by themselves;
from 2.0.1 onward, checking works normally.

## Verification

`SHA256SUMS.txt` uses the standard `sha256sum` format:

```bat
certutil -hashfile IDM_Setup_2.0.1.exe SHA256
```

Compare the printed digest with the matching line in `SHA256SUMS.txt`.

## Known limitations

- The application, installer and updater are **not code-signed**. Windows
  SmartScreen may warn on first launch.
- **Automatic installation is disabled in this build** because no trusted
  Authenticode publisher is configured. Update checks and signed manifests work;
  new versions are downloaded manually from GitHub. Automatic installation
  returns on the first build released with a CA-issued certificate and a signed
  installer.
- Windows 10 support is provided by the installer configuration but this build
  was validated on Windows 11 x64 only.
- POST form downloads, Blob/MediaSource streams, browser-internal saves and
  authenticated sessions that require browser cookies stay in the browser.
- Real browser interception still needs manual verification on each target
  browser version.

## Upgrade and uninstall

The installer upgrades an existing per-user installation in place. The
uninstaller removes the application but only deletes user data when explicitly
requested.

See `docs\README.md` for the full feature guide, `docs\UPDATES.md` for the
update system and `docs\PACKAGING.md` for build, signing and deployment details.
