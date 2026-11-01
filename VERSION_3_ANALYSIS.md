# IDM 3.0.0 — Implementation Report (Phase 1)

**Date:** 2026-11-01
**Analysed version:** 2.0.1 (schema version 3)
**Target:** 3.0.0
**Status:** read-only analysis and verified backup complete. No application source was modified.

---

## 1. Executive summary

The editable project is **Python 3 + PySide6 (Qt 6)**, not C#/.NET. The prompt's
C#/.NET assumption does not match the repository. Rewriting in C# would be an
unrelated replacement and would break the preservation requirement, so 3.0.0 stays
on Python/PySide6 and upgrades the existing architecture in place.

The existing system is mature:

| Area | Current state |
|------|---------------|
| Desktop shell | PySide6, toolbar + category sidebar + table + status bar |
| Download engine | Segmented HTTP/HTTPS, 1–16 connections, pause/resume, retry/backoff, speed limits |
| Persistence | SQLite, additive migrations, schema v3, pre-update backup |
| Browser integration | MV3 Chrome/Edge + MV2 Firefox, native messaging, authenticated loopback bridge |
| Updates | HTTPS manifest, Ed25519 manifest signature, SHA-256, Authenticode, staged updater, rollback |
| Installer | Inno Setup 6, stable AppId, per-user, data-preserving uninstall |
| Tests | **460 passed in 63.59 s** (baseline, current tree) |

The upgrade is feasible without a framework change.

---

## 2. Verified baseline and backup

### 2.1 Baseline tests

```text
.venv\Scripts\python.exe -m pytest tests -q
460 passed in 63.59s
```

### 2.2 Backup

Created with `build/backup_v2.py`:

- `Backup/Version_2.0.1_Source/` — editable source snapshot (196 files total backup).
- `Backup/Version_2.0.1_Data/idm.sqlite3` — SQLite online backup.
- `Backup/Version_2.0.1_Data/logs/` — application and native-host logs.
- `Backup/Version_2.0.1_Data/Database_Report.json` — integrity and row counts.
- `Backup/V2_0_1_Backup_Manifest.json` — size and SHA-256 for every file.
- `Backup/V2_0_1_RESTORE.md` — restore procedure.

Verification results:

| Check | Result |
|-------|--------|
| Files hashed and re-read | 196 / 196, 0 failures |
| Total bytes | 1,727,715 |
| Live database integrity | `ok` |
| Live schema version | 3 |
| Settings / downloads / queue / segments / logs | 30 / 0 / 0 / 0 / 1 |
| Restored database integrity | `ok`, schema 3, 30 settings |
| Tests run from restored source copy | 22 passed (migrations, persistence, engine) |

**Backup approved as the rollback point. No V2 source was changed.**

---

## 3. Current architecture (files that matter for V3)

| Layer | Files | Notes |
|-------|-------|-------|
| Entry points | `main.py`, `native_host_main.py`, `updater_main.py` | Desktop, browser host, post-exit updater |
| UI | `idm/ui/main_window.py` (1,685 lines), `sidebar.py`, `download_view.py`, `toolbar.py`, `delegates.py`, `theme.py`, dialogs | Single download table + category sidebar |
| Model | `idm/models/download_item.py`, `table_model.py` | 6 columns; category derived from extension |
| Engine | `idm/engine/worker.py` (892), `manager.py` (837), `segmented.py` | Range segments, journal, retry, limits |
| Persistence | `idm/core/database.py` (483), `settings.py`, `paths.py`, `scheduler.py` | Schema v3, settings in SQLite |
| Browser | `integrations/protocol.py` (417), `native_host.py`, `message_handler.py`, `service.py`, `bridge_server.py`, `registration.py` | Host `com.idm.native`, strict validation |
| Extensions | `extensions/chrome`, `extensions/edge`, `extensions/firefox` | MV3 chrome downloads interception |
| Updates | `idm/updater/*` (17 modules) | Manifest, signature, hash, Authenticode, rollback |
| Packaging | `IDM.spec`, `build_windows.ps1`, `installer/IDM_Setup.iss` | `IDM.exe`, `IDM_Updater.exe`, `IDM_NativeHost.exe` |

User data: `%APPDATA%\IDM Download Manager` (database, logs, downloads, runtime).
Installer identity: `{A52627A1-E4C9-456C-A397-BB6D9FD48F1B}`.

---

## 4. Gap analysis against the 3.0.0 brief

