# IDM 2.0.0 — Release Notes

**Release date:** 2026-11-01
**Platform:** Windows 10/11 x64
**Channel:** stable

IDM is an original Windows download manager built with Python, PySide6 and
Requests. It keeps the compact, classic Internet Download Manager layout while
using an original icon set, an SQLite-backed history and a real HTTP download
engine.

Version 2.0.0 completes the automatic update system: background checks, a
non-modal notification, optional automatic download, verified pre-update
backups, startup recovery and rollback.

## What's new in 2.0.0

### Automatic update checks

- IDM checks for updates shortly after startup and then every 1–168 hours
  (default 24 hours). Checks are skipped while downloads are active and can be
  disabled in **Options → Updates**.
- A new version opens a non-modal notification with the version, release date
  and release notes. **Install Now** starts the normal consent flow;
  **Remind Me Later** postpones that exact version for 24 hours.
- New versions can be downloaded automatically in the background (off by
  default). Installation still requires approval unless the user deliberately
  turns off **Ask before installing an update**.
- Background failures do not interrupt the user with error dialogs; they are
  written to the log and reported in the status bar.

### Secure update installation

- Releases are described by a strictly validated manifest. Unknown fields,
  duplicate keys, malformed versions, untrusted hosts and non-HTTPS URLs are
  rejected.
- Optional Ed25519 manifest signatures authenticate the download URL and
  SHA-256 before anything is downloaded.
- The installer is downloaded with HTTP Range resume and retry, then verified
  with SHA-256 and Windows Authenticode. The standalone `IDM_Updater.exe`
  verifies the package again immediately before execution.
- The expected publisher must match exactly. Unsigned packages, wrong
  publishers and downgrades are refused.
- IDM exits before the installer runs; it is never force-closed, and active
  downloads are paused only with the user's consent. UAC is left to Windows.

### Verified backups and recovery

- Before an update, IDM creates a verified snapshot of the SQLite database
  (with an integrity check), settings, update configuration, download history,
  queue and browser-native manifest configuration.
- A pending-update record written before installation lets the next IDM start
  report success, a skipped install, a failure, a version mismatch or a
  database problem.
- **Restore Previous Version** uses the cached, verified previous installer or
  a binary snapshot, and always restores the verified pre-update database.
  User download files are never deleted.

### Update settings and diagnostics

- **Options → Updates** now controls automatic checks, the check interval,
  notifications, automatic download, install confirmation and shows the last
  check and last successful update.
- A **Check for Updates Now** button is available on the same page and in the
  About window.

### Under the hood

- SQLite schema version 3 records the source browser and HTTP referrer for
  browser-submitted downloads; existing databases migrate in place.
- Release notes are grouped into New features, Performance, Security, Bug
  fixes and Changes in the update dialog.
- Download throughput metrics and update history are recorded for diagnostics.

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
- Import/export of JSON snapshots and URL lists.

## Install

1. Verify the package contents against `SHA256SUMS.txt`.
2. Run `IDM_Setup_2.0.0.exe`.
3. Optionally select the browser-integration tasks for the browsers you use.
4. Launch IDM from the Start Menu or desktop shortcut.

A portable build is included under `portable\IDM`; run `IDM.exe` directly if
you do not want to install. The portable build keeps its data in
`%APPDATA%\IDM Download Manager`, like the installed build.

Browser extension packages are in `browser-extensions\` and are copied into the
installation directory by the installer. They are never installed silently.

## Verification

`SHA256SUMS.txt` uses the standard `sha256sum` format:

```bat
certutil -hashfile IDM_Setup_2.0.0.exe SHA256
```

Compare the printed digest with the matching line in `SHA256SUMS.txt`.

## Known limitations

- The application, installer and updater are **not code-signed** in this
  build. Windows SmartScreen may warn on first launch.
- Automatic updates are implemented but **not configured** in this build: no
  HTTPS endpoint, Ed25519 manifest key or trusted Authenticode publisher is
  baked in. Update checks report that updates are not configured until those
  values are supplied. See `docs/UPDATES.md`.
- Windows 10 support is provided by the installer configuration but this build
  was validated on Windows 11 x64 only.
- POST form downloads, Blob/MediaSource streams, browser-internal saves and
  authenticated sessions that require browser cookies stay in the browser.
- Real browser interception still needs manual verification on each target
  browser version.
- A real signed end-to-end upgrade requires a code-signing certificate and a
  public update endpoint; that path has not been executed with this build.

## Upgrade and uninstall

The installer upgrades an existing per-user installation in place. Settings,
history, schedules and partial downloads under
`%APPDATA%\IDM Download Manager` are preserved. The uninstaller removes the
application but only deletes user data when explicitly requested.

See `docs\README.md` for the full feature guide, `docs\UPDATES.md` for the
update system and `docs\PACKAGING.md` for build, signing and deployment details.
