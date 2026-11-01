# Changelog

All notable changes to IDM are recorded here. Versions follow semantic
versioning (`MAJOR.MINOR.PATCH`).

## [3.6.0] — 2026-11-01

### Added

- Working **Download File Info** dialog for manual, context-menu and browser
  downloads: full-URL copy, category detection, editable file name and folder,
  native folder picker, extension display, remembered folder per category,
  optional description and a server-reported file information panel.
- Link metadata detection with `HEAD`, a `Range: bytes=0-0` GET fallback,
  redirect handling, request timeouts and honest unknown/unavailable states.
- Start Download, Download Later and Cancel actions. Later tasks persist in the
  queue across restarts and start from the Queue Manager.
- Schema version 5 with `description` and `start_later` columns, a verified
  pre-migration backup and non-destructive upgrade from versions 1–4.
- Browser downloads now open the dialog and cancel the browser copy only after
  IDM creates the task; cancelling resumes the original browser download.
- Automated coverage for metadata detection, category handling, the dialog,
  Download Later, the browser prompt, migrations and security rules.

### Changed

- The Download File Info dialog now uses a Windows 11-style layout with a
  branded header, file hero card, icon-led fields, a compact server information
  card, animated primary action and an adaptive 800×920 default size.
- Browser requests are serialised behind the dialog; duplicate active URLs are
  answered without a second prompt.
- Chrome, Edge, Firefox and Video Assistant manifests are version 3.6.0.

### Fixed

- Server status labels now include 200, 204, 206, 301, 302 and 304 reasons
  instead of a bare `HTTP <code>`.
- Redirected metadata requests keep the URL the user entered while reporting
  the final response headers.

## [3.5.0] — 2026-11-01

### Added

- Centralized design system (`idm/ui/design.py`) for colour, typography,
  spacing, radii, elevation, icons and motion, compiled into the global Qt
  style sheet.
- Light, Dark and Follow-Windows themes with instant, app-wide switching.
- Collapsible navigation rail covering Dashboard, All Downloads, Downloading,
  Completed, Queued, Paused, Video Downloads, Documents, Programs, Music,
  Compressed Files, Browser Assistant, Scheduler, Download History and
  Settings.
- Modern toolbar with context-aware Add, Start, Pause, Resume, Stop, Remove,
  Queue, Search, theme, Notifications and Settings actions.
- Live dashboard totals, throughput, queue state, recent transfers, disk space
  and update status.
- Virtualized download table with a Category column and search across file
  name, URL, category and source domain.
- Video Downloads card grid with metadata, search, sorting and per-card
  actions.
- Browser Assistant backed by real registry, native-host and bridge status.
- Fourteen searchable, persisted Settings sections.
- Redesigned Update Center showing installed/latest versions, release notes,
  download progress, verification state, history and maintenance tools.
- Subtle animations with a Reduce motion preference and automatic respect for
  the Windows animation-effects setting.
- Keyboard navigation, accessible names for icon-only controls, focus outlines
  and multi-select support.

### Changed

- Replaced the classic page layouts with responsive card-based workspaces that
  fit 1366×768 and scale to 2560×1440 at 100–175% scaling.
- Download rows now show category and use original category icons.
- About-window and background update checks now share their result with the
  Update Center.
- Release notes are stored as `ReleaseNotes.md` and referenced by the UI and
  packaging scripts under that name.

### Fixed

- Dashboard summary header no longer collapses; the headline now reflects
  live state (transfers in progress, queued, complete or ready).
- Navigating to a footer page such as Settings no longer leaves the previous
  sidebar row highlighted.
- Pill badges and chips render with the intended rounded corners; Qt clamps
  radii above half the widget height, so the obsolete `999px` token is now a
  measured 14 px with tighter per-component radii.
- Options dialog tabs scroll instead of overlapping labels and inputs when the
  window is short.
- Performance tuning rows align labels, hints and controls on a single
  right-aligned grid.

### Refined

- Toolbar actions use monochrome, palette-aware line icons; Add URL keeps a
  white glyph for contrast.
- Video cards use a cinematic navy poster in both themes with category glow
  and a divider before the delete action.
- Settings and Video Downloads search fields gained a leading search icon that
  follows the active palette.
- Transfer rows colour state by meaning — accent for active, green for
  complete, amber for paused/stopped, red for failed.
- Branding assets were regenerated from the updated `assets/logo.svg`
  (application icon, `.ico`, installer wizard bitmaps).

### Preserved

- Download engine, retry/resume, segmented transfers, queue, scheduler and
  speed limits.
- SQLite schema version 4 and all user data, settings and history.
- Browser extensions, native messaging protocol, allowlists and message size
  limits.
- Ed25519 manifest verification, SHA-256 checks, Authenticode support, update
  backup and rollback.
- No DRM bypass, protected-stream extraction or silent extension installation.

## [3.0.0] — 2026-11-01

- Next-generation workspace with Dashboard, Video Downloads, All Downloads,
  Browser Integration, Analytics, Performance, Advanced Settings, Update
  Center and Notifications.
- IDM Video Assistant Manifest V3 extension for Chrome and Edge using the
  `com.idm.native` host and protocol v2.
- Database schema v4 with additive migrations and verified backups.
- Signed update pipeline with resumable installer download, SHA-256,
  Authenticode support and rollback.
- Installer per-user native-host registration, extension archives and
  in-place upgrades from 1.x and 2.x.

## [2.0.1] — previous release

- Released with a configured, signed update feed.
- Fixed a release-build variable collision with the `-Package` switch.

## [2.0.0] — previous release

- Added automatic updates, verified backups and rollback.

## [1.0.0] — initial release

- First public release of the IDM download manager.
