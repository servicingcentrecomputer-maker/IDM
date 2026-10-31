# IDM Browser Integration

IDM integrates with Google Chrome, Microsoft Edge and Mozilla Firefox through
a browser extension plus a native messaging host. When interception is enabled,
the extension pauses the browser's own download, asks IDM to accept it, and
cancels the browser copy **only after IDM confirms acceptance**. If IDM is not
running, rejects the link, or the native host is unavailable, the browser
download is resumed so the user still gets the file.

## Components

| Component | Location | Purpose |
| --- | --- | --- |
| Native messaging host | `IDM_NativeHost.exe` (built), `integrations/native_host.py` (source) | Stdio process started by the browser; validates every message and forwards it to IDM |
| Shared protocol | `integrations/protocol.py` | Framing, strict validation, duplicate tracking, response shapes |
| Browser allowlist | `integrations/browser_registry.py` | Pinned extension IDs, `allowed_origins` / `allowed_extensions` manifests |
| Registration | `integrations/registration.py`, `scripts/register_native_host.py` | Writes browser manifests and per-user `HKCU` registry values |
| Desktop bridge | `integrations/bridge_server.py` | Authenticated 127.0.0.1 NDJSON endpoint |
| Desktop service | `integrations/service.py` | Adds accepted transfers to the existing queue and answers status/list requests |
| Location policy | `downloads/location_manager.py` | Default / ask / file-type destination modes and filesystem safety |
| Chrome extension | `extensions/chrome/` | Manifest V3 service worker, popup and context menu |
| Edge extension | `extensions/edge/` | Manifest V3; same key and extension ID as Chrome |
| Firefox extension | `extensions/firefox/` | Manifest V2 persistent background page with a stable Gecko ID |

The native host is a separate executable built without PySide6. It only speaks
the four-byte little-endian length-prefixed JSON protocol on stdin/stdout; all
diagnostics go to `%APPDATA%\IDM Download Manager\logs\native_host.log` and
stderr.

## Installation

### Normal installation

`IDM_Setup.exe` copies `IDM_NativeHost.exe` next to `IDM.exe` and offers one
optional task per browser:

- **Integrate with Google Chrome**
- **Integrate with Microsoft Edge**
- **Integrate with Mozilla Firefox**

A task is shown as checked only when the browser is detected. Selecting a task
writes the browser-specific native messaging manifest into
`{app}\browser-integration\` and registers it under the current user only:

```
HKCU\Software\Google\Chrome\NativeMessagingHosts\com.idm.native
HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.idm.native
HKCU\Software\Mozilla\NativeMessagingHosts\com.idm.native
```

Both the 64-bit and 32-bit registry views are written because browsers may run
as either architecture. Chrome and Edge receive `allowed_origins`; Firefox
receives `allowed_extensions`. Uninstalling removes only IDM's own value and
only deletes the key when nothing else remains.

The installer ships extension ZIP packages in
`{app}\browser-extensions\` and never installs an extension into a browser.
Browser stores prohibit silent installation, and sideloading without an
explicit policy is intentionally not attempted.

### Manual or development registration

Build the host first, then register from an elevated-free shell:

```powershell
.\.venv\Scripts\python.exe scripts\register_native_host.py install
.\.venv\Scripts\python.exe scripts\register_native_host.py status
```

Useful options:

| Option | Effect |
| --- | --- |
| `--browser chrome` | Limit to one browser (repeatable) |
| `--installed` | Only act on browsers detected on this machine |
| `--host-path <exe>` | Register a specific absolute `IDM_NativeHost.exe` |
| `--dev` | Write a `.cmd` launcher for `integrations/native_host.py` (development only) |
| `--json` | Machine-readable output |

`--dev` is a convenience for source checkouts. Chromium's native messaging
documentation defines `path` as an executable path; use the packaged
`IDM_NativeHost.exe` for real installations and store submissions.

To load the unpacked extensions while developing:

- Chrome: `chrome://extensions` → Developer mode → **Load unpacked** →
  `extensions\chrome`.
- Edge: `edge://extensions` → Developer mode → **Load unpacked** →
  `extensions\edge`.
