# IDM 1.0.0 — Release Notes

**Release date:** 2026-11-01
**Platform:** Windows 10/11 x64
**Channel:** stable

IDM is an original Windows download manager built with Python, PySide6 and
Requests. It keeps the compact, classic Internet Download Manager layout while
using an original icon set, an SQLite-backed history and a real HTTP download
engine.

## Highlights

- **Multi-connection download engine** — up to 16 segmented HTTP Range
  connections, resumable after pause, restart or power loss, with a durable
  per-segment journal.
- **Safe completion** — data is written to `.idm.part`, verified against the
  expected size and only then renamed; existing files are never overwritten.
- **Queue and scheduler** — configurable concurrency, persistent queue,
  automatic retry with backoff and `Retry-After` support, and scheduled
  pause/resume.
- **Classic interface** — nine-button toolbar, category sidebar, sortable
  download list, modeless progress window with per-connection details, and
  **Classic Light**, **Modern Light** and **Modern Dark** themes.
- **Browser integration** — Chrome, Edge and Firefox extensions with a native
  messaging host and an authenticated loopback bridge. The browser copy is only
  cancelled after IDM confirms it accepted the transfer.
- **Seven-tab Options** — general behaviour, retries and speed limits,
  download locations, connections, interface visibility, themes and updates.
- **Import/export** — JSON snapshots and plain URL lists; imported items start
  paused.
- **Updater** — signed manifest support, resumable installer download, SHA-256
  and Authenticode verification, with a separate `IDM_Updater.exe`.

## Install

1. Verify the package contents against `SHA256SUMS.txt`.
2. Run `IDM_Setup_<version>.exe`.
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
certutil -hashfile IDM_Setup_1.0.0.exe SHA256
```

Compare the printed digest with the matching line in `SHA256SUMS.txt`.

## Known limitations

- The application, installer and updater are **not code-signed** in this
  build. Windows SmartScreen may warn on first launch.
- Automatic updates are implemented but **not configured**: no HTTPS endpoint,
  no Ed25519 manifest key and no trusted Authenticode publisher are baked in.
  See `docs/UPDATES.md`.
- Windows 10 support is provided by the installer configuration but this build
  was validated on Windows 11 x64 only.
- POST form downloads, Blob/MediaSource streams, browser-internal saves and
  authenticated sessions that require browser cookies stay in the browser.
- Real browser interception still needs manual verification on each target
  browser version.

## Upgrade and uninstall

The installer upgrades an existing per-user installation in place. Settings,
history, schedules and partial downloads under
`%APPDATA%\IDM Download Manager` are preserved. The uninstaller removes the
application but only deletes user data when explicitly requested.

See `docs\README.md` for the full feature guide and `docs\PACKAGING.md` for
build, signing and deployment details.
