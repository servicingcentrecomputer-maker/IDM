# IDM 3.5.0 Testing Report

**Date:** 2026-11-01
**Build:** 3.5.0 (stable)
**Platform:** Windows 10.0.26300 x64

## Environment

| Component | Version |
| --- | --- |
| Python | 3.12.14 |
| PySide6 / Qt | 6.12.0 |
| Requests | 2.34.2 |
| PyInstaller | 6.22.3 |
| Inno Setup | 7.1.1 |
| Node.js (extension harness) | 24.18.0 |

The UI test suite runs with `QT_QPA_PLATFORM=offscreen` and an isolated
`APPDATA`, so tests never read or write the real user profile or the
commercial IDM data folder.

## Automated regression

| Area | Command | Result |
| --- | --- | ---: |
| Core, engine, persistence, updater, extensions | `pytest tests -q --ignore=tests/test_ui.py --ignore=tests/test_update_ui.py --ignore=tests/test_update_notification.py` | 468 passed, 23.01 s |
| Main window, downloads, dialogs, screenshots | `pytest tests/test_ui.py -q` | 16 passed, 118.78 s |
| Update panel | `pytest tests/test_update_ui.py -q` | 21 passed, 2.46 s |
| Update notification | `pytest tests/test_update_notification.py -q` | 10 passed, 10.24 s |
| App-data layout, release notes and scripts | `pytest tests/test_app_layout.py tests/test_release_notes.py tests/test_release_scripts.py -q` | 17 passed, 0.72 s |
| Compile check | `python -m compileall -q idm integrations tools scripts` | clean |
| **Total** | | **532 passed, 0 failed** |

`tests/test_ui.py` is slow because each scenario creates a real offscreen
main window, theme, local HTTP server and download engine. Running the four UI
files in one pytest process intermittently stalls past ten minutes on this
machine; each file passes independently, which is the result recorded above.
This is a test-harness ordering issue, not an application hang — a native
`MainWindow` build and navigation profile completes in under one second.

### What the automated tests cover

- Download engine: Range requests, segmentation, pause/resume, retry, speed
  limits, queue ordering and media categorisation.
- Persistence: SQLite schema v4, additive migrations, settings round-trips and
  verified backups.
- Browser integration: manifest validation, pinned extension ID, native host
  protocol validation, message size limits and command allowlists.
- Extension packaging: deterministic Chrome/Edge/Firefox ZIPs, manifest
  version parity, installer resources and PyInstaller inclusion.
- Update pipeline: signed manifest parsing, HTTPS enforcement, SHA-256,
  Authenticode policy, download resumption, install approval, backup and
  rollback.
- UI: shell creation, theme switching, filters, search, sorting, add/progress/
  options/about/queue/scheduler dialogs, toolbar state, import/export and
  dashboard composition.

## Visual and responsive checks

Offscreen renders were generated for the redesigned pages at 1366×768,
1920×1080 and a narrow 1040 px width, in both light and dark themes:

- Settings — all fourteen sections, search results and the no-results state.
- Browser Assistant — disconnected, configured and registration guidance
  states.
- Update Center — not checked, up to date, update ready and check failed.
- All Downloads — Category column, painted progress, status chips and
  multi-selection.
- Video Downloads — card grid, metadata, per-card actions and empty state.
- Dashboard — empty and active-transfer states, including the state-driven
  headline and colour-coded transfer statuses.
- Performance Monitor — transfer-rate chart, summary tiles and the aligned
  tuning grid.
- Toolbar and navigation rail — monochrome palette-aware icons in both themes
  and correct active-row state when navigating to footer pages.
- Video Downloads — cinematic navy posters in both palettes, search field with
  leading icon and a separated delete action.
- Options dialog — every tab inside a scroll container, verified at short
  window heights where the Updates tab previously overlapped.
- Badges and counts — rounded corners verified after replacing the
  unrenderable `999px` pill radius with 14 px and per-component radii.

