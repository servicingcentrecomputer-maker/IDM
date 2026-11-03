# Changelog

All notable changes to IDM are recorded here. Versions follow semantic
versioning (`MAJOR.MINOR.PATCH`).

## [3.6.3] — 2026-11-03

### Added

- **Measured bandwidth limit.** Options → Download Settings now offers three
  limit modes — No limit, Fixed maximum, and Percentage of the measured link.
  The percentage is taken from a rolling estimate of the connection built from
  what IDM actually transferred, so the limit drops when the link slows down.
  A transfer that is pinned at its own cap is never treated as a measurement of
  the link, which stops a limit from confirming itself.
- **Measure the link now.** A percentage limit cannot discover the ceiling it
  is pinned under, so the button lifts the limit for a five-second window while
  a download runs and records the real figure. The estimate is saved and re-used
  after a restart.
- **Speed over time** graph in the Download Progress window: one reading per
  second, the peak and average, and a dashed line showing the limit that is
  actually binding (the tighter of the global cap and the per-download cap).
- **Download Properties** window (Downloads → Properties) with
  General, Transfer, Integrity, Source and Last error sections, the real size on
  disk, and Copy Link / Open Folder / Open actions.
- **Open**, **Open Containing Folder** and **Properties** in the Downloads menu
  and the list context menu. Files that Windows would execute (`.exe`, `.msi`,
  `.bat`, `.ps1` and similar) ask for confirmation before the first open.
- **Rename** and **Refresh Download Link** for a selected download. Rename
  writes the file and the record together, rolls back if either fails, and
  re-detects the category when the extension changes.
- **Verify Checksum** computes the SHA-256 of a finished file and reports
  whether it matches the checksum the download was given. A mismatch during an
  automatic verification discards the partial file instead of keeping it.
- **Add Batch Downloads** (`Ctrl+Shift+U`) takes a list of URLs, removes
  duplicates, caps the batch at 500 and starts them into one folder.
- **Page link capture.** The Video Assistant can collect the downloadable links
  on a page, send them through the native host, and open one folder prompt for
  the whole batch.
- **System tray**: minimise to the tray, Pause all / Resume all / Quit from the
  tray menu, a live summary in the tooltip, and native Windows notifications
  that can be turned off.
- **Start IDM when I sign in to Windows**, detected from both the HKCU Run key
  and the Startup folder so an externally made change is still reported
  correctly.
- **Connection Settings** tab: system, direct or manual HTTP/HTTPS proxy with
  bypass matching, per-site usernames and passwords for HTTP 401 responses, and
  connect and read timeouts.
- **FTP and FTPS downloads** with passive transfer, resume with `REST`, and
  plain-language errors for 530/550/421 replies.
- **Dynamic re-segmentation.** A connection that falls behind has half of its
  unclaimed tail reassigned to an idle connection, so one slow stream no longer
  holds the whole download up.
- **Redirect handling** follows up to eight hops itself and drops stored
  credentials when the chain leaves the original host.
- **Brave and Opera** are recognised and registered as supported browsers, and
  Chrome and Edge builds now report which browser they are actually running in.
- **Live bridge status** on the Browser Integration page, so you can see
  whether the native host is answering without sending a test download.
- **General** library destination, so files that match no rule land somewhere
  named rather than in an unnamed catch-all.

### Changed

- Credentials are kept in Windows Credential Manager, never in the settings
  database. The stored site-authentication table holds host, user and scheme
  only; passwords are not written to disk.
- Every log record is passed through a secret scrubber, so a URL carrying
  `?token=` or an `Authorization:` header cannot leave a password in the log
  file, including inside free-form error text.
- Media restrictions are enforced in the download engine, not only in the
  dialogs, so a blocked platform is refused whichever route the request
  arrives from. IDM never bypasses DRM or access controls.
- **Delete Completed** now says how many entries it is about to clear and
  confirms first, honouring the existing "ask before removing" setting. The
  downloaded files are left on disk.
- Settings from 3.6.2 load unchanged: a non-zero `speed_limit_kbps` still means
  a fixed limit after the upgrade.
- Chrome, Edge, Firefox, native host and Video Assistant are version 3.6.3.

