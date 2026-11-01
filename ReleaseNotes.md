# IDM 3.5.0 — Release Notes

**Release date:** 2026-11-01
**Platform:** Windows 10/11 x64
**Channel:** stable

Version 3.5.0 is a complete modern redesign of the IDM desktop interface. The
download engine, SQLite database, browser integration, native messaging host,
security model and signed updater are unchanged; every screen above them has
been rebuilt on one central design system so the application looks and behaves
consistently at any window size, theme or Windows display scale.

Existing settings, history, queue entries, partial downloads, browser
registration and update configuration are preserved. No database migration is
required for this release.

## Highlights

### A single design system

Colours, typography, spacing, corner radii, elevation, icon sizes and motion
timings now live in `idm/ui/design.py` and are compiled into the global Qt
style sheet by `idm/ui/theme.py`. Components no longer invent their own
spacing or colours, so light, dark and Follow-Windows themes stay consistent
across every page.

- Original IDM branding and iconography only; no third-party artwork.
- Light and dark palettes plus a **Follow Windows** mode that tracks the
  Windows app theme while it is running.
- Theme switching is immediate and repaints every page, table, card and
  custom-painted control.
- Subtle 120–260 ms transitions for the sidebar rail, segmented controls,
  toggles and notices. Windows' "Animation effects" accessibility setting and
  the IDM **Reduce motion** preference disable them together.

### Navigation and toolbar

- Collapsible navigation rail with Dashboard, All Downloads, Downloading,
  Completed, Queued, Paused, Video Downloads, Documents, Programs, Music,
  Compressed Files, Browser Assistant, Scheduler, Download History and
  Settings. Counts are live and the collapsed rail keeps icons and tooltips.
- The toolbar exposes Add Download, Start, Pause, Resume, Stop, Remove, Queue,
  Search, theme selection, Notifications and Settings. Actions enable only
  when they apply to the current selection.
- Keyboard access: `Ctrl+B` toggles the rail, lists are focusable, Enter
  activates navigation items and video cards, and every icon-only button has
  an accessible name.

### Dashboard

The dashboard reads live data from the download manager and storage layer:

- Active, queued, completed and failed totals.
- Live aggregate throughput and the global speed limit.
- Recent transfers with progress and state.
- Queue depth, scheduler state, disk free space and last update check.
- The view refreshes automatically while transfers are running and stops
  polling when the page is not visible.

### Download list

- Virtualized table that stays responsive with thousands of rows.
- File name, size, **category**, status, time left, transfer rate and last try.
- Per-row progress painting, status colouring and category-aware icons.
- Search across file name, URL, category and source domain; sortable columns;
  multi-select; context menu for open, folder, copy link, pause, resume, stop,
  queue and remove.
- Explicit empty and no-results states instead of a blank grid.

### Video Downloads

- Card grid with title, source, format, size, progress, speed, time left and
  status, plus search and sorting.
- Cards expose Pause/Resume, Open file, Open folder, Copy link and Remove
  record only when the action is valid.
- Direct HTTP/HTTPS media only. YouTube and other restricted platforms are
  recognised but never scraped, decrypted or bypassed; the extension and the
  desktop point users to the platform's official options.

### Browser Assistant

- Real Chrome, Edge and Firefox detection from the native-messaging registry
  entries and the installed extension version.
- Native host registration status, supported file types and connection state
  come from the live bridge; the page never reports "connected" without a
  validated connection.
- Enable/disable detection, choose supported types and open installation
  instructions. The installer still ships extensions as archives and unpacked
  folders and never installs them silently.

### Settings

Fourteen searchable sections: General, Downloads, Connections, Browser
Integration, Video Downloads, File Types, Scheduler, Notifications, Appearance,
Storage, Backup and Restore, Automatic Updates, Security, and About IDM.

- In-page search filters sections and rows immediately, with a clear
  no-results state.
- Every control persists through the existing settings store and applies
  without restarting IDM.
- Appearance includes theme, reduced motion and workspace visibility.
- Browser Integration, Backup and Restore, Automatic Updates and About expose
  real actions: registration, verified backup/restore, update checks and
  diagnostic locations.

### Update Center

- Installed version, latest version, release date, package size and status at
  a glance.
- Embedded signed-manifest check with release notes, download progress,
  SHA-256 verification, Authenticode status when a publisher is configured,
  pre-install backup and rollback.
- Background checks and About-window checks share the same result state, so
  the page always matches the real updater.
- Update history and maintenance tools remain available.

## Preserved and unchanged

- Segmented HTTP Range download engine, retry, resume, speed limits and queue.
- SQLite schema version 4, verified pre-migration backups and all user data.
- Browser extensions, native messaging protocol v2, allowlists, size limits
  and command restrictions.
- Ed25519 manifest signatures, SHA-256 installer checks, Authenticode support,
  staged installation and rollback.
- No DRM bypass, no protected stream extraction, no signature deciphering and
  no unauthorised scraping.

## Upgrade notes

- Install `IDM-Setup-3.5.0.exe` over 3.0.0 or any earlier 1.x/2.x release. The
  same AppId, installation directory and `%APPDATA%\IDM Download Manager`
  user-data folder are reused.
- No database migration runs for 3.5.0; schema version 4 remains current.
- The pinned Chrome/Edge extension ID is unchanged, so existing native-host
  registration continues to work. Reload the unpacked extension if the
  browser reports an older manifest version.
- The signed public update feed still advertises 3.0.0 until a new manifest is
  signed with the release key. IDM will correctly treat the installed 3.5.0 as
  newer; the Update Center shows that state instead of offering a downgrade.

## Verification

Run the following from the repository root after installing dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Build and package:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1 -Force -Package
```

Release artifacts:

- `dist\IDM\IDM.exe` — portable application
- `dist-installer\IDM-Setup-3.5.0.exe` — installer
- `release\IDM-3.5.0-win64.zip` — bundle with installer, portable build,
  extensions, documentation and SHA-256 sums

See `UI-Design-System.md` for the design tokens and component rules and
`TestingReport.md` for the verification record.
