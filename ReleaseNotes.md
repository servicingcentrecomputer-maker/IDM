# IDM 3.6.2 — Release Notes

**Release date:** 2026-11-03
**Platform:** Windows 10/11 x64
**Channel:** stable

Version 3.6.2 is a UI release on top of the 3.6.1 Classic + Modern shell. The
interface now uses Hybrid Fluent design tokens for Light and Dark, the dashboard
reports real download totals and live speed, and the download list gains
refresh, sorting and a separate **Downloaded** column. The download engine,
queue, scheduler, browser integration, updater, settings and database schema
keep their existing behaviour and data.

## Highlights

### Hybrid themes

- Light (`#F3F5F8` background, `#1685D9` accent) and Dark (`#151A22` background,
  `#3199F5` accent) palettes with matching borders, hover, selected and
  focus-ring roles across the shell.
- Switching between Light, Dark, System Default and Classic swaps the palette
  while window repaints are hidden, so the white flash is gone.
- New installations default to **Light**; Classic remains available for existing
  preferences and stored theme choices are unchanged.

### Dashboard

- Cards for **Total downloads**, active, completed and total data downloaded.
- Live current speed and the active count in the dashboard hero.

### Download list

- **Refresh** toolbar button and **View → Refresh** (`F5`) reload the list from
  the download manager without disturbing running transfers.
- Sort selector in the content header (default order, file name, size, date
  added, downloaded amount, progress, speed and status) that stays in sync with
  the clickable column headers.
- **Downloaded** column showing the bytes received so far, separate from the
  total **Size** column.
- A loading state that paints before a history reload.
- Responsive columns: **Time Left** and **Date Added** drop below a 980 px
  viewport, and **Downloaded** and **Speed** as well below 820 px, so file names
  stay readable.

### Navigation and layout

- Sidebar footer with an online/offline connection dot, the live transfer rate
  and a tooltip explaining when Windows network monitoring is unavailable.
- New **Other Files** library destination, a version chip in the toolbar and the
  application version in the window title.
- A **More** toolbar menu holding Queue, Scheduler and Options below 1120 px.

### Browser extensions

- Chrome, Edge, Firefox and Video Assistant manifests are version 3.6.2.

## Preserved functionality

- Segmented HTTP downloads over up to 16 connections, Range resume after a
  restart, retry and speed limits.
- Persistent queue, scheduler, download history, clipboard monitoring and
  category detection.
- Chrome, Edge and Firefox integration through the native messaging host and
  localhost bridge, including the Download File Info review dialog.
- Existing settings, database schema 5, partial files, browser registration and
  update configuration are untouched.

## Upgrade

- Install `IDM-Setup-3.6.2.exe` over 3.6.1 or any earlier release. The same
  `AppId`, installation directory and `%APPDATA%\IDM Download Manager` data are
  reused; no migration is needed for this release.

## Artifacts

- `dist\IDM\IDM.exe` — portable application with `_internal\`,
  `IDM_Updater.exe` and `IDM_NativeHost.exe`
- `dist-installer\IDM-Setup-3.6.2.exe` — installer (SHA-256
  `b2c9f9cea6ed6f7f6bf742701300ba7200b6897dd3f81ae16d15bcad4b7afa1d`)
- `release\IDM-3.6.2-win64.zip` — bundle with installer, portable build,
  extension archives, documentation and `SHA256SUMS.txt`
- `dist-extensions\IDM_Video_Assistant_3.6.2.zip` — Video Assistant package

## Known limitations

- The installer is unsigned unless a CA-issued Authenticode certificate is
  configured; the signed manifest and SHA-256 remain the trust anchors.
- Windows 10 is supported by the installer configuration but validation ran on
  Windows 11 x64.
- The signed update feed advertises 3.6.2 with the published installer's real
  SHA-256 and package size. The automatic download-and-install path from 3.6.1
  was not re-run end-to-end in this session.
- Real browser interception still needs a manual pass in Chrome and Edge; the
  native host, bridge, protocol and prompt contract are covered by automated
  tests.
