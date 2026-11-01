# IDM Video Assistant 3.5.0

A Chrome / Microsoft Edge Manifest V3 extension that finds direct media links on
the page you are viewing, shows their metadata, and sends an authorised link to
the IDM desktop application through the `com.idm.native` native messaging host.

The extension is deliberately narrow. It does **not** extract protected streams,
decipher signatures, use browser cookies, bypass DRM or platform download rules,
or run shell commands.

## What it does

- Scans the current page for links whose path ends in a configured media
  extension (`mp4`, `webm`, `mp3`, `flac` and so on).
- Reads HTML5 `<video>` and `<audio>` sources, including their `currentSrc`,
  `src`, `<source>` children, intrinsic `videoHeight`, duration and declared
  MIME type.
- Shows the page domain, title, file name, format, size hint, quality label,
  duration and detection source in the toolbar popup.
- Sends a selected link to IDM with one click. IDM validates the request again
  and decides where to save it.
- Optionally intercepts ordinary browser downloads: the browser copy is paused,
  IDM is asked to accept it, and the browser copy is cancelled only after IDM
  confirms acceptance. If IDM is unavailable or rejects the link, the browser
  download resumes.
- Adds **Download with IDM**, **Download with IDM to…** and **Send this media to
  IDM** context menu actions.
- Recognises YouTube and YouTube Music pages and displays Google's official
  download options instead of extracting streams.
- Stores the supported file-type list and user toggles in browser local storage.

## What it never does

- No DRM removal, stream extraction, signature deciphering, manifest rewriting
  or protected-segment downloading.
- No intercepting or downloading of platform stream hosts such as
  `googlevideo.com`, `video.twimg.com` or `tiktokcdn.com`.
- No page probing, hidden network requests, cookie access, history access or
  script injection into the page.
- No automatic execution of downloaded media.
- No arbitrary shell commands or filesystem access.
- No silent installation into a browser and no fake CRX package.

## Files

| File | Purpose |
| --- | --- |
| `manifest.json` | MV3 manifest, pinned extension key, minimum permissions |
| `background.js` | Service worker: download interception, context menus, tab media cache, native messaging |
| `content.js` | Page-side scanning, change observer and in-page toast |
| `media-detector.js` | Shared direct-link parser and restricted-platform policy |
| `native-messaging.js` | Native host client, request builder and filename/URL validation |
| `popup.html` | Toolbar popup markup |
| `popup.css` | Popup theme (dark and light) |
| `popup.js` | Popup state, settings, media list, official options and actions |
| `icons/` | 16, 32, 48 and 128 pixel extension icons |
| `README.md` | This document |
| `InstallationGuide.md` | Step-by-step Chrome, Edge and native-host setup |

## Requirements

- Google Chrome 102+ or Microsoft Edge 102+.
- IDM 3.5.0 running locally.
- The `com.idm.native` native messaging host registered for the browser you use.
  The IDM installer can do this, or you can run the registration script from a
  source checkout.

The manifest pins the development public key, so the unpacked extension keeps the
ID `ljckgbgnolmopacdgmmgaijleadcmpgn` across reloads. The native host allowlist
uses the same ID. A store build with a different ID must update the native host
allowlist (`IDM_CHROME_EXTENSION_ID` / `IDM_EDGE_EXTENSION_ID`).

Use either the basic **IDM Integration Module** or this **IDM Video Assistant** in
a browser profile, not both: they share a pinned extension ID. The Video
Assistant includes the basic interception and context-menu features.

## Install in two minutes

1. Register the native host (installer task or `register_native_host.py`).
2. Extract the ZIP package, or use the unpacked folder directly.
3. Chrome: open `chrome://extensions` → enable **Developer mode** → **Load
   unpacked** → select the `IDMVideoAssistant` folder.
4. Edge: open `edge://extensions` → enable **Developer mode** → **Load
   unpacked** → select the same folder.
5. Open the toolbar popup and press **Test connection**.

See [InstallationGuide.md](InstallationGuide.md) for the full procedure,
including verification and troubleshooting.

## Detection rules

A link is reported only when all of the following are true:

1. It resolves to an absolute `http:` or `https:` URL.
2. Its path (or a known query parameter such as `filename`) ends in an extension
   from the configured list.
3. It is not on a restricted stream host.

HTML5 media is reported only when the element exposes a usable source URL and
the extension/format is in the configured list. Quality and duration appear only
when the browser exposes real values; they are never guessed.

The detector reads the live DOM after `document_idle` and observes later DOM
changes, media metadata events, `pageshow` and `hashchange`. It does not fetch a
URL to discover what it is.

## YouTube and restricted platforms

YouTube, YouTube Music, Vimeo, Dailymotion, Twitch, Netflix, Hulu, Prime Video,
Disney+, Max, Peacock, Paramount+, TikTok, Instagram, Facebook, X, SoundCloud and
Spotify pages are treated as restricted for **page scanning**. Their protected
stream URLs cannot be handed to IDM.

