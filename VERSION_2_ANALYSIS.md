# IDM Download Manager — Version 2.0 Analysis

**Document status:** Phase 1 complete (read-only analysis). No Version 1.0 source file was
modified, replaced, or deleted while producing this document.

**Analysis date:** 2026-11-01
**Analysed build:** 1.0.0 (schema version 3)
**Workspace:** `D:\IDM`
**Repository state:** not a git repository, so the backup is the only rollback point.

---

## 1. Executive summary

IDM Download Manager 1.0 is a working, Python 3 + PySide6 (Qt 6) desktop download manager
with a segmented HTTP/HTTPS download engine, SQLite persistence, three visual themes, a
Chrome/Edge/Firefox browser integration stack, an authenticated loopback bridge, a native
messaging host, a signature-verifying updater, and an Inno Setup installer.

The upgrade to 2.0 is feasible **without changing the framework**. The existing layering is
sound: UI, engine, persistence, browser integration and updater are separated enough to grow
independently.

The most important findings are:

| # | Finding | Impact |
|---|---------|--------|
| 1 | The prompt assumes C#/.NET; the actual editable project is Python/PySide6. | Framework is preserved. No rewrite. Version metadata is still emitted as 1.0.0.0 Windows resources. |
| 2 | 378 automated tests pass on the current tree (43.24 s). | Stable baseline for regression testing. |
| 3 | The build would currently fail its version-consistency gate: app is `1.0.0`, extensions are `1.1.0`. | Must be fixed before any 2.0 build. |
| 4 | The installed V1 folder contains stale C# artifacts (`IDM.Core.dll`, `IDM.UI.dll`, `IDM.UI.exe`) beside the Python binaries. | Upgrade must remove known-obsolete files; otherwise stale code can be launched. |
| 5 | Database migration has no automatic pre-migration backup. | Requirement gap. Migration must back up first. |
| 6 | The updater verifies signature/hash but has no rollback if the new build installs and then fails to start. | Requirement gap. Needs previous-build retention and health check. |
| 7 | Update signing configuration is empty (`GITHUB_OWNER`, `EXPECTED_PUBLISHER`, `MANIFEST_PUBLIC_KEY`) and all shipped artifacts are unsigned. | Production update/install cannot be certified until real inputs exist. |
| 8 | Several requested V2 features do not exist at all (clipboard monitor, tray notifications, smart manager, settings backup/restore, performance monitor, per-download scheduler). | Must be built and tested, not claimed. |
| 9 | The browser extension has no file-type filtering and reconnects are basic. | Extension upgrade work is required. |
| 10 | Current user data is small but real: 20 settings, 1 log row, 0 downloads, 0 queue entries. Integrity check: `ok`. | Backup is straightforward; data must still be preserved exactly. |

**Recommendation:** approve Phase 2 (backup) verification, then proceed with an incremental
2.0 upgrade. Do not attempt a rewrite. Do not ship until the unsigned/placeholder update
configuration is replaced with real release inputs or the update feature is explicitly marked
unconfigured in the release.

---

## 2. What Version 1.0 actually is

### 2.1 Stack

| Area | Technology | Evidence |
|------|------------|----------|
| Language | Python 3.11+/3.12 | `requirements.txt`, `.venv`, `main.py` |
| UI | PySide6 / Qt 6 Widgets | `idm/ui/*.py` |
| HTTP | `requests` | `requirements.txt`, `idm/engine/worker.py` |
| Database | SQLite via `sqlite3` | `idm/core/database.py` |
| Crypto (manifest signing) | `cryptography` (Ed25519) | `scripts/sign_manifest.py`, `idm/updater/*` |
| Packaging | PyInstaller | `IDM.spec` |
| Installer | Inno Setup 6 | `installer/IDM_Setup.iss` |
| Extensions | Manifest V3 (Chrome/Edge), Manifest V2 (Firefox) | `extensions/*/manifest.json` |
| Platform | Windows 10/11 x64, per-user install | `installer/IDM_Setup.iss` |

