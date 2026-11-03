# IDM 3.6.3 — Release Notes

**Release date:** 2026-11-03
**Platform:** Windows 10/11 x64
**Channel:** stable

Version 3.6.3 is a capability release on top of the 3.6.2 Hybrid UI. The
download engine, the browser bridge and the surrounding tools gained the pieces
that were missing before, and the interface gained the windows that make a
transfer inspectable while it runs. The 3.6.2 shell, themes, dashboard, list
columns, sorting and responsive behaviour are unchanged, and existing settings,
history and partial files carry over.

## Highlights

### Measured bandwidth limiting

- Options → Download Settings now has three limit modes: **No limit**, **Fixed
  maximum** and **Percentage of the measured link**.
- The percentage is taken from a rolling estimate of the connection built from
  the bytes IDM actually moved, so the limit falls when the link falls instead
  of staying pinned to a number typed in months ago.
- A transfer that is sitting on its own cap is never recorded as a measurement
  of the link. Without that rule a 500 KB/s limit would "measure" a 500 KB/s
  connection and keep agreeing with itself.
- **Measure the link now** lifts the limit for a five-second window while a
  download runs, because a percentage limit cannot discover the ceiling it is
  pinned under. The figure is stored and re-used after a restart.
- Nothing can be measured on an idle connection; the dialog says so rather than
  inventing a number.

### Speed over time

- The Download Progress window plots one reading per second, with the current,
  peak and average speed.
- A dashed line marks the limit that is actually binding — the tighter of the
  global cap and the per-download cap — which is how you tell a slow server from
  a limit you forgot about.
- The graph is drawn by a new `SpeedGraph` widget in the shared design system,
  so it follows Light, Dark and Classic palettes.

### Download tools

- **Properties** window with General, Transfer, Integrity, Source and Last error
  sections, the real size on disk, and Copy Link / Open Folder / Open actions.
- **Open**, **Open Containing Folder** and **Properties** in the Downloads menu
  and the list context menu.
- **Rename** writes the file and the record together and rolls back if either
  step fails; changing the extension re-detects the category.
- **Refresh Download Link** re-resolves a link that has gone stale.
- **Verify Checksum** computes the SHA-256 of a finished file and compares it to
  the checksum the download was given. Automatic verification that fails discards
  the partial file instead of keeping it.
- **Add Batch Downloads** (`Ctrl+Shift+U`) takes a list of URLs, drops duplicates,
  caps the batch at 500 and starts them into one folder.
- **Delete Completed** now states how many entries it will clear and asks first,
  honouring the existing "ask before removing" setting. Files stay on disk.

### Engine

- **FTP and FTPS** transfers with passive mode and `REST` resume, with readable
  errors for 530, 550 and 421 replies.
- **Dynamic re-segmentation**: a connection that falls behind has half of its
  unclaimed tail handed to an idle connection, so one slow stream no longer
  decides when the download finishes.
- **Redirects** are followed up to eight hops by the engine itself, and stored
  credentials are dropped when the chain leaves the original host.
- Segments are granted to a worker in 8 MiB slices rather than whole, which is
  what makes the rebalancing above possible.

### Around the application

- **System tray**: minimise to the tray, Pause all / Resume all / Quit from its
  menu, a live summary in the tooltip, and native Windows notifications that can
  be switched off.
- **Start IDM when I sign in to Windows**, read from both the HKCU Run key and
  the Startup folder so a change made outside IDM is still reported honestly.
- **Connection Settings**: system, direct or manual HTTP/HTTPS proxy with bypass
  matching, per-site credentials for HTTP 401 responses, and connect and read
  timeouts.
- **Page link capture** in the Video Assistant: collect the downloadable links on
  a page, send them through the native host, one folder prompt for the batch.
- **Brave and Opera** are detected and registered; Chrome and Edge builds now
  report which browser they are really running in.
- **Live bridge status** on the Browser Integration page, so you can see the
  native host answering without staging a test download.
- **General** library destination for files that match no rule.

### Security and privacy

- Passwords for proxies and sites go to Windows Credential Manager. The settings
  database stores host, user and scheme only — no password is ever written to
  disk in plain text.
- Every log record passes through a secret scrubber, so a URL carrying a token or
  an `Authorization:` header cannot leak into the log file, including inside
  free-form error text.
- Media platform restrictions are enforced in the download engine, not only in
  the dialogs, so a refused source is refused whichever route it arrives from.
  IDM does not bypass DRM, paywalls or any access control.
- Destination folders are validated before use, filenames are sanitised, and
  executable downloads ask for confirmation before being opened from the list.

## Preserved functionality

- Segmented HTTP downloads over up to 16 connections, Range resume after a
  restart, automatic retry, queue and priority handling.
- Categories including custom ones, download history, clipboard monitoring,
  scheduler, import/export of the download list and the update feed.
- Chrome, Edge and Firefox integration through the native messaging host and the
  localhost bridge, including the Download File Info review dialog.
- The 3.6.2 interface: Hybrid Fluent Light and Dark, the dashboard cards,
  responsive columns, the More menu and the refresh and sort controls.

## Upgrade

- Install `IDM-Setup-3.6.3.exe` over 3.6.2 or any earlier release. The same
  `AppId`, installation directory and `%APPDATA%\IDM Download Manager` data are
  reused.
- Settings from 3.6.2 load unchanged. A non-zero `speed_limit_kbps` still means a
  fixed limit; the new `speed_limit_mode`, `speed_limit_percent` and
  `measured_capacity_kbps` keys are additive and the database schema is
  unchanged.

## Artifacts

- `dist\IDM\IDM.exe` — portable application with `_internal\`,
  `IDM_Updater.exe` and `IDM_NativeHost.exe`
- `dist-installer\IDM-Setup-3.6.3.exe` — installer
- `release\IDM-3.6.3-win64.zip` — bundle with installer, portable build,
  extension archives, documentation and `SHA256SUMS.txt`
- `dist-extensions\IDM_Video_Assistant_3.6.3.zip` — Video Assistant package

The SHA-256 of every artifact is recorded in `SHA256SUMS.txt` inside the bundle
and in the release asset list.

## Known limitations

- The installer is unsigned unless a CA-issued Authenticode certificate is
  configured; the signed update manifest and SHA-256 remain the trust anchors.
- Windows 10 is supported by the installer configuration but validation runs on
  Windows 11 x64.
- Real browser interception still needs a manual pass in Chrome, Edge, Brave and
  Opera; the native host, bridge, protocol and prompt contract are covered by
  automated tests.
- A percentage limit follows a link downward on its own but cannot climb back to
  a faster connection without a measurement, because the limit hides the ceiling
  it is pinned under. Use **Measure the link now** after moving to a quicker
  network.

## Not implemented in 3.6.3

Requested during this release and left out, listed so the gap is on the record:

- SOCKS and per-protocol proxies (HTTP/HTTPS proxying only).
- MD5 and SHA-1 verification (SHA-256 only).
- Antivirus scanning of finished downloads.
- Adaptive streaming: HLS `.m3u8` and DASH `.mpd` manifests are recognised as
  video but not parsed, so there is no segment merging, quality selection,
  audio-only extraction, subtitles or playlist handling.
- An in-application log viewer.
- Named queues with per-queue rules; the queue is shared and ordered by priority.
- Segmented FTP; FTP uses a single connection.
- Page-link capture in the Chrome, Edge and Firefox modules; it ships in the
  Video Assistant only.
- Any bypass of DRM, paywalls or a site's access controls.