- Firefox: `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on**
  → `extensions\firefox\manifest.json`.

The Chrome and Edge manifests embed a development public key so the unpacked
extension keeps the ID `ljckgbgnolmopacdgmmgaijleadcmpgn` across reloads. This
key was generated only to pin that development ID; it is not used to sign
packages. Store-assigned IDs and signed Firefox XPI IDs must be supplied to the
host allowlist with `IDM_CHROME_EXTENSION_ID`, `IDM_EDGE_EXTENSION_ID` and
`IDM_FIREFOX_EXTENSION_ID` (or by rebuilding the constants in
`integrations/browser_registry.py`). See
[BROWSER_STORE_PUBLISHING.md](BROWSER_STORE_PUBLISHING.md).

## Download interception

1. Chrome or Edge creates a download (`downloads.onCreated`); Firefox uses the
   same event through `browser.downloads`.
2. The extension ignores downloads it did not create, downloads started by an
   extension (`byExtensionId`), non-HTTP(S) URLs, and URLs it just handed to
   IDM (a 15-second suppression cache).
3. The browser download is paused first. The extension then sends a
   `request_download` message containing URL, filename, referrer, MIME type,
   declared size and an optional `ask_folder` flag.
4. The native host validates the message, checks the browser/extension
   allowlist, and forwards it over the authenticated loopback bridge.
5. The desktop service validates again, resolves the destination folder and
   adds the task to the existing `DownloadManager` queue.
6. Only when the response is `download_accepted` does the extension cancel the
   browser download. Otherwise it resumes the browser download and shows a
   short error badge instead of losing the file.

The right-click menu adds **Download with IDM** and **Download with IDM to…**
for links. The first uses the saved location mode; the second sends
`ask_folder: true` and always opens IDM's folder picker. Neither creates a
hidden browser download.

The popup shows connection state, active/queued/total counts, the default save
folder, recent transfers and the last error. It provides:

- an interception toggle stored in browser storage;
- an **Ask where to save** toggle that adds `ask_folder: true` to every
  intercepted download without changing the saved location mode; it is enabled
  by default, so users choose a folder for each browser download unless they
  switch it off;
- **Open IDM** and **Download Settings**;
- **Test Connection**, which performs a real native-host status request.

Popup content is rendered with `textContent`; browser- or server-supplied names
are never inserted as HTML.

## Download locations

IDM supports three modes, stored in the SQLite settings database:

| Mode | Behavior |
| --- | --- |
| Default location | Every browser download goes to the configured default folder |
| Ask every time | A folder dialog appears for each download; cancelling aborts it |
| File type based | Extension rules choose a folder; unmatched files use the default |

A request can also carry `ask_folder: true`. This is sent by the popup's
**Ask where to save** toggle and by **Download with IDM to…**, and it opens the
folder picker for that single download even when the saved mode is Default or
File type. Cancelling the picker answers `cancelled`, so the extension resumes
the browser download and IDM adds nothing.

A rule is a folder plus a list of extensions (`zip`, `.pdf`, `*`). Rules are
normalized (lowercase, no leading dot), duplicates are rejected, and only one
catch-all `*` rule is allowed. Recommended rules create Archives, Software,
Documents, Media and Images folders under the default location.

Safety guarantees:

- Paths must be absolute Windows paths (`C:\...`) and must not contain `..`,
  control characters or reserved device names.
- A missing folder is created only when the user (or the integration's
  approval callback) agrees.
- A free-space check runs before a transfer and reserves 32 MiB or 2% of the
  size, whichever is larger.
- File names may not contain path separators or Windows-reserved characters;
  the final path is resolved and must stay inside the chosen folder.
- Duplicate names are made unique by the existing manager (`name (1).ext`),
  including names reserved by active downloads.
- Only HTTP and HTTPS URLs are accepted. Embedded credentials, `file:`,
  `javascript:`, `data:` and other schemes are rejected.

## Data and diagnostics

The product deliberately uses `%APPDATA%\IDM Download Manager` instead of the
brief's `%APPDATA%\IDM`, because the commercial Internet Download Manager uses
the latter. Sharing it would mix two products' data and make uninstall cleanup
unsafe. Existing IDM behavior and user data take precedence; the test suite
asserts the commercial folder is never touched.

```
%APPDATA%\IDM Download Manager\
    database\idm.sqlite3
    logs\idm.log
    logs\native_host.log
    runtime\browser_bridge.json     Random port + per-run token; removed on exit
    native_messaging\               Manifests and optional .cmd dev launcher
