# IDM 3.0.0 — Release Notes

**Release date:** 2026-11-01
**Platform:** Windows 10/11 x64
**Channel:** stable

Version 3.0.0 is a major upgrade of the IDM desktop download manager. It
replaces the classic single-list interface with a multi-page workspace, adds a
dedicated IDM Video Assistant browser extension for Chrome and Edge, upgrades
the native messaging protocol to version 2, raises the database schema to
version 4 and strengthens download, update and installer security.

The Python/PySide6 architecture, the segmented download engine, the SQLite
database, the existing browser integration host and the automatic updater are
preserved. Existing user data is migrated in place and is never reset.

## Highlights

### Next-generation desktop interface

The main window now provides a navigation rail with these pages:

- **Dashboard** — active transfers, queue state, recent activity and disk
  status at a glance.
- **Video Downloads** — direct media transfers with Title, Filename, Format,
  Size, Progress, Speed, ETA, Status and Source Domain columns, plus
  Start, Pause, Resume, Cancel, Open File, Open Folder and Delete Record
  actions.
- **All Downloads** — the complete download list and history.
- **Browser Integration** — connection status, host registration and setup
  guidance for the IDM Video Assistant.
- **Download Analytics** — totals, category breakdown and transfer history
  computed from the local database.
- **Performance Monitor** — concurrency, connection count, live throughput and
  the global speed limit.
- **Advanced Settings** — folders, transfer behaviour, interface and
  maintenance tools.
- **Update Center** — update checks, signed release status, update history,
  backups and rollback tools.
- **Notifications** — completion, failure and update notices stored locally.

All pages are backed by real application state. Light and dark themes are
available and follow the existing original IDM branding.

### IDM Video Assistant browser extension

A new Manifest V3 extension is included at
`BrowserExtension/IDMVideoAssistant/` for Chrome and Edge. It:

- Detects ordinary downloadable media links in pages and, where the browser
  exposes them, HTML5 `<video>` and `<audio>` sources.
- Shows format, size and quality only when those values are legitimately
  observable; otherwise the fields stay empty.
- Sends supported direct media URLs to the desktop application through the
  `com.idm.native` messaging host.
- On YouTube and YouTube Music pages, shows Google's own official download
  options (Premium, YouTube Studio creator downloads and the YouTube Help
  article) instead of extracting streams.
- Never lists `googlevideo.com` or other restricted stream URLs, even when a
  non-YouTube page embeds them.
- Shows connection status and download processing notifications.
- Lets users enable or disable detection, choose supported file types, and set
  whether IDM asks where to save.
- Requests the minimum permissions: `nativeMessaging`, `downloads`,
  `contextMenus`, `storage` and `activeTab`. It does not request browsing
  history.

The extension does not bypass DRM, access controls or platform restrictions.
Restricted platforms, protected streams and browser-internal saves stay in the
browser.

### Media download engine

- Direct HTTP/HTTPS media transfers for MP4, WebM, M4A and related formats.
- Content-Type and size detection, HTTP Range support, pause/resume,
  multi-connection transfers and automatic network recovery.
- Retry with backoff, integrity verification with SHA-256, and media
  categorisation.
- Server restrictions are respected; no protected stream extraction, no
  signature deciphering and no unauthorized scraping.

### Secure desktop bridge

- Native messaging protocol version 2 carries page title, media kind, quality
  label, duration and detection source in addition to the URL and filename.
- Every field is validated and allowlisted on the desktop side. Message size is
  strictly limited.
- Connections use an authenticated loopback bridge. The desktop confirms each
  download request and reports errors back to the extension.
- URLs are restricted to HTTP/HTTPS, filenames are sanitised and path traversal
  is rejected before any file is created.

### Database schema version 4

- New `media_metadata` table stores observed media information.
- New `notifications` and `download_events` tables back the Notifications and
  Analytics pages.
- Migrations are additive and versioned. A verified backup of the database is
  created before migration.
- History, settings, queue, paths, browser configuration and update settings
  are preserved. The database is never reset.

### Performance and security

- Faster list refresh, incremental UI updates and reduced database writes on
  the hot path.
- HTTPS-only update and manifest endpoints, validated URLs, safe filenames,
  minimum browser permissions and secure file handling.
- Update manifests are verified with an embedded Ed25519 public key and
  SHA-256. Installers can additionally be verified with Windows Authenticode
  when a trusted publisher is configured.

### Update Center and installer

- Automatic update checks every 24 hours with release notes, signed manifest
  verification, SHA-256 verification, a pre-update database backup, staged
  installation and rollback.
- `IDM-Setup-3.0.0.exe` performs an in-place upgrade from Version 2.x,
  preserves user data, refreshes browser integration and registers the native
  messaging host for Chrome and Edge.
- The installer ships the unpacked extension folder and never installs an
  extension silently. Clear Chrome and Edge instructions are shown after
  installation and in the Browser Integration page.

## Upgrade notes

- Installing 3.0.0 over 2.0.0 or 2.0.1 upgrades in place. The first launch
  migrates the database to schema version 4 after making a verified backup.
- Browsers with the 2.x extension should remove it and load the 3.0.0 unpacked
  extension; the pinned extension ID is unchanged, so the native host
  registration continues to work.
- Partial downloads created by 2.x resume normally.

## Verification

`Checksums.txt` lists the SHA-256 digest of every file in this release folder.
On Windows, generate a digest with:

```bat
certutil -hashfile IDM.exe SHA256
certutil -hashfile IDM-Setup-3.0.0.exe SHA256
```

Compare the result with the matching line in `Checksums.txt`.

## Known limitations

- The application, installer and updater are not code-signed. Windows
  SmartScreen may warn on first launch.
- Automatic installation remains disabled until a CA-issued Authenticode
  certificate and a trusted publisher are configured. In that state the Update
  Center offers the signed manifest's installer for manual download.
- Windows 10 support is provided by the installer configuration; this build was
  validated on Windows 11 x64 only.
- DRM-protected streams, Blob/MediaSource streams, browser-internal saves and
  authenticated sessions that require browser cookies are intentionally not
  downloaded.
- The unpacked extension must be loaded manually; browsers do not permit IDM to
  install it silently.
- The latest Video Assistant package is published separately as
  `IDM_Video_Assistant_3.0.0.zip` and is also included in the Windows release
  bundle. Reload that folder after upgrading to pick up the final popup and
  YouTube official-options changes.