There are **no editable C# project files** in the workspace. The C# DLLs/EXE in the
*installed* folder are leftovers from an earlier prototype and are not part of this source
tree. They are treated as obsolete artifacts to be removed by the 2.0 upgrade.

### 2.2 Entry points

| Entry point | Purpose |
|-------------|---------|
| `main.py` | Desktop application; sets AppUserModelID, logging, theme, `MainWindow` |
| `native_host_main.py` | Standalone browser native messaging host |
| `updater_main.py` | Standalone updater process launched after the app exits |

### 2.3 Architecture

```
Presentation      idm/ui/  (MainWindow, toolbar, sidebar, download view,
                            delegates, status bar, dialogs, themes, icons)
                        |
Application       integrations/  (browser service, loopback bridge,
                                  native host, protocol validation)
                        |
Engine            idm/engine/  (manager -> worker -> segmented planner
                                + speed limiter)
                        |
Persistence       idm/core/    (database, migrations, settings, paths,
                                scheduler, download categorization, logging)
                        |
Platform          scripts/, installer/, IDM.spec, build_windows.ps1
```

Data flow for a browser download:

1. Extension pauses the browser download.
2. Extension sends a Native Messaging request (`request_download`).
3. Native host validates framing, request ID, browser, extension ID, URL, MIME, size and
   referrer (`integrations/protocol.py`).
4. Request is forwarded over the authenticated loopback bridge (`127.0.0.1`, per-run token).
5. GUI-thread service validates again, resolves the destination folder, adds the task.
6. Engine plans 1–16 HTTP Range segments, downloads, journals progress, verifies size, and
   renames the `.part` file atomically.
7. Extension cancels its own browser copy only after `download_accepted`.

---

## 3. Source inventory

### 3.1 Size

| Metric | Value |
|--------|-------|
| Python files outside `.venv`, `build`, `dist*` | 102 |
| Tests | 30 files, 378 tests |
| UI/engine/integration/source lines (approx.) | 26,659 including extensions and tests |

### 3.2 Key modules

| File | Lines | Role |
|------|-------|------|
| `idm/ui/main_window.py` | 1,283 | Application shell, menus, actions, update handoff |
| `idm/engine/worker.py` | 892 | HTTP transfer, ranges, retries, pause/resume, limiting |
| `idm/engine/manager.py` | 837 | Queue, concurrency, persistence, recovery |
| `idm/ui/dialogs/options.py` | 832 | Seven-tab settings dialog |
| `idm/core/database.py` | 483 | Schema, migrations, backup |
| `integrations/protocol.py` | 417 | Framing and strict validation |
| `idm/updater/updater.py` | 373 | Install/restart flow |
| `integrations/service.py` | 371 | Browser request acceptance |
| `installer/IDM_Setup.iss` | 358 | Inno Setup script |
| `idm/core/settings.py` | 343 | SQLite-backed settings |
| `integrations/bridge_server.py` | 302 | Authenticated loopback server |
| `idm/updater/package_verifier.py` | 295 | Hash + Authenticode verification |
| `idm/engine/segmented.py` | 260 | Segment plan + crash-safe journal |
| `idm/core/scheduler.py` | — | One-off pause/resume scheduling |
| `idm/core/speed_limiter.py` | — | Global and per-download leaky bucket |

### 3.3 Assets and packaging

| Path | Contents |
|------|----------|
| `assets/` | Application icon, branding images |
| `extensions/chrome`, `edge`, `firefox` | Extension source (MV3/MV2) |
| `installer/` | Inno Setup script and installer assets |
| `scripts/` | Release build, extension packaging, native host registration, manifest signing/validation |
| `tools/` | Branding asset generator |
| `update/latest.json` | Template update manifest (placeholder) |
| `IDM-Update-Server/` | Static update-host template and schema |
| `docs/` | Browser integration, store publishing, updates |
| `README.md`, `PACKAGING.md` | Current documentation |

---

## 4. Feature inventory (V1) and V2 mapping

Legend: **Implemented** = works and is tested; **Partial** = exists but does not meet the V2
requirement; **Missing** = no implementation found.