### Not implemented in 3.6.3

Requested during this release and deliberately left out, so the gap is on the
record rather than hidden:

- SOCKS and per-protocol proxies; only HTTP/HTTPS proxying is implemented.
- MD5 and SHA-1 verification; only SHA-256 is available.
- Antivirus scanning of finished downloads; IDM hands the file to Windows and
  does not invoke a scanner.
- Adaptive streaming: HLS (`.m3u8`) and DASH (`.mpd`) manifests are recognised
  as video but not parsed, so segment merging, quality selection, audio-only
  extraction, subtitles and playlists are not supported.
- A log viewer inside the application; the log file is still text you open
  yourself.
- Named queues with their own rules per queue; the queue is shared and ordered
  by priority.
- Segmented FTP; FTP transfers use one connection.
- Page-link capture in the Chrome, Edge and Firefox integration modules; it
  ships in the Video Assistant only.
- Any bypass of DRM, paywalls or a site's access controls.

## [3.6.2] — 2026-11-02

### Added

- Hybrid Fluent design tokens: Light (`#F3F5F8` background, `#1685D9` accent)
  and Dark (`#151A22` background, `#3199F5` accent) palettes with matching
  borders, hover, selected and focus-ring roles across the shell.
- **Refresh** toolbar button and **View → Refresh** (`F5`), which reloads the
  list from the download manager without disturbing running transfers.
- Sort selector in the content header (default order, file name, size,
  date added, downloaded amount, progress, speed and status) that stays in
  sync with the clickable column headers.
- **Downloaded** column showing the bytes received so far, separate from the
  total **Size** column.
- Sidebar connection footer with an online/offline dot, live transfer rate and
  a tooltip explaining when Windows network monitoring is unavailable.
- **Other Files** library destination, a version chip in the toolbar and the
  application version in the window title.
- Dashboard cards for **Total downloads**, active, completed and total data,
  with live current speed and the active count in the hero.
- A loading state in the download list that paints before a history reload, and
  a **More** toolbar menu holding Queue, Scheduler and Options below 1120 px.
  The table also drops Time Left and Date Added below a 980 px viewport, and
  Downloaded and Speed below 820 px, so file names stay readable.
- Themes now hide window repaints while the palette is swapped, removing the
  white flash when switching between Light, Dark, System and Classic.

### Changed

- New installations default to the Light theme; the Classic theme remains
  available for existing preferences and stored settings are unchanged.
- Chrome, Edge, Firefox and Video Assistant manifests are version 3.6.2.

## [3.6.1] — 2026-11-02

### Added

- Classic + Modern application shell: **File**, **Downloads**, **View**,
  **Tasks** and **Help** menus; a compact toolbar with Add URL, Resume, Resume
  All, Stop, Stop All, Delete, Delete Completed, Options, Scheduler and Queue;
  and a responsive icon-only mode below 1320 px.
- Custom categories in the sidebar with live counts, table filtering and
  selection preservation, plus **Tasks → Manage Categories**.
- **Download Complete** window with real average speed, completion time, size
  and source host, Open File / Open Folder actions and a persisted
  “Show this window when a download completes” choice.
- Total downloaded data across all records in the status bar.
- Live MB/GB download readouts. After **Start Download** the Download File Info
  dialog stays open as a compact live view with the percentage, downloaded and
  total size, transfer rate, time left and status, and closes itself when the
  transfer finishes. The download list also shows the downloaded amount in its
  Size column (for example `8.3/64 MB`).

### Changed

- The download table now shows **File Name** (with category subtitle and
  file-type icon), **Size**, **Status** pill, rounded **Progress** meter,
  **Speed**, **Time Left** and **Date Added**, with the previous category
  information preserved in the name subtitle and tooltip.
- Classic Light, Modern Light and Modern Dark share one design-system token
  set; switching applies instantly, persists, and covers every dialog and
  status widget.
- The status bar adds the downloaded-total readout and the current version;
  the sidebar reuses the same icon and count styling as the modern pages.
- Chrome, Edge, Firefox and Video Assistant manifests are version 3.6.1.

### Fixed

- The progress column renders the designed rounded meter in every theme; a
  second, older delegate definition no longer overrides it.

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