```

Diagnostics:

```powershell
.\.venv\Scripts\python.exe scripts\register_native_host.py status
```

The status output reports the manifest path, host path, registry views,
conflicts and missing files. The popup's **Test Connection** exercises the same
path the extension uses.

## Security model

- The browser is never trusted. URL scheme, length, filename and metadata are
  validated by the native host and again by the desktop service.
- Only the pinned extension IDs may control IDM. Registry configuration alone
  is not treated as authorization.
- The native host communicates with the browser only through stdio frames; it
  never writes arbitrary data to stdout.
- The loopback bridge binds to 127.0.0.1 on a random port, requires a 32-byte
  random token regenerated each run, closes malformed or oversized frames, and
  stops accepting after repeated authentication failures.
- No shell commands, arbitrary file reads, browser cookies, passwords or
  tokens are accepted or forwarded. Authenticated browser sessions are not
  reused; see the limitations below.
- No DRM, paywall, login or access-control bypass is implemented.
- The extension requests only `nativeMessaging`, `downloads`, `contextMenus`
  or `menus`, and `storage`. It has no content scripts, host permissions,
  `webRequest`, `tabs` or cookie access.

## Browser limitations

These are platform constraints, not configuration options:

| Area | Limitation |
| --- | --- |
| POST / streaming | `chrome.downloads` only exposes completed download URLs. Form POSTs, Blob URLs, MediaSource streams, HLS/DASH segments and in-memory responses cannot be sent to IDM. They stay in the browser. |
| Authenticated downloads | IDM performs its own HTTP request without the browser's cookies or client certificates, so session-bound downloads may return an error page. The original file is not lost because the browser copy is resumed when IDM rejects it. |
| "Save as" and print-to-PDF | Browser-internal saves may not produce an ordinary download item and can bypass interception. |
| Private/incognito windows | Extensions must be explicitly allowed in private windows; enterprise policy may disable this. |
| Interception races | A download can progress briefly before it is paused. The extension cancels only after IDM acceptance, so a failed request resumes from the browser's current progress. |
| Service worker suspension | Chrome/Edge MV3 may suspend the service worker. Interactive native messages are awaited; the duplicate cache makes a retried request idempotent. Firefox uses a persistent MV2 background page. |
| Store IDs | Store packaging may assign a different extension ID. The native host allowlist must be updated to that ID; the embedded development key is not a store signing key. |
| Native host path | Chromium expects the manifest `path` to point to an executable. The `--dev` `.cmd` launcher is for development only. |
| Firefox signing | Release Firefox only installs signed XPIs. Temporary add-ons work for development; distribution requires signing through Mozilla Add-ons. |
| Browser API versions | Chrome/Edge require Chrome 102+ for the MV3 APIs used; Firefox requires 109+. |

## Verification

Automated coverage in `tests/` includes protocol framing and limits, URL and
filename validation, duplicate tracking, allowlist and manifest generation,
location modes and filesystem safety, bridge token authentication, service
acceptance/ask/duplicate/unauthorized paths, native-host dispatch and offline
behavior, registry installation and conflict-safe removal, extension manifests
and deterministic ZIP packages, installer/build integration and SQLite browser
metadata. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

The extension's real pause → native request → cancel/resume sequence requires a
real browser and a running desktop app. It is verified by code review and a
manual checklist; it is not simulated by a headless test:

1. Start IDM and open the popup; confirm connected status and counts.
2. Download a large ZIP with interception on; confirm it appears in IDM, the
   browser entry disappears, and progress matches.
3. Stop IDM, start a browser download, and confirm the browser download
   resumes and the popup reports IDM unavailable.
4. Turn interception off and confirm downloads stay in the browser.
5. Test **Download with IDM** on a link, and the ask/type location modes.
6. Repeat on Chrome, Edge and Firefox, including both 64-bit and 32-bit
   registry views when available.

## Uninstallation

The installer's uninstaller removes the native host, manifests and only IDM's
own registry values for browsers that were registered. Settings, history and
downloads under `%APPDATA%\IDM Download Manager` follow the normal uninstall
choice and are kept by default. Extension removal is controlled by the browser
(Chrome/Edge extension page, Firefox Add-ons); IDM never removes browser
extensions automatically.