| Requested V2 capability | V1 state | Evidence / gap |
|-------------------------|----------|----------------|
| Smart Download Manager | **Missing** | No rule engine beyond extension→category mapping in `location_manager.py`. |
| Advanced scheduler | **Partial** | `idm/core/scheduler.py` supports only `pause_all` / `resume_all` one-off times. No per-download, recurring, or bandwidth scheduling. |
| Improved queue manager | **Partial** | `queue_seq` + priority + 10 concurrent; no reordering UI, batch edit, or queue groups. |
| Automatic recovery | **Partial** | Segment journal and restart-as-Paused restore exist; no opt-in automatic resume or integrity re-check UI. |
| Clipboard monitoring | **Missing** | README roadmap says “Not started”. |
| Advanced browser integration | **Partial** | Authenticated bridge, MV3 Chrome/Edge, MV2 Firefox, context menus, badge. Missing file-type filtering, richer reconnect/status, and Edge-specific install guidance is thin. |
| Notifications | **Missing** | No tray icon or completion notifications. |
| Bandwidth management | **Partial** | Global + per-download limit (`speed_limiter.py`); no schedule-based profiles. |
| Advanced categorization | **Implemented (basic)** | Extension→category mapping and configurable rules; no user-defined rule editor with tests beyond current. |
| History search | **Partial** | Table search and filters exist; no dedicated history view with date/status/category query. |
| Settings backup/restore | **Missing** | Only SQLite backup before updates; no user-facing export/import. |
| Update manager | **Partial** | HTTPS manifest, strict schema, SHA-256, Authenticode, optional Ed25519, staged updater. No rollback, no configured keys, no working production endpoint. |
| Error logging | **Implemented** | Rotating logs under `%APPDATA%\IDM Download Manager\logs`. No in-app log viewer. |
| Performance monitoring | **Missing** | No throughput/connection/health dashboard. |
| Accessibility | **Partial** | Qt widgets and keyboard shortcuts exist; no audit, labels, high-contrast, or scalable UI plan. |

### 4.1 Existing strengths to preserve

- Segmented downloads with 1–16 connections and 1 MiB minimum segment size.
- HTTP Range handling including 200/206/416 and redirect restriction to HTTP(S).
- Crash-safe segment journal with atomic replacement and strict validation.
- Cooperative pause/resume/cancel without killing the process.
- Retry with backoff and `Retry-After` honoring for 408/425/429/5xx.
- Global and per-download speed limiting.
- Queue persistence and 10-download concurrency cap.
- Three complete themes and a functional dashboard.
- Authenticated loopback bridge with token comparison via `hmac.compare_digest`.
- Strict native messaging validation (size limits, control characters, schemes, IDs).
- Database migration by `PRAGMA user_version` without destructive resets.
- Uninstaller preserves user data unless explicitly opted out.
- Real updater verification code (not a stub).

---

## 5. Download engine assessment

### 5.1 Strengths

- `idm/engine/segmented.py` plans segments with `MIN_SEGMENT_BYTES = 1 MiB` and
  `MAX_SEGMENTS = 16`; journals are validated before load.
- `idm/engine/worker.py` writes to `.idm.part`, verifies final size, and renames atomically.
- `idm/engine/manager.py` batches persistence (1.5 s) and throttles segment saves.
- Active downloads are restored as **Paused** after restart, which is safe.

### 5.2 Gaps for 2.0

1. No per-segment live progress display in the UI (aggregate only).
2. No adaptive connection reduction when the server throttles or returns errors repeatedly.
3. No disk-space preflight before starting a large download.
4. No checksum/verification option (server-provided SHA-256) beyond size verification.
5. Recovery is manual after restart; no “resume interrupted automatically” setting.
6. No explicit handling of servers that ignore Range on subsequent requests (fallback exists,
   but the UI does not explain the downgrade).
7. No test coverage for very large files or disk-full behavior.

---

## 6. Database and migration assessment

### 6.1 Current schema

- `PRAGMA user_version = 3`.
- Tables: `app_settings`, `download_logs`, `download_queue`, `download_segments`,
  `downloads`, `settings` (legacy), `sqlite_sequence`.
