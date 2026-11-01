# IDM — Internet Download Manager

An original Windows desktop download manager built with Python, PySide6 and
Requests. The interface follows the compact, classic Internet Download Manager
layout while using an original icon set, an SQLite-backed history, a real HTTP
download engine, pause/resume with HTTP Range, a queue, schedules and three
interface themes.

The current build is Version 3.5.0. It replaces the classic layouts with a
consistent, modern workspace built on a central design system: a collapsible
navigation rail, live dashboard, virtualized download table with categories,
video card grid, real Browser Assistant status, fourteen searchable Settings
sections, a redesigned Update Center, light/dark/Follow-Windows themes and
motion that respects the Windows reduced-motion preference. The complete
application shell, the multi-connection segmented download engine and the
browser integration are included. The engine supports HTTP Range transfers
over up to 16 parallel connections, resumable segmented downloads that survive
a restart, automatic retry, global and per-download speed limits, and a
persistent queue. Servers that do not support Range fall back to a single
connection automatically. The download engine, database, extensions, native
messaging and updater are unchanged by the interface redesign; see
[ReleaseNotes.md](ReleaseNotes.md).

An About window with **Check for Updates** is included, backed by a real signed
release manifest, resumable installer download, SHA-256 and Windows Authenticode
verification, and a separate `IDM_Updater.exe` process. Automatic updates are
implemented but intentionally inert until an HTTPS endpoint and trusted publisher
are configured; see [docs/UPDATES.md](docs/UPDATES.md).

Chrome, Edge and Firefox integrations are included: a per-browser extension
detects downloads, pauses the browser copy, asks IDM to accept it, and cancels
the browser download only after acceptance. IDM keeps the transfer in its
existing queue with browser, filename, URL and progress shown in the normal UI.
See [docs/BROWSER_INTEGRATION.md](docs/BROWSER_INTEGRATION.md).

## Requirements

- Windows 10 or Windows 11
- Python 3.11+ (Python 3.12+ recommended by the project brief)
- PySide6 and Requests (installed from `requirements.txt`)

The source build, automated tests and packaged installer were validated on
Windows 11 x64 with Python **3.12.14**, PySide6 **6.12.0**, Requests
**2.34.2** and Inno Setup 7. The code uses features available in Python 3.11
and newer. Windows 10 is supported by the installer configuration but was not
available for testing on this machine.

## Install and run

### Windows installer

A packaged build is produced by the build automation:

- Application: `dist\IDM\IDM.exe`
- Installer: `dist-installer\IDM-Setup-3.5.0.exe`

Run `IDM-Setup-3.5.0.exe` to install IDM, create shortcuts, optionally start it with
Windows, and register it in Add/Remove Programs. The browser integration page
offers one optional task per detected browser; selecting it registers the
native messaging host for the current user. Extension ZIP packages are shipped
in `{app}\browser-extensions` and are never installed silently. User data is
stored under `%APPDATA%\IDM Download Manager` and is preserved across upgrades
and default uninstalls. See [PACKAGING.md](PACKAGING.md) for build
instructions, silent install/uninstall switches, data paths, upgrade behavior,
the testing checklist and code-signing requirements. Browser setup, extension
IDs and store publishing are covered in
[docs/BROWSER_INTEGRATION.md](docs/BROWSER_INTEGRATION.md) and
[docs/BROWSER_STORE_PUBLISHING.md](docs/BROWSER_STORE_PUBLISHING.md).

### Release package

The 3.5.0 deliverables are assembled in `release\IDM-3.5.0-win64\` and
`release\IDM-3.5.0-win64.zip`: the portable application (`IDM.exe` with
`_internal\`, `IDM_Updater.exe` and `IDM_NativeHost.exe`),
`IDM-Setup-3.5.0.exe`, the unpacked `BrowserExtension\IDMVideoAssistant\`,
the extension archives, release notes, changelog, design-system guide, testing
report and `SHA256SUMS.txt`. Source remains editable in the repository root.

`build_windows.ps1 -Package` assembles `release\IDM-<version>-win64\` and a
matching ZIP after a successful build. The bundle contains the installer, the
portable application, browser extension packages, documentation, release
notes, `VERSION.json` and a `SHA256SUMS.txt` that covers every file. The
packager refuses to run when the application, installer resources and extension
manifests disagree on the version, and warns when an artifact predates the
newest source change.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1 -Force -Package
```

