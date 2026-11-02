# IDM 3.6.1 — Release Notes

**Release date:** 2026-11-02
**Platform:** Windows 10/11 x64
**Channel:** stable

Version 3.6.1 is a UI release: the existing 3.6.0 download platform now uses a
single **Classic + Modern** interface. The shell, table, dialogs, icons and
themes were rebuilt on the project's own design tokens, while the download
engine, database, queue, scheduler, browser integration and updater keep their
existing behaviour and data. Nothing was replaced with mock data — progress,
speed, time left, sizes, completion times and totals all come from the running
engine and `DownloadItem` records.

## Highlights

### Classic shell with a modern finish

- Menu bar with **File**, **Downloads**, **View**, **Tasks** and **Help**;
  **Downloads** adds Stop All and **Tasks** groups Options, Scheduler, Queue
  Manager and Manage Categories.
- Compact toolbar with Add URL, Resume, Resume All, Stop, Stop All, Delete,
  Delete Completed, Options, Scheduler and Queue. Below 1320 px the labels
  collapse to icons with tooltips; the search field hides below 1200 px.
- Sidebar keeps the classic IDM workspace list (Dashboard, All Downloads,
  Downloading, Completed, Queued, Paused), the library categories (Documents,
  Music, Videos, Programs, Compressed Files, Images) and the tool pages, with
  live counts for every destination.
- **Custom categories** created while adding a download or through **Tasks →
  Manage Categories** appear in the sidebar as their own destinations, filter the
  table, show counts and keep selection across category edits.

### Download list

- Seven columns: **File Name** (with category subtitle and a file-type icon),
  **Size** (downloaded/total while active), **Status** (tinted chip), **Progress**
  (rounded meter with percentage), **Speed**, **Time Left** and **Date Added**.
- Real-time values from the engine, honest em dashes for unknown size, speed,
  ETA or completion data, sortable columns, multi-select, safe context menu,
  search across name/URL/category/source domain and category filtering.
- The status bar reports active and queued transfers, the current transfer rate,
  the total data downloaded across all records and the application version.

### Download Complete window

A new non-modal window opens when a transfer finishes (unless disabled in
Options → Confirmations):

- Real average speed, completion time, final size and source host.
- **Open File** and **Open Folder** actions using the real saved path, plus
  Close; the window can stay open while downloads continue.
- A persisted **Show this window when a download completes** checkbox.
- One window per finished download; closing it releases the dialog cleanly.

### Themes and design system

- Three themes: **Classic Light**, **Modern Light** and **Modern Dark**, plus
  Follow Windows. Switching applies instantly without restarting and the choice
  persists in settings; every dialog, card, menu and status widget follows.
- Shared spacing, radius, typography, elevation, icon-size and motion tokens in
  `idm/ui/design.py`, compiled into the Qt style sheet.
- Updated monochrome SVG icon set, including Stop All and Delete Completed.
- Custom-painted progress meter, status chips and sidebar rows stay readable in
  all three themes; focus outlines, hover and disabled states are kept.

### Preserved functionality

- Segmented HTTP downloads over up to 16 connections, Range resume after a
  restart, retry and speed limits.
- Persistent queue, scheduler, download history, clipboard monitoring and
  category detection.
- Chrome, Edge and Firefox integration through the native messaging host and
  localhost bridge, including the Download File Info review dialog.
- Existing settings, database schema 5, partial files, browser registration and
  update configuration are untouched.

## Upgrade

- Install `IDM-Setup-3.6.1.exe` over 3.6.0 or any earlier release. The same
  `AppId`, installation directory and `%APPDATA%\IDM Download Manager` data are
  reused; no migration is needed for this release.
- The original 3.6.0 binaries are kept byte-for-byte in
  `Backup/Release_3.6.0_PreRedesign/`; the new installer uses a new file name
  and does not replace them.

## Artifacts

- `dist\IDM\IDM.exe` — portable application with `_internal\`,
  `IDM_Updater.exe` and `IDM_NativeHost.exe`
- `dist-installer\IDM-Setup-3.6.1.exe` — installer
- `release\IDM-3.6.1-win64.zip` — bundle with installer, portable build,
  extension archives, documentation and `SHA256SUMS.txt`
- `dist-extensions\IDM_Video_Assistant_3.6.1.zip` — Video Assistant package

## Known limitations

- The signed update feed advertises 3.6.1 with the published installer's real
  SHA-256 and package size. The automatic download-and-install path from 3.6.0
  was not re-run end-to-end in this session.
- The installer is unsigned unless a CA-issued Authenticode certificate is
  configured; the signed manifest and SHA-256 remain the trust anchors.
- Windows 10 is supported by the installer configuration but validation ran on
  Windows 11 x64.
- Real browser interception still needs a manual pass in Chrome and Edge; the
  native host, bridge, protocol and prompt contract are covered by automated
  tests.
