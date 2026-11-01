# IDM 3.6.0 — Release Notes

**Release date:** 2026-11-01
**Platform:** Windows 10/11 x64
**Channel:** stable

Version 3.6.0 makes every new download start from a real **Download File Info**
dialog. Manual link entry, the browser extensions and the context menus all open
the same review screen, where the file name, category, destination folder,
optional description and start time are confirmed before any transfer is queued.
The dialog reads the real server metadata, so the size, type, resume support and
last-modified values shown are the ones the server reported — or an em dash when
the server did not report them.

Existing settings, history, queue entries, partial downloads, browser
registration and update configuration are preserved. The database migrates from
schema version 4 to 5 with a verified backup first; downloads added by older
versions keep their rows and gain empty `description` and `start_later` values.

## Highlights

### Download File Info dialog

- URL field with full-link copy, so long or tokenised links can be reused
  without truncation.
- Category selector with General, Compressed, Documents, Music, Videos,
  Programs, Images and Other, plus automatic detection from the filename
  extension and, when needed, the server MIME type.
- Editable **Save as** name and **Save to** folder with the native Windows
  folder picker, the detected extension, and validation for unsafe names, path
  traversal, missing folders and obvious free-space problems.
- **Remember this folder for “Category”** stores a per-category default that is
  also editable from Settings.
- Optional description (up to 2,000 characters) saved with the download record.
- File information panel: size, MIME type, source host, server status, last
  modified and resume support, with unknown values kept honest.
- Windows 11-style presentation: branded header, gradient file hero card with
  category and extension chips, icon-led fields, a server information card and
  a subtle animated primary action in light, dark and Follow-Windows themes.
- Resizable and scrollable: opens at 800×920 where space allows, clamps to the
  screen and keeps its footer reachable down to 640×560.

### Server metadata detection

- A `HEAD` request first. Redirects are followed, and the final URL, status,
  `Content-Length`, `Content-Disposition`, `Content-Type`, `ETag`,
  `Last-Modified` and `Accept-Ranges` are recorded.
- If `HEAD` is rejected, a single `GET` with `Range: bytes=0-0` is used and
  aborted as soon as the headers arrive. IDM never downloads a whole file to
  inspect it.
- Unknown size, missing `Content-Disposition`, servers without Range support,
  timeouts and network failures are reported honestly. IDM does not claim
  resume or multi-connection support that the server did not advertise.
- Pending probes are aborted when the URL changes or the dialog closes.

### Start, Later and Cancel

- **Start Download** validates the URL and folder, refuses an active duplicate,
  checks the destination, creates the database record and hands the task to the
  engine. The dialog closes only after the task exists; failures stay visible
  with a clear message.
- **Download Later** stores the complete task in the queue without starting any
  network transfer. It survives a restart and starts from the Queue Manager with
  **Start now**.
- **Cancel** creates no record and cancels pending metadata requests.

### Browser integration

- Chrome, Edge and Firefox downloads now open the Download File Info dialog
  instead of being added silently. The detected browser, referrer, page and
  MIME type are kept on the record.
- The browser copy stays paused while the dialog is open. It is cancelled only
  after IDM confirms the task; cancelling the dialog or any error resumes the
  original browser download, so a file is never discarded.
- Requests are handled one at a time, simultaneous downloads queue behind the
  dialog, and a URL that is already active is answered without a second prompt.
- The extension manifests are version 3.6.0. No new browser permission is
  requested.

### Database and engine

- Schema version 5 adds `description` and `start_later` to the download table.
- Before migrating, IDM writes a verified backup under
  `%APPDATA%\IDM Download Manager\backups\`; an integrity-check failure stops
  the upgrade instead of changing data.
- Held tasks are stored as queued with `start_later = 1`, do not consume an
  active slot, and are excluded from automatic queue pumping until released.

### Security

- Only `http` and `https` links are accepted; `file:`, `javascript:`, `data:`
  and other schemes are rejected.
- File names are sanitised and the resolved path must stay inside the chosen
  folder. Windows-reserved names and credentials in URLs are rejected.
- Logs redact URL credentials, query strings and fragments; cookies and
  authentication headers are never logged, and the extension never forwards
  browser cookies or client certificates.
- The extension remains limited to `nativeMessaging`, `downloads`,
  `contextMenus`, `storage` and `activeTab`; there are no host permissions,
  cookie access or content injection.
- Downloaded files are never executed or opened automatically.

## Preserved and unchanged

- Segmented HTTP Range engine, up to 16 connections, resume, retry, speed
  limits and the persistent queue.
- All 3.5.0 workspace pages: navigation rail, dashboard, virtualized download
  table, video cards, Browser Assistant, Settings and Update Center.
- SQLite history, verified backups, extension settings and saved downloads.
- Ed25519 manifest signatures, SHA-256 and Authenticode verification for
  updates.
- No DRM bypass, no protected stream extraction and no signature deciphering.

## Upgrade notes

- Install `IDM-Setup-3.6.0.exe` over 3.5.0 or any earlier release. The same
  AppId, installation directory and `%APPDATA%\IDM Download Manager` user-data
  folder are reused.
- The first 3.6.0 start migrates schema version 4 to 5 after writing a backup.
  Existing downloads, settings, queue order and partial files are preserved.
- The pinned Chrome/Edge extension ID is unchanged, so the existing native-host
  registration keeps working. Reload the unpacked extension so the browser
  reports version 3.6.0.
- The signed public update feed advertises 3.6.0 after the release manifest is
  signed and published. Until then the Update Center reports that the installed
  build is already current.

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
- `dist-installer\IDM-Setup-3.6.0.exe` — installer
- `release\IDM-3.6.0-win64.zip` — bundle with installer, portable build,
  extensions, documentation and SHA-256 sums

See `UI-Design-System.md` for the design tokens and component rules and
`TestingReport.md` for the verification record.