It can also be run directly:

```powershell
.\.venv\Scripts\python.exe scripts\package_release.py
```

Use `--no-portable`, `--no-installer` or `--no-zip` to tailor the bundle. See
[PACKAGING.md](PACKAGING.md#release-package) for the layout and validation
rules.

### From source

From `D:\IDM`:

```bat
cd /d D:\IDM
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

If the Windows `py` launcher is unavailable, create the environment with the
full interpreter path, for example:

```bat
"C:\Users\Jawad\AppData\Local\Programs\Python\Python311\python.exe" -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

## Browser integration

Three extensions are provided: Manifest V3 for Chrome and Edge and a
Firefox-compatible Manifest V2 extension with a stable Gecko ID. They use only
`nativeMessaging`, `downloads`, the context-menu API and `storage`.

- Interception pauses the browser download, sends a validated request to
  `IDM_NativeHost.exe`, and cancels the browser copy only after IDM replies
  `download_accepted`. On any failure the browser download is resumed.
- The context menu adds **Download with IDM** and **Download with IDM to…** for
  links; the second item always asks for a folder for that download.
- The popup shows connected/disconnected state, interception toggle, active and
  queued counts, the default save folder, recent transfers, **Open IDM**,
  **Download Settings** and **Test Connection**.
- The popup's **Ask where to save** toggle opens a folder picker for each
  browser download (intercepted or from the link menu) without changing the
  saved location mode. It is enabled by default so every browser download can
  go to a folder of the user's choice; turn it off to use the saved location
  automatically. Cancelling hands the download back to the browser.
- Downloads appear in the normal queue with browser, URL, size and progress;
  pause, resume, stop, retry and history use the existing engine and SQLite
  storage.
- Save To supports a default folder, ask-every-time, or file-type folders with
  user-editable extension rules. Missing folders are created only after
  approval; paths, traversal, reserved names and free space are checked.
- The browser never supplies trusted data: scheme, URL, filename, MIME type and
  size are validated by both the native host and the desktop app.
- The native host and desktop app communicate through an authenticated
  127.0.0.1 bridge with a per-run token. No shell commands, browser cookies,
  credentials or arbitrary local files are accepted.

Build the host and extension packages:

```powershell
.\.venv\Scripts\python.exe scripts\register_native_host.py install --dev
.\.venv\Scripts\python.exe scripts\package_extensions.py
```

For a packaged install, the installer's per-browser tasks register
`IDM_NativeHost.exe` under `HKCU`. Detailed installation, development loading,
extension IDs, limitations and a manual verification checklist are in
[docs/BROWSER_INTEGRATION.md](docs/BROWSER_INTEGRATION.md). Store submission is
documented in
[docs/BROWSER_STORE_PUBLISHING.md](docs/BROWSER_STORE_PUBLISHING.md).

### IDM Video Assistant

`BrowserExtension\IDMVideoAssistant\` contains a separate Manifest V3 extension
for Chrome and Edge that adds page-side media detection. It shares the pinned
extension ID and the `com.idm.native` host with the basic integration, so use one
of them per browser profile. It lists direct HTTP(S) media links and observable
HTML5 media sources, sends a selected link to IDM, and recognises YouTube and
YouTube Music pages. YouTube pages show only Google's official options
(Premium offline downloads, Studio creator downloads and the YouTube Help page);
no protected stream, `googlevideo.com` URL or signature data is extracted or
downloaded.

Install it from the unpacked folder, or build its ZIP package:

```powershell
.\.venv\Scripts\python.exe scripts\package_video_assistant.py
# dist-extensions\IDM_Video_Assistant_3.5.0.zip, no CRX
```

Its [README](BrowserExtension/IDMVideoAssistant/README.md) and
[InstallationGuide](BrowserExtension/IDMVideoAssistant/InstallationGuide.md)
cover permissions, Chrome/Edge loading, native-host registration and the manual
verification checklist.

Known platform limits: POST form downloads, Blob/MediaSource streams, browser-
internal saves and authenticated sessions that require browser cookies are not
sent to IDM. Those downloads stay in the browser. The original browser download
is not cancelled until IDM confirms it accepted the task.

## Run the tests

```bat
cd /d D:\IDM
python -m pytest tests -q
```

The UI tests use Qt's offscreen platform automatically; no visible window is
required. To regenerate the native screenshots used for visual review:

```bat
python -m tests.render_ui
```

Images are written to `build/ui-check/` and include the three themes, the Add
Download dialog, Options, Themes, progress, queue, scheduler and About windows.
That directory is disposable.

## Redesigned interface

### Window shell

- Title: **IDM – Internet Download Manager**. The window is resizable, compact
  and restores its previous size and position.
- Light grey/white Classic palette: background `#F2F2F2`, panels `#FFFFFF`,
  toolbar `#F7F7F7`, accent `#1683D8`, borders `#D5DDE5`, text `#202020`.
  Completed progress bars use the same classic blue accent.
- Menu bar: **File**, **Downloads**, **View** and **Help**, with every action
  wired to a real operation.
- Toolbar with nine labeled buttons in classic order: **Add URL**, **Resume**,
  **Resume All**, **Pause**, **Stop**, **Delete**, **Options**, **Scheduler**,
  **Queue**. Colored SVG icons, hover/pressed states and tooltips are included.
- Sidebar: All Downloads, Downloading, Completed, Documents, Music, Videos,
  Programs, Compressed Files, with live counts. Selecting a category filters
  the table.
- Search across file names and URLs, with an empty state for empty searches and
  filtered views.
- View menu and Options → User Interface can show or hide the toolbar,
  categories sidebar, download list and status bar. Choices persist.
- Three themes: **Classic Light**, **Modern Light** and **Modern Dark**. The
  theme button in the toolbar cycles through them; View → Theme selects one
  directly. The choice is persisted, and dark mode requests a dark Windows
  title bar.

### Download list

Columns: **File Name**, **Size**, **Status**, **Time Left**, **Transfer
Rate**, **Last Try**.

- File Name shows a category icon, the file name and an inline progress bar
  with a percentage; completed bars use the classic blue accent.
- Status uses a colored indicator dot plus the readable status name.
- Click a column header to sort; click again to reverse the order.
- Row selection supports Resume, Pause, Stop, Delete and the context menu.
- Double-click a completed download to open its folder; double-click any other
  download to open its progress window.
- Empty states cover an empty library, an empty category and no search
  results.

### Add Download dialog

- Fields for Download URL, File Name, Save To with Browse, Category and
  Priority.
- Asynchronous HEAD inspection reports size, resumability and content type,
  and detects the filename from `Content-Disposition`.
- Buttons: **Download Later**, **Start Download** and **Cancel**.
- URL validation rejects non-HTTP(S), credential-bearing and malformed links.
- Duplicate names and existing `.idm.part` files are resolved with unique names.

### Download Progress window

- Modeless window showing file name, URL, status, total and downloaded size,
  transfer rate, time left, last try and a large percentage/progress bar.
- Pause/Resume control, Cancel (stops the transfer), and Open Folder when done.
- A live connection list shows one row per active segment with its own
  progress bar and state, plus the number of connections actually in use.
- A per-download speed limit control applies immediately without restarting
  the transfer.

### Options

Seven tabs: **General**, **Download Settings**, **Save To**, **Connection
Settings**, **User Interface**, **Themes** and **Updates**.

- General: start immediately, restore the download list, confirmation prompts.
- Download Settings: automatic retry, retry attempts and speed limit.
- Save To: default download folder, location mode (default folder, ask every
  time, or file-type rules) and editable extension-to-folder rules with
  duplicate/overlap validation.
- Connection Settings: maximum simultaneous downloads and the number of
  segmented connections per download (1–16).
- User Interface: toolbar, sidebar, download list and status bar switches.
- Themes: three live preview cards. A theme applies immediately; Cancel
  restores the previous theme.
- Updates: HTTPS manifest URL, exact trusted Authenticode publisher and the
  stable/beta channel. Leaving the URL blank falls back to `GITHUB_OWNER` in
  `config.py`. Environment variables can override all three for managed
  deployments.

### About and Check for Updates

- **Help → About IDM** shows the logo, installed version, update channel,
  copyright, developer and storage details, release notes and the update panel.
- **Help → Check for Updates…** opens About and starts a check immediately.
- The check runs on a background thread with timeouts and retry/error messages.
  The panel shows the latest version, release date, release notes and a
  download progress bar during installation-package download. With no update
  it shows exactly:
  “You are using the latest version of IDM.”
- An available release shows installed/latest versions, date, notes, mandatory
  status, a clickable latest-version link and **Install Update**. Mandatory
  updates still require explicit consent.
- When the latest release is already installed and automatic installation is
  available, the same button becomes **Reinstall <version>**, so a damaged
  installation can be repaired with the same verified installer. Your
  downloads, settings and history are kept.
- Installation downloads the installer into `%TEMP%\IDM-Update-*`, verifies
  SHA-256 against the Ed25519-signed manifest and, when a publisher is
  configured, the Windows Authenticode signature. It then saves settings and a
  database backup, hands off to `IDM_Updater.exe` and closes IDM. The updater
  re-verifies the package, runs the Inno Setup installer with normal Windows
  UAC, optionally restarts IDM and cleans up.
- Downgrades are never offered. HTTP, credential-bearing URLs, untrusted hosts
  and packages whose SHA-256 or configured Authenticode signature does not
  match are rejected.
- Configuration, signing, GitHub/custom hosting, publishing steps, security
  invariants and the tested scenarios are documented in
  [docs/UPDATES.md](docs/UPDATES.md). No endpoint or publisher is baked in.

### Import and export

- **File → Export Downloads** writes a JSON snapshot (URL, filename, folder,
  category, priority and status).
- **File → Import Downloads** accepts that JSON format or a plain text list of
  URLs. Imported items are added **paused** so importing a list never starts
  unexpected network traffic. Missing or invalid entries are skipped and
  reported.

## Download engine

- HTTP and HTTPS direct links only; URLs with embedded credentials are
  rejected.
- HTTPS certificates are verified through Requests' default TLS behaviour.
  Certificate failures stop the download with a readable error.
- HTTP Range resume when the server supports it.
- Multi-connection (segmented) transfers with a configurable 1–16 connections
  per download. Each segment requests a bounded byte range and writes into a
  disjoint region of the same `.idm.part` file through a per-segment `r+b`
  handle.
- Segmentation is only used when the server advertises Range support, the file
  is at least 2 MiB, and more than one connection is configured. Small files,
  Range-less servers, servers that drop Range mid-transfer and files without a
  known size always fall back to a single connection without data loss.
- If a server ignores a Range request, the partial file is discarded and the
  download safely restarts from byte zero. If the remote validators (ETag or
  Last-Modified) change, the transfer restarts once instead of mixing versions.
- A segment journal (`<file>.idm.part.json`) records the exact byte range and
  durable progress of every segment. The journal is written atomically and is
  the source of truth for resuming a segmented download after pause, restart
  or power loss.
- The number of simultaneous downloads is configurable from 1 to 10.
- Progress is streamed in 64 KiB chunks with a 250 ms UI update interval, so
  the window stays responsive.
- Speed and ETA are calculated over a rolling time window.
- Pause, stop, remove and cancel requests are cooperative and interruptible.
- Retry with exponential backoff for timeouts, connection drops, HTTP 408,
  425, 429 and 5xx responses. A server's `Retry-After` header is honored for
  the next attempt.
- When the server declares a Content-Length, the file is only finalized after
  the assembled byte count matches. A connection that closes early is treated
  as an error and is never marked complete. A segmented transfer additionally
  verifies the final on-disk size before the rename.
- Data is written to a `.idm.part` file, flushed to disk, and only renamed to
  the final name after the expected size has been verified. The segment
  journal is removed before the atomic rename.
- Existing files are never overwritten. Both the Add dialog and the manager
  choose a unique file name; the final rename also handles a last-second
  collision.
- A global, thread-safe speed limiter applies across all active downloads, and
  a per-download limiter caps a single transfer across all its segments.

## Persistence and scheduler

- Settings, window geometry, download history, per-download segment state,
  the queue and tool history are stored in SQLite under
  `%APPDATA%\IDM Download Manager\database\idm.sqlite3`.
- The schema is versioned with `PRAGMA user_version` and migrated in
  transactions. Migrations only add columns and tables, so existing settings
  and download records are preserved. A pre-migration database is upgraded in
  place without deleting rows.
- Settings live in the `app_settings` table; legacy values from the older
  `settings` table are copied over during the migration.
- Legacy `settings.ini` values are imported once when the database is empty, so
  existing preferences and window geometry are kept.
- On startup, completed items are restored as completed. Active, queued or
  transitioning items are restored as **Paused**, never silently resumed and
  never marked completed. Partial `.idm.part` sizes and segment journals are
  read back so Resume continues from the saved bytes.
- History writes are batched on a 1.5-second timer to avoid disk churn while
  progress updates arrive; segment progress is persisted on pause, retry and
  completion.
- The scheduler can pause or resume all downloads at a chosen time. Entries
  persist in `%APPDATA%\IDM Download Manager\settings\schedules.json`.
- Rotating log file at `%APPDATA%\IDM Download Manager\logs\idm.log`.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+N` | Add URL |
| `Ctrl+R` | Resume selected |
| `Ctrl+Shift+R` | Resume all |
| `Ctrl+P` | Pause selected |
| `Ctrl+Shift+P` | Pause all |
| `Ctrl+Shift+S` | Stop selected |
| `Delete` (table focused) | Remove selected |
| `Ctrl+Shift+Delete` | Delete Completed |
| `Ctrl+Shift+I` | Import downloads |
| `Ctrl+Shift+E` | Export downloads |
| `Ctrl+,` | Options |
| `Ctrl+Shift+T` | Scheduler |
| `Ctrl+Shift+Q` | Queue |
| `Ctrl+F` | Focus search |
| `F1` | Documentation |
| `Ctrl+Q` | Exit |
| `Esc` (search focused) | Clear search / return to list |

## Data locations

All mutable data lives under `%APPDATA%\IDM Download Manager`, never in the
installation directory.

| Item | Location |
| --- | --- |
| Settings and download history | `%APPDATA%\IDM Download Manager\database\idm.sqlite3` |
| Pre-update database backups | `%APPDATA%\IDM Download Manager\database\backups\` (five newest) |
| Application log | `%APPDATA%\IDM Download Manager\logs\idm.log` |
| Updater log | `%APPDATA%\IDM Download Manager\logs\updater.log` |
| Schedules | `%APPDATA%\IDM Download Manager\settings\schedules.json` |
| Legacy settings import | `%APPDATA%\IDM Download Manager\settings\settings.ini` (read once, never created) |
| Default downloads | `%APPDATA%\IDM Download Manager\downloads` (any folder can be chosen in Options) |
| Partial data | `<download folder>\<file>.idm.part` and `.idm.part.json` |

The folder is named `IDM Download Manager` rather than `IDM` on purpose: the
commercial Internet Download Manager owns `%APPDATA%\IDM`, including its own
`downloads` folder and `idm.log`. Keeping the data separate prevents collisions
and makes the uninstaller's optional data cleanup safe. The uninstaller only
deletes `%APPDATA%\IDM Download Manager` when the user explicitly opts in.

All paths are resolved from the Windows application-data environment; no
absolute project paths are hard-coded.

## Architecture

```
main.py                     Application entry point; closes SQLite on exit
updater_main.py             Entry point for the standalone IDM_Updater.exe
idm/
  version.py                Single source of truth for the application version
  constants.py              Categories, priorities, limits; re-exports app metadata
  core/
    paths.py                AppData, assets, download folder locations
    database.py             Versioned SQLite store: settings, history, segments, queue, logs
    settings.py             Settings, SQLite migration, persistence
    url_utils.py            URL validation, filename detection, formatting
    logging_setup.py        Rotating file and console logging
    probe.py                Asynchronous HEAD probe for the Add dialog
    scheduler.py            Persistent pause/resume schedules
  engine/
    worker.py               QThread HTTP transfer, multi-connection orchestration
    segmented.py            Segment planning, atomic journal, recovery inspection
    manager.py              Queue, concurrency, worker lifecycle, persistence
    speed_limiter.py        Thread-safe global and per-download bandwidth limiters
  models/
    download_item.py        Download domain model and status rules
    table_model.py          Table model, sort roles, filter/search proxy
  ui/
    main_window.py          Shell, menus, view toggles, import/export
    theme.py                Three palettes, QSS, Windows title-bar integration
    icons.py                SVG icon set, toolbar icons and logo rendering
    toolbar.py, sidebar.py, status_bar.py, download_view.py, delegates.py
    update_service.py       Qt workers for manifest checks and installer downloads
    dialogs/
      add_download.py       Address, filename, folder and probe
      progress.py           Modeless progress and connection window
      options.py            Seven settings tabs and live theme previews
      about.py              About dialog with the update panel
      update.py             Check/download/verify/install UI workflow
      queue.py, scheduler.py
  updater/                  Qt-free update core shared by the app and updater
    config.py               Endpoint, publisher, channel, trusted hosts and limits
    version_manager.py      Semantic versions and update decisions
    manifest_validator.py   Strict manifest, channel and Ed25519 validation
    update_checker.py       HTTPS fetch, redirect validation, comparison
    update_downloader.py    Resumable streaming download and SHA-256 check
    package_verifier.py     SHA-256 and Authenticode publisher verification
    handoff.py              Validated JSON handoff and safe temp cleanup
    launcher.py             Staging, detached start and stale cleanup
    updater.py              Standalone installer process
assets/                     Logo, toolbar icons, check/chevron SVG assets
config.py                   Central production update configuration
ReleaseNotes.md            User-facing release notes for this version
CHANGELOG.md               Version history
UI-Design-System.md        Design tokens, component rules and accessibility
TestingReport.md           Automated and visual verification record
scripts/                    Release build, hash, signing, validation and packaging tools
IDM-Update-Server/          Separate public manifest repository scaffold
update/latest.json          Local sample manifest (placeholders; not publishable)
docs/UPDATES.md             Configuration, signing, publishing and security guide
tests/                      HTTP server, engine, persistence, updater and UI tests
release/                    Generated release packages (build output, not source)
```

The engine is deliberately independent of the UI and communicates through Qt
signals. All network and file transfer work runs on QThreads; the main thread
only handles UI, queue bookkeeping and signals.

## Security and reliability notes

- Only `http://` and `https://` URLs are accepted.
- URLs containing embedded usernames or passwords are rejected.
- TLS certificate verification is left enabled; there is no option to
  disable it or bypass authentication, DRM or access controls.
- Redirects are followed only to HTTP/HTTPS addresses.
- Downloaded files are never executed automatically.
- Temporary `.idm.part` files prevent incomplete data from masquerading as a
  finished download. Segment journals are written atomically and validated on
  load; a corrupt, overlapping or out-of-bounds journal is discarded and the
  transfer restarts instead of trusting bad state.
- Existing files are protected by unique naming and an atomic rename.
- Concurrency is bounded and server rate-limit responses are respected via
  retry backoff and `Retry-After`.
- Restored queued/active entries are forced to Paused so a restart cannot
  begin hidden network activity.
- Update checks use HTTPS only and reject embedded credentials, IP literals,
  untrusted hosts and redirects outside the configured host allowlist.
- Update installers are accepted only after SHA-256 and exact-publisher
  Authenticode verification, by both the application and the separate updater.
  Only a verified `.exe` is run; no scripts or server-provided commands are
  executed.
- Updates are never installed silently: every installation requires user
  confirmation; mandatory updates are still cancellable. UAC, Defender and
  SmartScreen are never bypassed.
- The running executable is never overwritten. The updater runs from the temp
  update folder after IDM closes.
- User data is independent of the installation directory and is never modified
  by an update or a default uninstall.
- Browser integration validates every request twice (native host and desktop
  service), allowlists the extension IDs and binds the bridge to localhost with
  a per-run token. It accepts only HTTP(S), rejects unsafe file names and
  folder traversal, creates folders only with approval, and never cancels the
  browser download before IDM confirms acceptance. It does not collect
  credentials, cookies or tokens, execute shell commands, read arbitrary local
  files, or bypass DRM, paywalls, logins or access controls.

## Testing coverage

The test suite uses a local threaded HTTP server with routes for:

- Range-capable downloads (bounded `bytes=start-end` requests) and servers that
  ignore Range
- slow transfers for pause/resume/stop and progress-window tests
- HTTP 404, 500 and 429 with `Retry-After`
- truncated responses (declared size larger than the body)
- duplicate names, active-name reservations and max-concurrency limits
- invalid URLs and URL credential rejection
- scheduler pause/resume actions
- Add-dialog HEAD probing, Content-Disposition detection, validation and both
  Start Download / Download Later modes
- table filters, search, header sorting, toolbar/menu state and all three themes
- queued downloads remaining queued and persisted as queued
- SQLite settings round-trip and restoring active/queued items as paused
- segmented plan coverage and journal round-trip, invalid-journal rejection
- multi-connection requests, no-Range single-connection fallback
- pause/resume of a segmented download across a simulated manager restart,
  including segment-journal and database segment recovery
- per-download speed-limiter enforcement and live limit changes
- schema migration from version 1 to the current version without losing
  settings or download rows, plus segment/queue/log round-trips and cascades
- import/export round-trip and download-list parsing
- isolated application-data layout and default download folder, including a check
  that the commercial `%APPDATA%\IDM` folder is never used
- semantic version comparison, pre-releases, no-downgrade and mandatory decisions
- stable/beta channel policy and channel-mismatch rejection
- manifest field validation, unknown/duplicate detection, unsafe URL/host
  rejection and BOM/UTF-8 handling
- optional Ed25519 signed-manifest verification (valid, tampered, wrong key,
  unsigned and malformed keys)
- manifest fetch success, HTTP failures, timeouts, TLS/connection errors,
  redirect-chain rejection and size limits
- installer download success, resume with HTTP Range, restarts when Range is
  ignored, 416 recovery, truncation, cancellation, wrong SHA-256 and size caps
- SHA-256/Authenticode verification, exact publisher matching and signature
  output parsing
- handoff validation, updater staging/launch, completion markers, safe temp
  cleanup, install arguments and updater success/cancel/failure flows
- About/update panel statuses, release notes, mandatory consent and the
  clickable latest-version workflow
- central configuration precedence, release signing CLI and manifest validator CLI
- native messaging framing (little-endian length prefix), truncation, 1 MiB
  limits, invalid JSON, URL/filename/MIME/size validation and duplicate TTL
- extension allowlisting, pinned key-derived Chrome/Edge IDs, Firefox Gecko ID,
  browser-specific `allowed_origins` / `allowed_extensions` manifests
- default/ask/file-type location modes, wildcard and duplicate-rule rejection,
  missing-folder approval, disk-space headroom, traversal and reserved-name
  rejection
- loopback bridge token authentication, malformed frames and status round-trip
- service acceptance, ask cancellation, unauthorized extensions, duplicate
  requests and duplicate URLs, browser metadata persistence and list/open
- native host offline/connected status, browser mismatch, forwarding and
  idempotent download requests
- registry installation and conflict-safe uninstallation using an in-memory
  registry, manifest validation and both 64/32-bit views
- extension manifests, deterministic store ZIP packages and installer/build
  integration for `IDM_NativeHost.exe`
- offscreen UI rendering and native screenshots

Run everything with `python -m pytest tests -q` (currently 460 tests).

## Roadmap

| Area | Scope | Status |
| --- | --- | --- |
| Phase 1 | Application shell, working single-connection engine, queue, scheduler, tests | Delivered |
| UI redesign | Classic IDM layout, nine-button toolbar, menus, progress window, six-tab Options, three themes, import/export | Delivered |
| Phase 2 | Multi-connection segmented engine, crash-safe segment journal, restart recovery, per-download speed limit, versioned SQLite migrations | Delivered in this build |
| Phase 5 | SQLite persistence, history restoring and restart recovery | Delivered in this build |
| Phase 7 | Clipboard link monitoring | Not started |
| Phase 8 | Chrome, Edge and Firefox extensions, native messaging host, authenticated desktop bridge, download interception with safe fallback, browser metadata/history | Delivered in this build (manual browser/Windows 10 validation pending) |
| Browser locations | Default, ask-every-time and file-type download destinations with editable rules and filesystem safety | Delivered in this build |
| Packaging | PyInstaller onedir build, standalone updater, Inno Setup installer, Start Menu/desktop/startup shortcuts, upgrade and uninstall, user-data preservation | Delivered in this build (unsigned; Windows 10 validation pending) |
| Updates | About/check/compare, stable/beta channels, signed manifest, resumable download, SHA-256 + Authenticode, separate updater, state backup and restart | Implemented; requires `GITHUB_OWNER`, a code-signing certificate and a tested public release before it is operational |
| Later | Notifications, tray integration | Not started |

The interface does not pretend that unimplemented features already exist.
Planned features are shown as disabled controls or explanatory notes, and are
only announced as available after they are implemented and tested.