Page minimum widths were measured against the 1024 px minimum window
(Settings body 435 px, Browser Assistant body 576 px, Update Center body
462 px, content stack 457 px). All fit without horizontal scrolling. Token
sizes are device-independent, and Qt's high-DPI scaling was exercised at
100%, 125%, 150% and 175%.

## Accessibility and motion

- All icon-only buttons expose accessible names; focus rings are visible in
  every palette.
- Sidebar lists and video cards are keyboard focusable; Enter/Space activates
  navigation and card actions.
- Reduced motion disables every animation duration, and Windows'
  “Animation effects” setting is honoured automatically.
- Status is conveyed by icon and text, not colour alone.

## Packaging verification

`build_windows.ps1` validated version parity before packaging:

- `idm/version.py`, all three `version_info*.txt` resources and
  `installer/IDM_Setup.iss` report 3.5.0.
- Chrome, Edge and Firefox manifests and the unpacked Video Assistant report
  3.5.0.
- The installer resource declares `VersionInfoVersion=3.5.0.0` and
  `OutputBaseFilename=IDM-Setup-{#MyAppVersion}`.
- `IDM.exe`, `IDM_Updater.exe` and `IDM_NativeHost.exe` are present in the
  portable folder; `qwindows.dll` and the bundled logo are verified.
- Extension ZIPs are written to `dist-extensions\`.
- The release bundle is assembled at `release\IDM-3.5.0-win64\` with a
  deterministic ZIP and `SHA256SUMS.txt`.

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `dist\IDM\IDM.exe` | 5,075,153 B | `209D4B360BFFF2D44B2375B6B792065D400DFE632877353E8919108FF8B0EC45` |
| `dist\IDM\IDM_Updater.exe` | 15,617,300 B | `6CEB00CC07D6A3D174EC082FED408C9A70D2D9FEC9ADAA4609163B9B1560BD9E` |
| `dist\IDM\IDM_NativeHost.exe` | 8,304,265 B | `E45E4FDA5F1E8FDEBB82E6EB17418B51FCF215A026F157538AC1B31597AA8788` |
| `dist-installer\IDM-Setup-3.5.0.exe` | 62,404,223 B | `9ECFD18359A9C16578C897BAC62D91F388C6FE30DD95DED8DB25FEFA54BBF852` |

The release ZIP changes whenever documentation is updated; its current digest
is written next to the archive as `release\IDM-3.5.0-win64.zip.sha256`.

The packaged `IDM.exe` and `IDM-Setup-3.5.0.exe` both report file and product
version 3.5.0 (3.5.0.0 in the embedded resources). The release folder contains
237 files (209.7 MiB) and its `SHA256SUMS.txt` covers 236 files (all except
itself).

A frozen-build smoke test of the final `dist\IDM\IDM.exe` with an isolated
`APPDATA` and `QT_QPA_PLATFORM=offscreen` started successfully: it migrated
and opened schema v4, started the browser bridge as native host 3.5.0 on a
loopback port, reached “Main window ready”, and completed a background update
check (installed 3.5.0, feed 3.0.0, no update) before the harness stopped it.

## Preserved data and backup

The verified Phase 1 backup remains at
`Backup/Version_3.0.0_20261101/`. No database migration is introduced by
3.5.0; existing settings, history, queue, partial files and browser
registration are preserved. Tests use an isolated `APPDATA`, and the build
script does not touch `%APPDATA%\IDM Download Manager`.

## Known limitations and external prerequisites

- The public signed update manifest (`update/latest.json`) still advertises
  3.0.0 because signing requires the release private key, which is kept outside
  the repository. A 3.5.0 install correctly reports that it is newer than the
  feed; publishing a 3.5.0 manifest is a post-build signing step.
- The 3.5.0 installer is not Authenticode-signed unless a CA-issued certificate
  is supplied. SHA-256 and the signed manifest remain the trust anchors.
- Chrome, Edge and Firefox store installation is outside the installer; the
  extensions ship as ZIPs and unpacked folders and are never installed
  silently.
