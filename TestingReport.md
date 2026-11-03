# IDM 3.6.3 Testing Report

**Date:** 2026-11-03
**Build:** 3.6.3 (stable)
**Platform:** Windows 11 x64 (10.0.26300)

## Environment

| Component | Version |
| --- | --- |
| Python | 3.12.14 |
| PySide6 / Qt | 6.12.0 |
| Requests | 2.34.2 |
| PyInstaller | 6.22.3 |
| Inno Setup | 7 (per-user install) |
| Node.js (extension harness) | 24.18.0 |

The automated UI suite runs with `QT_QPA_PLATFORM=offscreen` and an isolated
`APPDATA`, so tests never read or write the real user profile or the commercial
IDM data folder.

## Automated regression

| Area | Command | Result |
| --- | --- | ---: |
| All tests (engine, segmentation, FTP, categories, dialogs, browser bridge, native host, security, updater, extensions, main window) | `python -m pytest tests -q` inside `build_windows.ps1` | **762 passed, 0 failed** in 128.63 s |
| Bandwidth limiting and the speed graph | `pytest tests/test_bandwidth.py -q` | 27 passed |
| Properties window and file actions | `pytest tests/test_properties.py -q` | 8 passed |
| Log and message redaction | `pytest tests/test_security.py -q` | 18 passed |
| Version consistency after the 3.6.3 bump | `pytest tests/test_extensions_packages.py tests/test_video_assistant_extension.py tests/test_update_config.py tests/test_updater.py tests/test_version_manager.py -q` | 105 passed |

The full-suite run is the release gate used by `build_windows.ps1`; it completed
with exit code 0 and collected all 762 tests. The suite grew from 735 in 3.6.2,
the additions being the bandwidth meter, the properties window, the file tools,
FTP, the tray and the redaction cases.

### New coverage in 3.6.3

| Test module | Covers |
| --- | --- |
| `test_bandwidth.py` | Rolling link-capacity estimate; throttled samples scaled back by the allowed fraction with the inference capped; a sample pinned at its own cap never measures the link; stale peaks expire out of the window; sub-interval noise ignored; `seed()` restores the saved figure; percentage clamping; a 3.6.2 settings file still means a fixed limit; the three new keys survive a save cycle; fixed, percentage and unlimited modes in the engine and switching between them; the measurement window lifts the cap and puts it back; graph history and painting. |
| `test_properties.py` | The properties window reports the size on disk rather than the size the record claims; Open is disabled when the file is missing; each action carries the right download id; the dialog stays usable on a 620 px screen; opening a file hands off to the shell; an executable asks before opening; menu actions track the selection. |
| `test_tray.py` | Tray menu actions, minimise-to-tray, start-with-Windows applied and undone from the registry, and the options dialog wiring. |
| `test_network_settings.py` | Proxy modes, bypass matching, per-site credentials and the connect and read timeouts. |
| `test_engine_security.py`, `test_transfer_policy.py` | Media-platform restriction enforced inside the engine, destination path validation and refusal of protected sources. |
| `test_ftp_engine.py` with `tests/ftp_server.py` | FTP and FTPS transfer, resume with `REST` and the friendly error mapping. |
| `test_file_tools.py` | Rename with rollback and category re-detection, refresh download link, manual SHA-256 verification. |
| `test_dialog_page_links.py`, `test_browser_page.py` | The page-link capture list, filtering of `mailto:` and JavaScript links, and the browser integration page. |
| `test_security.py` (extended) | `scrub_secrets` over proxy URLs, query tokens, headers and free-form prose; the logging filter applied to a real record. |

## Visual review

