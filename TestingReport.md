# IDM 3.6.1 Testing Report

**Date:** 2026-11-02
**Build:** 3.6.1 (stable)
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
| All tests (core, engine, migrations, probe, dialogs, browser prompt, security, updater, extensions, main window) | `python -m pytest tests -q` inside `build_windows.ps1` | **582 passed, 0 failed** in 1467.09 s |
| Final UI module rerun after the Options default-size adjustment | `pytest tests/test_ui.py -q` | 19 passed, 180.91 s |
| Version consistency after the 3.6.1 bump | `pytest tests/test_extensions_packages.py tests/test_release_notes.py -q` | 20 passed, 0.65 s |

The full-suite run is the release gate used by `build_windows.ps1`; it completed
with exit code 0 and collected all 582 tests, including the three new UI tests.
It is a single-process run — the earlier split-run workaround is no longer
needed on this machine.

### New coverage in 3.6.1

| Test | Covers |
| --- | --- |
| `test_ui.py::test_completion_dialog_reports_real_details` | The completion window shows the record's real size, completion time, source host and average speed; Open File is disabled when the path is missing; the remember checkbox writes `show_completion_dialog`. |
| `test_ui.py::test_completion_event_opens_and_cleans_up_dialog` | A completed download opens exactly one window, respects the disabled setting and is removed from the registry after closing. |
| `test_ui.py::test_custom_categories_appear_in_sidebar_and_filter` | A user category appears in the sidebar, filters the table, reports counts and keeps its selection after a refresh. |
| `test_ui.py` shell test (updated) | Toolbar includes Stop All and Delete Completed; menus and Tasks actions are present. |

## Visual review