For YouTube and YouTube Music, the popup displays official options instead:

- **YouTube Premium** or **YouTube Music Premium** — offline downloads in the
  official app.
- **YouTube Studio** — creators can download their own uploads.
- **YouTube Help** — Google's instructions for downloading videos you uploaded.

These buttons open Google's own pages. The extension does not read
`googlevideo.com`, `videoplayback` URLs or any embedded player stream, and it does
not claim that a video is downloadable merely because it is visible on YouTube.

A direct file link that a creator posted (for example a plain `.mp3` on a
non-restricted host) can still be sent with the right-click **Download with IDM**
action. It is handled as an ordinary file, not as a YouTube stream.

## Browser download interception

1. The browser starts a normal download.
2. The extension ignores non-HTTP(S) URLs, downloads made by extensions, and
   URLs recently handed to IDM.
3. Restricted stream hosts and downloads whose referrer is a restricted platform
   are left to the browser.
4. The browser download is paused and a validated `request_download` message is
   sent to the native host.
5. IDM accepts the request (or asks for a folder). Only then is the browser copy
   cancelled.
6. On any error, a cancellation or a timeout, the browser copy is resumed.

The toolbar badge shows a check after a successful add and an exclamation mark
after a rejection.

## Permissions and privacy

| Permission | Why it is needed |
| --- | --- |
| `nativeMessaging` | Talk only to the registered `com.idm.native` host |
| `downloads` | Detect and pause ordinary browser downloads |
| `contextMenus` | Add the right-click actions |
| `storage` | Keep toggles and file types on this device |
| `activeTab` | Read the active tab when the popup opens |

Content scripts run on `http://*/*` and `https://*/*` so the popup can list
media on the current page. There are no `tabs`, `history`, `cookies`,
`webRequest`, `debugger` or host permissions in the manifest. Detection results
are kept in memory per tab and expire after one minute; they are not uploaded
anywhere.

The popup renders all page- and server-supplied text with `textContent`; no HTML
from a page or native response is injected.

## Native messaging security

- Host name: `com.idm.native`; protocol version 2.
- The native host checks the browser name and extension ID allowlist; registry
  registration alone is not accepted as authorisation.
- URL scheme, length, filename characters, MIME hint, size and duration are
  validated by the extension, again by the native host, and again by IDM.
- The native host forwards requests over an authenticated loopback bridge with a
  random per-run token. Browser cookies and client certificates are never
  forwarded.
- A request is idempotent by `request_id`, so a service-worker retry cannot add
  the same download twice.
- Filenames may not contain path separators, Windows-reserved characters,
  control characters or a trailing dot/space.

## Error handling

The popup reports native-host failures, an unregistered host, an unauthorised
extension, IDM not running, a rejected URL, a restricted stream and a cancelled
folder picker. When interception fails, the browser download is resumed rather
than discarded. Errors are stored locally and shown in the popup; they are not
sent to a remote service.

## Limitations

- Blob URLs, MediaSource streams, HLS/DASH segments, form POSTs and in-memory
  responses are not exposed by `chrome.downloads` and stay in the browser.
- IDM performs its own HTTP request, so a download that requires the browser's
  session cookies may fail. The browser copy is resumed in that case.
- Incognito use requires the browser's explicit extension permission.
- Chrome and Edge may suspend the MV3 service worker; pending native messages are
  awaited and retried with the same request ID.
- Firefox is not supported by this MV3 folder; IDM ships a separate MV2 Firefox
  integration.
- The extension does not install itself. Browser policy requires the user to
  load or install it explicitly.

## Development and validation

From the repository root:

```powershell
node --check BrowserExtension\IDMVideoAssistant\background.js
node --check BrowserExtension\IDMVideoAssistant\content.js
node --check BrowserExtension\IDMVideoAssistant\media-detector.js
node --check BrowserExtension\IDMVideoAssistant\native-messaging.js
node --check BrowserExtension\IDMVideoAssistant\popup.js
node tests\video_assistant_harness.js
.\.venv\Scripts\python.exe -m pytest tests\test_video_assistant_extension.py -q
```

The harness checks the detector's metadata rules, restricted-platform policy,
YouTube official options and protocol v2 request builder. The pytest suite checks
the manifest, permissions, assets, message routes, packaging rules and the
harness result.

The real pause → native request → cancel/resume sequence requires a browser and
a running IDM instance; it is covered by the manual checklist in
[InstallationGuide.md](InstallationGuide.md).

## Packaging

The extension is distributed as an unpacked folder and as a plain ZIP. There is
no CRX in this project. Do not load the ZIP directly in Chrome or Edge: extract
it first, then use **Load unpacked**.

```powershell
.\.venv\Scripts\python.exe scripts\package_video_assistant.py
```

The deterministic archive is written to
`dist-extensions\IDM_Video_Assistant_3.5.0.zip` with `manifest.json` at its root,
and the SHA-256 digest is printed. The ZIP contains the unpacked extension,
including this README and the installation guide.
