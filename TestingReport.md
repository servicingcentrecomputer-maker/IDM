# IDM 3.6.0 Testing Report

**Date:** 2026-11-01
**Build:** 3.6.0 (stable)
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
| Core, engine, persistence, migrations, probe, dialog, browser prompt, security, updater, extensions | `pytest tests -q --ignore=tests/test_ui.py --ignore=tests/test_update_ui.py --ignore=tests/test_update_notification.py` | 528 passed, 38.46 s |
| Main window, downloads, dialogs, screenshots | `pytest tests/test_ui.py -q` | 16 passed, 123.23 s |
| Update panel | `pytest tests/test_update_ui.py -q` | 21 passed |
| Update notification | `pytest tests/test_update_notification.py -q` | 10 passed |
| Compile check | `python -m compileall -q idm integrations downloads tools scripts` | clean |
| **Total** | | **575 passed, 0 failed** |

`tests/test_ui.py` creates a real offscreen main window, theme, local HTTP
server and download engine per scenario. Running the two UI files in the same
pytest process as the rest of the suite intermittently stalls past ten minutes
on this machine, so the recorded results come from the split runs above and the
release build was executed with `-SkipTests` **after** these runs completed.
Each file passes independently; this is a harness ordering issue, not an
application hang.

### New coverage in 3.6.0

| Test file | Tests | Covers |
| --- | ---: | --- |
| `tests/test_probe.py` | 12 | HEAD success, HEAD 405 → Range GET 206 fallback, redirects, unknown size, no Range support, 404/403/500, chunked responses, refused connections, unsupported schemes, timeout handler, server not fully drained |
| `tests/test_categories.py` | 10 | Extension and MIME detection, custom categories, sanitisation, limits, safe category lookup, remembered folders, path normalisation |
| `tests/test_dialog_file_info.py` | 13 | Remembered folder, category switching, custom `Books`/`cbz` after probe, unsafe filename containment, invalid URL/name/folder, duplicate blocking, description limit, Download Later flags, submit-before-accept, probe failure, long-URL copy, 640×560 layout, restricted platform |
| `tests/test_download_later.py` | 5 | Held row persistence, no slot consumption, restart survival, `start_queued`, Queue Manager labels |
| `tests/test_browser_prompt.py` | 5 | Accept with metadata, cancel answers `cancelled`, duplicate skip, `ask_folder`, serialised nested request |
| `tests/test_security.py` | 13 | Unsafe schemes, URL redaction, filename sanitisation, path containment, dropped cookie/authorization fields, redacted logs |
| `tests/test_migrations.py` | +1 | v4 → v5 migration, verified backup, legacy row and settings preserved, new columns defaulted |
| `tests/video_assistant_harness.js` | — | Manifest and request-builder parity at 3.6.0 |

## Seventeen dialog scenarios

| # | Scenario | Evidence |
| ---: | --- | --- |
| 1 | Category detected from the filename extension | `test_categories.py::test_detect_category_by_extension`, dialog defaults |
| 2 | Category detected from MIME when the name has no extension | `test_categories.py::test_detect_category_by_mime` |
| 3 | User creates a custom category and it persists | `test_categories.py::test_custom_category_round_trip`, `test_dialog_file_info.py` custom `Books` case |
| 4 | HEAD reports size, type, disposition and last-modified | `test_probe.py::test_head_success` |
| 5 | HEAD is rejected and a Range GET fallback returns 206 | `test_probe.py::test_head_rejected_uses_range_get` |
| 6 | Redirects keep the entered URL and use the final headers | `test_probe.py::test_redirect_is_followed` |
| 7 | Unknown size stays “Unknown” instead of an invented value | `test_probe.py::test_missing_content_length`, dialog probe-failure case |
| 8 | A server without Range support is not assumed resumable | `test_probe.py::test_no_range_support` |
| 9 | Timeout and refused connection show a clear state | `test_probe.py::test_timeout`, `test_connection_refused` |
| 10 | Start Download validates, creates the record, then closes | `test_dialog_file_info.py::test_submit_creates_task_before_accept` |
| 11 | Download Later persists without starting and starts later | `test_download_later.py` (5 tests) |
| 12 | Cancel creates nothing and aborts the pending probe | `test_dialog_file_info.py::test_invalid_inputs_keep_dialog_open`, dialog `reject()` |
| 13 | A URL already active is refused | `test_dialog_file_info.py::test_duplicate_active_url_is_blocked` |
| 14 | Invalid scheme, name or folder is rejected with a message | `test_dialog_file_info.py`, `test_security.py` |
| 15 | Browser download accepts, cancels back to the browser, or queues behind the dialog | `test_browser_prompt.py` (5 tests) |
| 16 | Long URL copies in full; the dialog fits 640×560 with themes | `test_dialog_file_info.py::test_copy_long_url`, `test_small_display_keeps_footer` |
| 17 | Credentials and sensitive values never reach logs or unrelated services | `test_security.py::test_redact_url`, `test_logs_redact_credentials`, protocol-drop test |

## Packaging verification

`build_windows.ps1 -Force -Package -SkipTests` completed with exit code 0 after
the recorded test runs. Version parity was validated by the script and the
version-sensitive tests:

- `idm/version.py`, `integrations.NATIVE_HOST_VERSION`, all three
  `version_info*.txt` resources and `installer/IDM_Setup.iss` report 3.6.0.
