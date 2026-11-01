# IDM 3.0.0 → 3.5.0 Upgrade: Phase 1 Implementation Report

## 1. Existing project (verified)

| Item | Finding |
| --- | --- |
| Version | `idm/version.py` → `CURRENT_VERSION = "3.0.0"` |
| Framework | **Python 3.12 + PySide6 (Qt 6)**, packaged with PyInstaller. No C#/WPF code is part of the application. Stale `IDM.Core.dll`/`IDM.UI.dll` files remain in the installed profile from an abandoned experiment and are not referenced or shipped by the build. |
| UI pattern | `QMainWindow` + custom painted `QStyledItemDelegate` tables + `QStackedWidget` pages + QSS themes (`idm/ui/theme.py`) |
| Size | 20,958 Python LOC in `idm/` (11,259 in `idm/ui/`) |
| Database | SQLite schema **version 4**: `downloads`, `download_segments`, `download_queue`, `download_logs`, `download_events`, `media_metadata`, `notifications`, `app_settings`, `settings`. Integrity check `ok`. |
| Theme model | `classic` (default), `light`, `dark`; no system-theme following |
| Extensions | `BrowserExtension/IDMVideoAssistant` (MV3) plus packaged `extensions/{chrome,edge,firefox}` |
| Native host | `integrations/` + `IDM_NativeHost.exe`, HKCU registration per browser |
| Updater | Signed manifest (Ed25519) + SHA-256 + optional Authenticode, backups and rollback (`idm/updater/*`) |
| Installer | Inno Setup `installer/IDM_Setup.iss`, `AppId` stable since 1.0.0, per-user native host registration |
| Build | `build_windows.ps1` reads `CURRENT_VERSION`, enforces version parity across manifests, `version_info_*.txt` and the `.iss` |

Uncommitted work on top of commit `4b369a7` (26 files, +984/−210) was present at
the start of this upgrade. It is updater hardening plus its tests.

## 2. Verified backup (Phase 1 deliverable)

`Backup/Version_3.0.0_20261101/`

- `Version_3.0.0_Source/` — 228 source files exactly as built, plus
  `_uncommitted_working_tree.patch` containing the uncommitted delta.
- `Version_3.0.0_Data/` — SQLite snapshot taken with the SQLite backup API
  (`integrity_check = ok`), schema dump, logs, data inventory, native messaging
  registry export, installed file listing.
- `Version_3.0.0_Release/` — published `IDM-Setup-3.0.0.exe`, `IDM.exe`, release
  docs and browser extension package.
- `Backup_Manifest_3.0.0.json` — SHA-256 for all **251 files / 69,606,211 bytes**.
- `RESTORE.md` — restore procedure.

A full re-hash verification pass was run after copying: **0 failures**.

## 3. Baseline test result

`472 passed` (`pytest`, non-UI suite; UI tests are run separately because they
create windows). This is the regression baseline that 3.5.0 must keep green.

## 4. UI architecture constraints discovered

1. **Public UI contracts used by tests must survive the redesign**
   - `DownloadToolbar.buttons` keys exactly: `add, resume, resume_all, pause,
     stop, delete, options, scheduler, queue`; `add` text is `Add URL`.
   - `MainWindow._actions` incl. `view_show_*`, `import`, `export`,
     `delete_completed`, `docs`, `about`, `check_updates`.
   - `Sidebar.select(key, emit_signal=True)`, `Sidebar.current_key`,
     `MainWindow._sidebar`, `_search`, `_download_view`,
     `_theme_actions["light"|"dark"]`, `_set_theme()`.
   - `OptionsDialog.theme_cards` must include `classic`, `light`, `dark`
     (`_preview_theme`), and `AdvancedSettingsPage` signals.
2. Existing settings keys must keep working; new keys are additive only.
3. The update check/install pipeline lives in `UpdatePanel` (About dialog). The
   Update Center page reuses it through `check_requested` rather than
   duplicating verification logic.
4. QSS is global; every new object name needs tokens in **all** palettes
   (classic, light, dark) or the legacy theme breaks.

## 5. Design decisions for 3.5.0

- Keep **PySide6** (no framework migration). The requested C#/WPF check resolves
  to "preserve framework".
- Introduce `idm/ui/design.py` (tokens: colour, type scale, spacing, radius,
  elevation, icon size, motion) and `idm/ui/components.py` (reusable widgets).
  `theme.py` becomes the token→QSS compiler.
- Add a real **System** theme: resolved from Qt `QStyleHints.colorScheme()`
  (Qt ≥ 6.5) with a Windows registry fallback, live-updating. `classic`
  remains internally supported (legacy + Options dialog compatibility) but is
  not part of the main theme switcher.
- Sidebar becomes collapsible with groups, badges, tooltips and keyboard
  support; every item maps to a real page, filter or dialog.
- Video Manager: keep the data model, add an icon/grid **card** view driven by a
  virtualised `QListView` (no fabricated thumbnails — generated format tiles
  only from real metadata).
- Settings: 14 categories with in-page search; all controls bind to persisted
  `AppSettings` fields; sections that depend on existing dialogs open those
  dialogs instead of duplicating logic (no placeholder buttons).
- Animations are centralised in `idm/ui/animations.py`, short (≤260 ms), and
  skipped when Windows reports reduced motion or the user disables them.
- Version bumped in one place (`idm/version.py`), with the build script
  enforcing parity with the extension manifests, `version_info_*.txt` and the
  Inno Setup script.

## 6. Planned file changes

New: `idm/ui/design.py`, `idm/ui/components.py`, `idm/ui/animations.py`,
`idm/models/video_card_model.py`, `docs/UI-Design-System.md`, release docs.

Rewritten: `idm/ui/theme.py`, `sidebar.py`, `toolbar.py`, `download_view.py`,
`delegates.py`, `status_bar.py`, `pages/{dashboard,videos,browser,settings,
update_center}.py`, `main_window.py` (structure only, behaviour preserved),
`icons.py` + `assets/logo.svg` (original branding).

Targeted: `core/settings.py` (additive `ui_animations`, system theme),
`models/table_model.py` (queued/paused/history filters), `version.py`,
`installer/IDM_Setup.iss`, `version_info_*.txt`, extension manifests.

## 7. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Global QSS regression in legacy/classic theme | Every palette keeps all tokens; screenshot check for classic/light/dark |
| Sidebar rework breaks navigation tests | Keep `select()`, `current_key`, `filter_changed`, filter keys unchanged |
| Settings rewrite loses a preference | Bind to the same `AppSettings` attributes; migration is additive |
| Theme switch while animations run | Single `ThemeManager.apply()`, stop animations before restyle |
| Build fails on version parity | `build_windows.ps1` validates; bump all manifests together |
| Update/rollback logic accidentally altered | No edits to `idm/updater/*` logic; only UI presentation changes |