`tests/render_ui.py` rendered the real widgets on the native Windows Qt
platform (not offscreen) into `build\ui-check\`:

| Artifact | What was checked |
| --- | --- |
| `native-dashboard-classic.png`, `native-dashboard-light.png`, `native-dashboard-dark.png` | Seven-column table, status pills, rounded progress meters, category subtitles, file icons, sidebar counts, menus, toolbar and the `IDM 3.6.1` readouts in all three themes. |
| `native-complete-dark.png`, `native-complete-classic.png` | Download Complete layout, real details card, Open File / Open Folder / Close actions and the remember checkbox. |
| `native-add-dialog.png` | Download File Info layout and real server metadata. |
| `native-options.png`, `native-options-themes.png` | Options tabs are fully visible after the 940×640 default size (all seven labels); theme cards preview correctly. |
| `native-progress-dark.png`, `native-about.png`, `native-queue.png`, `native-scheduler.png`, `native-empty-classic.png` | Progress dialog, About version 3.6.1, queue/scheduler and the empty state. |

The screenshots were inspected manually before release. No fake or placeholder
transfer values are rendered: every size, speed, ETA, completion time and total
comes from the engine or the stored `DownloadItem`.

## Packaging verification

`build_windows.ps1 -Force -Package` completed with exit code 0. The first pass
reached Inno Setup and stopped because Inno Setup 7 is installed per user at
`C:\Users\Jawad\AppData\Local\Programs\Inno Setup 7` rather than in Program
Files; the build was resumed with that path. Tests and PyInstaller had already
succeeded in the first pass, and the final pass rebuilt and repackaged without
running tests again.

- `idm/version.py`, `integrations.NATIVE_HOST_VERSION`, all three
  `version_info*.txt` resources and `installer/IDM_Setup.iss` report 3.6.1;
  `IDM.exe` reports file version 3.6.1.0.
- Chrome, Edge and Firefox manifests and the unpacked Video Assistant report
  3.6.1; the installer resource reports 3.6.1.
- The installer declares `VersionInfoVersion=3.6.1.0` and
  `OutputBaseFilename=IDM-Setup-{#MyAppVersion}`.
- `IDM.exe`, `IDM_Updater.exe` and `IDM_NativeHost.exe` are staged in the
  portable folder; `qwindows.dll` and the bundled logo were verified by the
  build.
- Extension ZIPs were written to `dist-extensions\`, including
  `IDM_Video_Assistant_3.6.1.zip`.
- The release bundle is assembled at `release\IDM-3.6.1-win64\` with
  `VERSION.json`, `ReleaseNotes.md`, `TestingReport.md` and
  `SHA256SUMS.txt`.

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `dist\IDM\IDM.exe` | 5,133,666 B | `2052C058266BD375CAAC8D6CCAA3A332B192BE2401F63A577F899D09F40C4F65` |
| `dist\IDM\IDM_Updater.exe` | 15,616,401 B | `E14F02E4D08201389045A3561E1AF1CAD20CF35ADBBA9D1AABCFC07D0A2FC03C` |
| `dist\IDM\IDM_NativeHost.exe` | 8,304,718 B | `F95D76119F7325CE15154EE128635ABA80EB307FFC21D5BF63311ECD0C4EEE0D` |
| `dist-installer\IDM-Setup-3.6.1.exe` | 62,466,466 B | `51B8F1F7B2FAF304C6A12B30496AE8792DFDF48ADDE166B6FB79CB20D7FD501C` |

The release ZIP changes when documentation is rebuilt; its digest is written
next to the archive as `release\IDM-3.6.1-win64.zip.sha256` and is not repeated
here because this report is itself inside the bundle.

### Frozen-build smoke test

`dist\IDM\IDM.exe` was started with an isolated `APPDATA`
(`build\smoke-3.6.1`) and `QT_QPA_PLATFORM=offscreen`. The frozen process:

- created a fresh SQLite database and migrated it from schema 1 through 5;
- started the browser bridge as native host **3.6.1** on a loopback port;
- logged `Main window ready` and `IDM 3.6.1 started (data: …)`;
- was then stopped by the harness. The executable reports file version 3.6.1.0.

### Installer

`IDM-Setup-3.6.1.exe` was compiled by Inno Setup 7 and its version resource was
verified. A silent install was **not** re-run on this machine in this session:
the installer script and AppId are unchanged from 3.6.0, and running it would
overwrite the existing native-host registrations and the installed application
for the current user. The silent install, launch, uninstall, upgrade and data
preservation results recorded for 3.6.0 still apply; re-validate the installer
on a clean Windows 10/11 machine or VM before publishing.

### Update manifest

`update/latest.json` was deliberately **not** rewritten for 3.6.1: it still
signed-advertises 3.6.0. An installed 3.6.1 is newer than the feed, so the Update
Center offers no downgrade. Publishing 3.6.1 requires re-signing the manifest
with the release Ed25519 key and publishing the new installer; see
`docs/UPDATES.md`.

## Database and user data

- No schema change ships in 3.6.1; schema version stays 5.
- The frozen smoke test exercised the full empty-database creation path
  (1 → 2 → 3 → 4 → 5) in an isolated profile.
- Tests and the smoke test never touched `%APPDATA%\IDM Download Manager`.
- The original 3.6.0 binaries were preserved before the rebuild:
  `Backup\Release_3.6.0_PreRedesign\IDM-3.6.0.exe`
  (`9c5e98f6c63121ad89241994c14108340e07daa6fe9c01aac79cc009169bae57`) and
  `Backup\Release_3.6.0_PreRedesign\IDM-Setup-3.6.0.exe`
  (`a725d44dd55423d73c317dd84d565f7ccc9b97bbed1419618e5dc53f0138e85a`),
  byte-identical to the files that were replaced in `dist\IDM\` (the 3.6.0
  installer also remains in `dist-installer\`).

## Security checks

- Link schemes outside HTTP(S) remain rejected by the dialog, native host and
  desktop service; no validation code changed in this release.
- Filenames are sanitised and resolved paths stay inside the chosen folder.
- Logs still redact URL credentials, query strings and fragments; cookies and
  authorization headers are never logged.
- Browser extensions keep their existing minimal permissions.
- Downloaded files are never executed or opened automatically; the completion
  window opens a file only when the user clicks **Open File**.
- The installer and executables are unsigned; SHA-256 and the signed update
  manifest remain the trust anchors.

## Known limitations

- Windows 10 was not available for testing; the installer configuration
  supports it, but validation ran on Windows 11 x64.
- The installer is unsigned until a CA-issued Authenticode certificate is
  configured.
- Real browser interception (pause → dialog → cancel/resume) still needs a
  manual pass in Chrome and Edge; the native host, bridge, protocol and prompt
  contract are covered by automated tests.
- The signed update feed still advertises 3.6.0 and was not re-signed.
- Chrome, Edge and Firefox store installation remains outside the installer;
  extensions ship as ZIPs and an unpacked folder and are never installed
  silently.