| V3 requirement | Current state | V3 action |
|----------------|---------------|-----------|
| Next-gen dashboard | One table view, category sidebar | Multi-page shell: Dashboard, All Downloads, Video Downloads, Analytics, Performance, Browser, Update Center, Notifications, Settings |
| Video Downloads section | Category filter only | Dedicated page with media columns (format, source domain, title) and media-specific actions |
| Advanced video management | None | Media metadata model, content-type classification, page title/source domain, per-media actions |
| IDM Video Assistant extension | `IDM Integration Module` intercepts downloads only | New MV3 extension with media detection, HTML5 scan, popup, compliant YouTube handling |
| Chrome/Edge integration | MV3 present | New extension packaged for both; registration and docs updated |
| Real-time monitoring | 500 ms aggregate stats | Live dashboard/performance tiles, per-download speed/ETA, event stream |
| Advanced queue | Persisted queue + dialog, 10 concurrent | Queue page with reorder, priority, bulk actions; persisted order preserved |
| Improved engine | Range, retry, resume, journal | Media classification, SHA-256 verification, disk preflight, adaptive connection fallback, recovery setting |
| Performance | Batched persistence, 0.5 s stats timer | Reduce startup work, debounce UI refreshes, cache analytics, lazy page construction |
| Security | Strict validation, path safety, HTTPS updater | Media field validation, URL/host checks, checksum verification, no auto-execution of media |
| Updater | Signature + hash + rollback | 3.0.0 metadata, Update Center page, 24 h default, explicit approval retained |
| Branding | Generic logo | Original 3.0 visual identity (no third-party artwork) |
| Installer | `IDM_Setup.exe` output | `IDM-Setup-3.0.0.exe`, V2 detection, repair, extension/NM registration |
| Release layout | `release/IDM-x-win64` | `IDM_V3_Release/` exactly as specified |

---

## 5. Preservation contract (must not change)

1. Framework remains Python 3 + PySide6.
2. User data stays in `%APPDATA%\IDM Download Manager`; never `%APPDATA%\IDM`.
3. Database is never reset; migrations are additive and preceded by a verified backup.
4. User downloads, `.idm.part` files and journals are never deleted without explicit action.
5. Installer AppId stays stable; in-place upgrade reuses the install directory and tasks.
6. Uninstall preserves user data unless explicitly opted out (`/REMOVEDATA`).
7. Native host name stays `com.idm.native`; the existing extension key/ID stays valid so no registration breaks.
8. Updates remain HTTPS-only with hash and signature verification; unverified packages never execute.
9. Semantic version 3.0.0 is the single source in `idm/version.py`, Windows resources, installer, extensions and manifest.

---

## 6. V3 implementation plan

| Phase | Work | Acceptance gate |
|-------|------|-----------------|
| 1 | Analysis + verified backup | 196/196 hashes, DB `ok`, restored-source tests pass |
| 2 | Schema v4 + media/notification tables | V2→V3 migration preserves all rows; pre-migration backup verified |
| 3 | Engine upgrades | Direct MP4/WebM, content-type classification, SHA-256 option, disk preflight, adaptive fallback; tests |
| 4 | Desktop UI | Nine pages, working controls, light/dark themes; UI construction tests |
| 5 | IDM Video Assistant | MV3 extension builds/loads; media detector unit tests; compliant YouTube UX |
| 6 | Native messaging v2 | Allowlist, size limits, media fields validated; end-to-end request test |
| 7 | Branding/updater/installer | 3.0.0 everywhere; `IDM-Setup-3.0.0.exe`; repair + data preservation |
| 8 | Full test + release | Full suite green; release directory, checksums, docs |

---

## 7. Risks and blockers

1. **Code signing:** no CA-issued Authenticode certificate is present. Builds remain
   unsigned; automatic installation stays disabled if no trusted publisher is configured.
2. **YouTube:** no DRM bypass, stream extraction, signature deciphering or scraping will
   be implemented. YouTube pages are recognised and the UI explains platform restrictions
   and opens official options; only user-authorized direct media URLs are downloadable.
3. **Windows 10 validation:** this machine is Windows 11-class; Windows 10 installer
   testing cannot be executed here and will be reported as not verified rather than claimed.
4. **Update feed:** the configured manifest is a release feed; a 3.0.0 manifest must be
   signed and published after the build, using the offline key that is not in this repo.

---

## 8. Approval

Phase 1 is complete. Implementation continues with Phase 2 (database v4), keeping the
backup as the rollback point.