- V2 migration copied legacy `settings` into `app_settings` and added `download_segments`,
  `download_queue`, `download_logs`, plus download columns `connections`,
  `speed_limit_kbps`, `etag`, `last_modified`, `retry_count`.
- V3 added `source_browser`, `referrer`.
- Migration is additive and wrapped in a transaction; `sqlite3.Error` rolls back.

### 6.2 Live user data (read-only inspection)

| Item | Value |
|------|-------|
| Database | `%APPDATA%\IDM Download Manager\database\idm.sqlite3` |
| Integrity | `ok` |
| `app_settings` | 20 rows (theme `classic`, download dir under AppData, 3 concurrent, 12 connections, 3 retries, no speed limit, empty update URL/publisher) |
| `downloads` | 0 |
| `download_queue` | 0 |
| `download_segments` | 0 |
| `download_logs` | 1 |
| Legacy `settings` | 0 |
| Downloads folder | `%APPDATA%\IDM Download Manager\downloads` (empty) |

### 6.3 Gaps

1. **No automatic backup before migration.** `Database.__init__` migrates before any UI exists.
2. Migration tests exist (`tests/test_migrations.py`) but do not require a backup artifact.
3. No documented rollback procedure if a future migration partially succeeds.
4. No schema checksum/validation report stored with each migration.
5. No settings export/import (required for V2).

### 6.4 V2 migration plan (summary)

- Keep `SCHEMA_VERSION` monotonic; add version 4+ in additive steps only.
- Before migration: SQLite online backup to
  `%APPDATA%\IDM Download Manager\backups\pre-migration-v<from>-<timestamp>.sqlite3`,
  verify with `PRAGMA integrity_check`, and record row counts.
- Migrate in a single transaction; on error, close, restore the backup, and report.
- Add a migration report (from/to version, duration, counts, backup path) to logs.
- Never drop or recreate existing tables; never reset `user_version` downward.
- Test with real V1 database copies (schema 1, 2, 3) and fresh databases.

---

## 7. Browser integration and extension assessment

### 7.1 Current implementation