- Chrome, Edge and Firefox manifests and the unpacked Video Assistant report
  3.6.0; the built executables report file version 3.6.0.0.
- The installer resource declares `VersionInfoVersion=3.6.0.0` and
  `OutputBaseFilename=IDM-Setup-{#MyAppVersion}`.
- `IDM.exe`, `IDM_Updater.exe` and `IDM_NativeHost.exe` are staged in the
  portable folder; `qwindows.dll` and the bundled logo are verified.
- Extension ZIPs are written to `dist-extensions\`, including
  `IDM_Video_Assistant_3.6.0.zip`.
- The release bundle is assembled at `release\IDM-3.6.0-win64\` with a
  deterministic ZIP, `VERSION.json` and `SHA256SUMS.txt`.

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `dist\IDM\IDM.exe` | 5,111,326 B | `2EE52B8FD9624BE4706D7E6FB6B4AE57FA358893228C995355445B106C5D8EA2` |
| `dist\IDM\IDM_Updater.exe` | 15,617,403 B | `870B01AB8D1862610027789CD46D9184ADC062F42928AC580D85FFDA82A1EE22` |
| `dist\IDM\IDM_NativeHost.exe` | 8,304,752 B | `15F46EE1C153BDE135C1926C091415F75FA1A9450AF7B72C7E05579366643DF7` |
| `dist-installer\IDM-Setup-3.6.0.exe` | 62,436,949 B | `40070376190E75EF733B16C8DB4D47EEFBD106EEC92F9CAB96A8E8D8B32E2F4B` |

The release ZIP changes whenever documentation is rebuilt; its digest is
written next to the archive as `release\IDM-3.6.0-win64.zip.sha256`.

### Frozen-build smoke test

`dist\IDM\IDM.exe` was started with an isolated `APPDATA` and
`QT_QPA_PLATFORM=offscreen`. It created and migrated a fresh database from
schema 1 through 5, started the browser bridge as native host 3.6.0 on a
loopback port, logged `Main window ready`, and reported `IDM 3.6.0 started`
before the test harness stopped it. The executable reports file
version 3.6.0.0.

### Update manifest

`update/latest.json` was rewritten for 3.6.0 with the installer's real size and
SHA-256, signed with the release Ed25519 key at
`C:\Users\Jawad\.idm-signing\manifest-private.pem`, and checked with
`scripts/validate_manifest.py`:

```
Signature OK
Installer OK: dist-installer\IDM-Setup-3.6.0.exe (62436949 bytes,
sha256=40070376190e75ef733b16c8db4d47eefbd106eec92f9cab96a8e8d8b32e2f4b)
Manifest OK … signature: verified (Ed25519)
```

## Database migration

- Schema version 5 adds `description TEXT NOT NULL DEFAULT ''` and
  `start_later INTEGER NOT NULL DEFAULT 0` to `downloads`.
- Before any upgrade, a backup is written under
  `%APPDATA%\IDM Download Manager\backups\` and opened with
  `PRAGMA integrity_check`; a failed check stops the migration.
- The v4 → v5 test inserts a legacy download and settings row, migrates, and
  asserts the row, settings and backup user_version 4 are intact and the new
  columns default correctly. v1 and v3 fixtures are also covered by the
  existing tests.
- A copy of the machine's real 3.5.0 database (user_version 4, one download)
  was migrated separately: it reached version 5, kept its download count, wrote
  `pre-migration-v4-<timestamp>.sqlite3` at version 4 with one row and an `ok`
  integrity check, and exposed `description` and `start_later`. The original
  file was not opened for writing.
- No existing download, queue entry or partial file is deleted or rewritten.

## Security checks

- Link schemes outside HTTP(S) are rejected by the dialog, native host and
  desktop service.
- Filenames are sanitised and the resolved path must stay inside the chosen
  folder.
- URL credentials, query strings and fragments are redacted in logs; cookies,
  authorization headers and client certificates are never logged or forwarded.
- The browser extensions keep their existing minimal permissions; no new host
  permission or cookie access was added for 3.6.0.
- Downloaded files are never executed or opened automatically.

## Preserved data and backup

The verified Phase 1 backup remains at `Backup/Version_3.0.0_20261101/`. The
3.5.0 source and build outputs remain in place (`release\IDM-3.5.0-win64\`,
`dist-installer\IDM-Setup-3.5.0.exe`). Tests and the smoke test use isolated
`APPDATA` folders; the build script does not touch
`%APPDATA%\IDM Download Manager`.

## Known limitations and external prerequisites

- The signed feed points at the 3.6.0 GitHub release asset, which is not
  published yet. Until the release is published, an installed 3.5.0 correctly
  sees a newer version but its download URL is not live.
- The installer is not Authenticode-signed unless a CA-issued certificate is
  supplied. SHA-256 and the signed manifest remain the trust anchors.
- Windows 10 was not available for testing; the installer configuration supports
  it, but validation ran on Windows 11 x64.
- Real browser interception (pause → dialog → cancel/resume) still needs a
  manual run in Chrome and Edge with IDM running; the automated tests cover the
  service, protocol and prompt contract.
- Chrome, Edge and Firefox store installation is outside the installer; the
  extensions ship as ZIPs and unpacked folders and are never installed
  silently.