`tests/render_ui.py` renders the real widgets on the native Windows Qt platform
(not offscreen) into `build\ui-check\`. The 3.6.3 additions were captured the
same way and inspected before release:

| Artifact | What was checked |
| --- | --- |
| Progress window during a running transfer | The **SPEED OVER TIME** panel with curve, gradient fill, current/peak/average labels and the dashed line for the binding limit; an empty history paints an explanation instead of an invented curve. |
| Options → Download Settings | The three bandwidth limit modes with their fields, the measured-link readout and **Measure the link now**; each field sits on the row of its own radio button. |
| `native-progress-dark.png` | The progress window as a whole: stats grid, connection rows and the per-download limit control. |
| `native-dashboard-*.png`, `v362-*.png` | The 3.6.2 shell unchanged — table, status pills, sidebar counts, menus, toolbar and the responsive widths. |

No fake or placeholder transfer values are rendered: every size, speed, ETA,
capacity figure and completion time comes from the engine or the stored
`DownloadItem`.

## Packaging verification

`build_windows.ps1 -Force -Package` completed with exit code 0.

- `idm/version.py`, `integrations.NATIVE_HOST_VERSION`, all three
  `version_info*.txt` resources, `installer/IDM_Setup.iss` and the Chrome, Edge,
  Firefox and Video Assistant manifests report 3.6.3; the build refuses to
  package when any of them disagrees.
- The installer declares `VersionInfoVersion=3.6.3.0` and
  `OutputBaseFilename=IDM-Setup-{#MyAppVersion}`.
- `IDM.exe`, `IDM_Updater.exe` and `IDM_NativeHost.exe` are staged in the
  portable folder; `qwindows.dll` and the bundled logo were verified by the
  build.
- Extension ZIPs were written to `dist-extensions\`, including
  `IDM_Video_Assistant_3.6.3.zip`.
- The release bundle is assembled at `release\IDM-3.6.3-win64\` with
  `VERSION.json`, `ReleaseNotes.md`, `TestingReport.md` and `SHA256SUMS.txt`.

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `dist\IDM\IDM.exe` | 5,237,291 B | `959BBD8B112EE3197562D5418FF37AF8A14B664492C00781DBF698D73CE84E70` |
| `dist\IDM\IDM_Updater.exe` | 15,616,135 B | `1B5F406EC33F7DB84F476AFFB55AF8CA8DE1FF723E3F0C3B173C10A0A59E6829` |
| `dist\IDM\IDM_NativeHost.exe` | 8,307,116 B | `BB88BFFC47C1974D3C6F3C7DCAEB7D00B78F30D5BE3FB6C525C852963673EE4E` |
| `dist-installer\IDM-Setup-3.6.3.exe` | 62,572,274 B | `BC8BA5B6FD4D325B4D779376420303FEAEEB48459076A4D718A0A5641D19DE99` |

The release ZIP changes when documentation is rebuilt; its digest is written
next to the archive as `release\IDM-3.6.3-win64.zip.sha256` and is not repeated
here because this report is itself inside the bundle.

### Frozen-build smoke test

`dist\IDM\IDM.exe` was started with an isolated `APPDATA`
(`build\smoke-3.6.3`) and `QT_QPA_PLATFORM=offscreen`, then stopped by the
harness. The frozen process:

- created a fresh SQLite database and migrated it from schema 1 through 5;
- started the browser bridge as native host **3.6.3** on a loopback port;
- logged `Main window ready` and `IDM 3.6.3 started (data: …)`;
- reached the live update feed, fetched `update/latest.json` and reported
  `installed=3.6.3 latest=3.6.2 available=False mandatory=False`, so the new
  build does not offer to downgrade itself;
- reported `No system tray is available; IDM stays window-only`, which is the
  correct degradation under the offscreen platform — the tray itself needs a
  real desktop session and is covered by `test_tray.py`.

The executable reports file version 3.6.3.0.

### Installer

`IDM-Setup-3.6.3.exe` is compiled by Inno Setup 7 and its version resource is
verified. A silent install is **not** re-run on this machine: the installer
script and `AppId` are unchanged from 3.6.0, and running it would overwrite the
existing native-host registrations and the installed application for the current
user. Re-validate the installer on a clean Windows 10/11 machine or VM before
relying on the automatic upgrade path.

### Update manifest

`update/latest.json` is updated to advertise 3.6.3 with the published installer
URL, its real `package_size` (62,572,274 B) and SHA-256
`BC8BA5B6FD4D325B4D779376420303FEAEEB48459076A4D718A0A5641D19DE99`, re-signed
with the release Ed25519 private key
(`C:\Users\Jawad\.idm-signing\manifest-private.pem`); the public key derived
from that key matches `MANIFEST_PUBLIC_KEY` in `config.py`. The manifest is
validated with `scripts/validate_manifest.py` against the built installer before
the feed is pushed, and the GitHub release asset is published first so
`download_url` resolves.

The automatic download-and-install path from an older installed version was not
exercised on this machine; validate it on a clean Windows 10/11 VM before
advertising the update.

## Database and user data

- No schema change ships in 3.6.3; the settings schema version stays at 5 and
  the three new bandwidth keys are additive, read with defaults when absent.
- A 3.6.2 settings file with a non-zero `speed_limit_kbps` still resolves to a
  fixed limit after the upgrade, asserted in `test_bandwidth.py`.
- Download history, partial files, journals and browser registration are
  untouched.
- The installer reuses the same `AppId` and `%APPDATA%\IDM Download Manager`, so
  an upgrade in place keeps the list, the queue and the schedule.
- Tests, the visual review and the smoke test never touched the real
  `%APPDATA%\IDM Download Manager`.

## Security checks

- Proxy and site passwords go to Windows Credential Manager; the settings
  database keeps host, user and scheme only, never a plain-text password.
- Every log record passes `SecretRedactionFilter`, which scrubs URL credentials,
  `token=`/`key=` style parameters and `Authorization:` headers, including when
  they appear inside free-form error text.
- `validate_url`, `sanitize_filename` and `validate_folder_path` gate every
  download, and a resolved destination stays inside the chosen folder.
- Media platform restrictions are enforced in the engine, not only in dialogs,
  and no code path bypasses DRM, a paywall or any access control.
- Downloaded files are never executed automatically. Opening from the list hands
  the file to Windows, and a file whose extension Windows would execute asks for
  confirmation first.
- Browser extensions keep their existing minimal permissions; page-link capture
  reads links from the page the user is on and extracts no credentials.
- The installer and executables are unsigned; SHA-256 and the signed update
  manifest remain the trust anchors.

## Known limitations

- Windows 10 was not available for testing; the installer configuration supports
  it, but validation ran on Windows 11 x64.
- Real browser interception still needs a manual pass in Chrome, Edge, Brave and
  Opera; the native host, bridge, protocol and prompt contract are covered by
  automated tests.
- FTP runs on a single connection, so segmented speed gains do not apply there.
- A percentage limit follows a link down automatically but needs **Measure the
  link now** to climb back to a faster connection, because the limit hides the
  ceiling it is pinned under.
- Chrome, Edge and Firefox store installation remains outside the installer;
  extensions ship as ZIPs and an unpacked folder and are never installed
  silently.
- Features requested for this release and not implemented are listed in
  `ReleaseNotes.md` and `CHANGELOG.md`.