- Native host name `com.idm.native`; manifests installed at
  `%LOCALAPPDATA%\Programs\IDM\browser-integration\`.
- HKCU registration present for Chrome, Edge and Firefox.
- Chrome/Edge MV3 manifests use a pinned key and extension ID
  `ljckgbgnolmopacdgmmgaijleadcmpgn`; Firefox uses `idm-browser-integration@idm.local`.
- Loopback bridge binds `127.0.0.1`, random port, per-run URL-safe token stored under
  `%APPDATA%\IDM Download Manager\runtime\browser_bridge.json`, limited connections and
  authentication failures, closed on malformed or oversized frames.
- Protocol limits messages to 1 MiB, validates request IDs, URLs, filenames, MIME types,
  referrers, sizes, browsers and extension IDs.
- Background script pauses/cancels/resumes browser downloads based on the IDM response;
  context menus and badge notifications exist.
- Popup shows connection state, interception toggles, active/queued/total counts, save folder,
  recent transfers, Open IDM, Settings and Test Connection.

### 7.2 Gaps

1. **Version mismatch:** extension manifests are `1.1.0`, application is `1.0.0`. The build
   script requires equality and will fail.
2. No file-type filtering UI or rule storage in the extension.
3. Reconnect/backoff and “IDM not running” handling are basic.
4. No explicit Edge install documentation parity with Chrome.
5. No extension-side validation tests beyond packaging tests.
6. Firefox MV2 is maintained but not feature-parity tested.

### 7.3 V2 direction

- Keep Native Messaging and MV3; do not weaken validation.
- Add file-type include/exclude rules, per-type “ask me” behavior, and a settings sync path.
- Add service-worker keepalive/reconnect with bounded retries and clear popup states.
- Add Edge-specific installation/registration checks.
- Ensure extension version is derived from or checked against `idm/version.py`.

---

## 8. UI assessment

### 8.1 Current state

The reviewed screenshots show a functional three-pane dashboard:

- toolbar, sidebar with counts, search field, table with category icons, progress bars,
  status dots;
- classic and dark themes render correctly;
- seven-tab Options dialog;
- Add Download dialog with URL probe, filename, folder, category and priority.

### 8.2 Gaps versus the V2 requirement

1. No layout switching (compact/comfortable/responsive) and no narrow-window strategy.
2. No dedicated history view, no advanced filter bar (date/status/category/size).
3. No tray icon, no toast notifications.
4. No performance panel (speed graph, connections, queue health).
5. No accessibility pass (tab order, accessible names, contrast, scaling).
6. Options General page is largely empty; several tabs need real controls.
7. No clipboard monitor indicator.
8. No settings backup/restore UI.
9. Visual identity is serviceable but not a deliberate V2 refresh (spacing, icon set,
   empty states, headers).

---

## 9. Updater assessment

### 9.1 Strengths

- HTTPS-only manifest with trusted-host allowlist and DNS-only host check.
- Strict manifest schema and size limits.
- SHA-256 and Windows Authenticode status/publisher verification.
- Optional Ed25519 manifest signature using `cryptography`.
- Separate staged `IDM_Updater.exe`; waits for parent exit; re-verifies before install.
- Silent Inno Setup install with log; restarts the app; cleans staging.

### 9.2 Gaps

1. `GITHUB_OWNER`, `EXPECTED_PUBLISHER`, `MANIFEST_PUBLIC_KEY` are empty; sample manifests
   contain placeholder URLs and zero hashes.
2. No verified rollback if the new version installs but fails to start.
3. No health check after restart (window appears, DB opens, version matches manifest).
4. No update channel UI beyond a stored setting.
5. No production signing key or certificate; all built artifacts are unsigned.

### 9.3 V2 direction

- Keep verification; add previous-build retention and a post-update health check.
- If health check fails, restore the retained build and reopen the app.
- Refuse production updates until real publisher, manifest URL, and public key are provided.
- Add an explicit “update not configured” state instead of shipping placeholders.

---

## 10. Installer and build assessment

### 10.1 Current installer

- AppId `{A52627A1-E4C9-456C-A397-BB6D9FD48F1B}` (stable across upgrades).
- Per-user default, x64, Windows 10+.
- Reuses previous install directory, tasks and privileges.
- Optional browser tasks register HKCU 32/64-bit native host manifests.
- Ships extensions as ZIPs; does not silently install them.
- Uninstaller preserves `%APPDATA%\IDM Download Manager` unless the user opts out or
  `/REMOVEDATA` is passed.

### 10.2 Gaps

1. Output is `IDM_Setup.exe`; V2 requires `IDM-Setup-2.0.exe`.
2. No explicit V1 detection / “upgrade detected” page.
3. Obsolete files are not removed; the installed folder still contains C# artifacts.
4. No repair-specific messaging beyond Inno’s default.
5. Version consistency gate currently fails because extensions are `1.1.0`.
6. No post-install verification of native host manifests or shortcuts.

### 10.3 Build pipeline

`build_windows.ps1` creates/reuses `.venv`, installs requirements, cross-checks versions in
`version_info*.txt`, extension manifests and installer, runs compile/import checks and tests,
packages extensions, builds with PyInstaller, runs Inno Setup, and prints SHA-256.

**Blocking defect:** it requires extension manifest version == app version. Chrome/Edge/
Firefox are `1.1.0`, app is `1.0.0`. A 2.0 build must align all of them.

---

## 11. Test baseline

Command:

```bat
.venv\Scripts\python.exe -m pytest tests -q
```

Result on 2026-11-01:

```text
378 passed in 43.24s
```

Coverage areas:

- engine, segmented planning/journals, persistence, migrations;
- browser bridge, protocol, native host (unit and process);
- update checker, manifest schema, signed manifest, downloader, package verifier, updater;
- UI construction, app layout, update UI;
- extension packaging, release scripts, version manager, location rules, registration.

Not covered:

- Windows 10-specific execution;
- actual signed production update and post-update rollback;
- V2 features (clipboard, tray, scheduler v2, settings export/import, performance monitor);
- V1→V2 installer detection end-to-end;
- very large files, disk-full, and long-running stability.

---

## 12. Defects and risk register

| ID | Severity | Defect / risk | Planned action |
|----|----------|---------------|----------------|
| R1 | High | Build version gate fails (extensions 1.1.0 vs app 1.0.0) | Align versions to 2.0.0 and add a single version source check. |
| R2 | High | No automatic pre-migration backup | Add verified backup before any schema change. |
| R3 | High | Stale C# artifacts remain in installed folder | Installer removes known obsolete files during upgrade. |
| R4 | High | No rollback after a failed post-update health check | Retain previous build and restore on failure. |
| R5 | High | Update keys/URL/publisher empty; artifacts unsigned | Block production release until real inputs are provided. |
| R6 | Medium | Extension lacks file-type filtering | Implement and test filtering. |
| R7 | Medium | Scheduler only pause/resume all | Build per-download time/bandwidth schedules. |
| R8 | Medium | No clipboard monitor, tray notifications, settings backup/restore, performance panel | Implement with tests. |
| R9 | Medium | No accessibility audit | Add keyboard/tab order, accessible names, contrast checks. |
| R10 | Low | README test count stale | Update documentation at release. |
| R11 | Low | No in-app log viewer | Optional; keep file logs if time-boxed. |
| R12 | Low | No disk-space preflight | Add check before starting downloads. |

---

## 13. Preservation strategy (V1 → V2)

The following are contractual and must not change without explicit approval:

1. **Framework:** Python 3 + PySide6. No C#/.NET migration.
2. **User data location:** `%APPDATA%\IDM Download Manager`. Do not merge with commercial
   IDM’s `%APPDATA%\IDM`.
3. **Database:** never reset; additive migrations only; backup before migration.
4. **Downloads:** never delete user downloads or `.idm.part`/journal files except when the user
   cancels or removes a download and confirms.
5. **Installer identity:** keep the same AppId for in-place upgrades; preserve previous
   install directory and tasks.
6. **Uninstall behavior:** preserve user data unless explicitly requested otherwise.
7. **Browser protocol:** keep Native Messaging host name `com.idm.native` and existing
   extension IDs so upgrades do not break registration.
8. **Update security:** keep HTTPS-only, hash and signature verification; never execute an
   unverified package.
9. **Versioning:** semantic versioning; 2.0.0 is the single source in `idm/version.py`,
   Windows version resources, installer, extensions and manifest.

---

## 14. Proposed V2 work breakdown

| Phase | Work | Acceptance gate |
|-------|------|-----------------|
| 2 | Complete backup + restore verification | All hashes match; restored DB integrity `ok`; restored source runs tests |
| 3 | UI redesign and themes | Dashboard, toolbar, sidebar, filters, history view, light/dark/classic, responsive states |
| 4 | Engine improvements | Per-segment progress, disk preflight, checksum option, adaptive connections, recovery tests |
| 5 | V2 features | Clipboard monitor, tray notifications, scheduler v2, queue v2, settings export/import, performance panel, accessibility |
| 6 | Browser extensions | File-type filtering, reconnect, Edge guidance, version alignment, packaging tests |
| 7 | Database v4 + migration | Pre-migration backup, additive migration, rollback test, V1→V2 preservation test |
| 8 | Update manager v2 | Health check, previous-build retention, rollback, unconfigured state, signature tests |
| 9 | Installer v2 | `IDM-Setup-2.0.exe`, V1 detection, obsolete-file cleanup, repair, data preservation |
| 10 | Testing | Full suite + installer scripts + Windows 10/11 validation evidence |
| 11 | Release packaging | `IDM_V2_Release/` complete, checksums, docs, no placeholders |
| 12 | Final review | Report, blockers, approval |

---

## 15. Backup plan and restore verification

### 15.1 Required backup tree

```
Backup/
  Version_1.0_Source/
  Database/
  Settings/
  Configuration/
  Installer/
  Backup_Manifest.json
```

### 15.2 What will be included

- **Version_1.0_Source:** editable source, tests, docs, assets, extensions, scripts, tools,
  requirements, version resources, `IDM.spec`, `build_windows.ps1`, README/PACKAGING.
  Excluded: `.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, generated `build/`,
  `dist*/`, and the empty app `downloads/` package output.
- **Database:** SQLite online backup plus schema dump, integrity report, row counts and
  previously created pre-update backups if present.
- **Settings:** `%APPDATA%\IDM Download Manager\settings`, runtime token descriptor (if any),
  logs, and an exported snapshot of relevant HKCU native-host registration. User downloads
  are **not moved or deleted**; their location is recorded instead.
- **Configuration:** `config.py`, `version_info*.txt`, update templates, `IDM.spec`,
  build/release scripts, native host manifests, extension manifests and IDs.
- **Installer:** installer source/assets, built `IDM_Setup.exe`, PyInstaller output, extension
  ZIPs, and a copy of the installed V1.0 folder (including stale C# files) for forensic
  rollback.
- **Backup_Manifest.json:** every file with relative path, size, SHA-256, timestamp, source
  path, exclusions, environment details, database verification results, and restore steps.

### 15.3 Restore verification criteria

1. Every manifest hash recomputes identically.
2. The backed-up database opens, passes `PRAGMA integrity_check`, reports schema version 3,
   and matches recorded row counts.
3. A copy of the backup source tree is restored to a temporary directory and a test subset
   runs successfully from it.
4. The installed-folder copy is byte-identical to the source folder.
5. Only after these checks pass may Phase 3 begin.

### 15.4 Verification results (2026-11-01)

Backup completed at `D:\IDM\Backup` using `build/backup_v1.py`.

| Check | Result |
|-------|--------|
| Backup files recorded in manifest | 509 |
| Backup size | 260,202,230 bytes |
| Manifest SHA-256 verification | 509 / 509 matched, 0 failures |
| Independent hash recomputation | 509 / 509 matched |
| Live source vs backup parity | 172 / 172 files matched |
| Installed folder vs backup parity | 223 / 223 files matched |
| Database integrity (`PRAGMA integrity_check`) | `ok` |
| Database schema version | 3 |
| Database row counts match source | Yes (20 settings, 1 log, 0 downloads) |
| App-level opening of restored database | Success; theme restored, 20 settings |
| Full test suite from restored source copy | **378 passed in 45.41 s** |
| Independent restored-source subset | **31 passed in 1.35 s** |

The installed V1 folder copy includes the stale C# artifacts, so a byte-level rollback is
possible even though those files must be removed by the 2.0 installer.

**Backup verified. No Version 1.0 source modification was made.**

---

## 16. Blockers requiring user input

These do not block the backup or UI work, but they block a **certified production release**:

1. **Update hosting:** a real HTTPS manifest endpoint (GitHub owner/repo or other trusted
   host). Until supplied, updates must remain visibly unconfigured.
2. **Code signing:** a certificate and publisher identity for `IDM.exe`,
   `IDM_NativeHost.exe`, `IDM_Updater.exe` and `IDM-Setup-2.0.exe`. Without it, artifacts
   remain unsigned and SmartScreen/Authenticode checks cannot pass.
3. **Manifest signing:** an Ed25519 keypair; the public key must be embedded in `config.py`,
   the private key must stay outside the repository.
4. **Windows validation:** access to a Windows 10 environment in addition to the current
   Windows 11-class machine for installer/upgrade testing.

---

## 17. Approval checklist

- [x] Existing architecture analysed
- [x] Source and feature inventory recorded
- [x] Database, installer, updater and browser integration assessed
- [x] Baseline tests executed (378 passed)
- [x] Risks and preservation contract documented
- [x] Backup created (`Backup/`, 509 files)
- [x] Backup hashes verified (509/509)
- [x] Database restore verified (integrity `ok`, schema 3, counts match)
- [x] Source restore verified (378 tests passed from restored copy)
- [ ] User approval to begin Phase 3

**No Version 1.0 source modification has been made.** The only additions are
`VERSION_2_ANALYSIS.md`, `Backup/`, and the build-time helper `build/backup_v1.py`.
