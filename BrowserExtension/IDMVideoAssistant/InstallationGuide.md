# IDM Video Assistant — Installation Guide

This guide covers Windows installation for Google Chrome and Microsoft Edge.
The extension is a plain Manifest V3 folder; it is never installed silently and
no CRX file is used.

## Before you start

- Install **IDM 3.5.0** and start it once.
- Use **Chrome 102+** or **Edge 102+**.
- Decide which IDM browser extension you want in the profile. The basic
  **IDM Integration Module** and **IDM Video Assistant** share the pinned ID
  `ljckgbgnolmopacdgmmgaijleadcmpgn`, so load one of them per browser profile.
  The Video Assistant includes download interception, context menus and the
  media list.
- Keep the unpacked folder in a permanent location. Chrome and Edge remember the
  path; moving or deleting the folder disables the extension.

## Step 1 — Register the native messaging host

The popup talks to IDM through the `com.idm.native` host. The host is a small
stdio program that validates every message and forwards it to the running IDM
application.

### Option A — IDM installer (recommended)

1. Run `IDM-Setup-3.5.0.exe`.
2. On the optional tasks page, select:
   - **Integrate with Google Chrome**, and/or
   - **Integrate with Microsoft Edge**.
3. Finish the installation.

The installer writes the browser manifest under
`{app}\browser-integration\` and registers it under the current user only:

```
HKCU\Software\Google\Chrome\NativeMessagingHosts\com.idm.native
HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.idm.native
```

It does **not** install the extension. That remains an explicit browser action.

### Option B — source checkout

Build or locate `IDM_NativeHost.exe`, then run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\register_native_host.py install --installed
```

If the host is in the release folder, point at it explicitly:

```powershell
.\.venv\Scripts\python.exe scripts\register_native_host.py install --installed `
  --host-path "D:\IDM\IDM_V3_Release\IDM_NativeHost.exe"
```

Check the registration:

```powershell
.\.venv\Scripts\python.exe scripts\register_native_host.py status
```

The status output must show the expected manifest path, host executable and
registry views. Do not use `--dev` for normal use; it writes a `.cmd` launcher
intended only for development.

## Step 2 — Load the unpacked extension

### Google Chrome

1. Open `chrome://extensions` in the address bar.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked**.
4. Select the folder that contains `manifest.json`, for example:
   - Source folder: `D:\IDM\BrowserExtension\IDMVideoAssistant`
   - Release folder: `D:\IDM\IDM_V3_Release\BrowserExtension\IDMVideoAssistant`
5. The card should read **IDM Video Assistant 3.5.0** and show the ID
   `ljckgbgnolmopacdgmmgaijleadcmpgn`.
6. Click the puzzle-piece icon and pin **IDM Video Assistant** to the toolbar.

If you downloaded the ZIP package, extract it first (right-click → **Extract
All**), then select the extracted folder. Chrome cannot load a ZIP directly.

### Microsoft Edge

1. Open `edge://extensions` in the address bar.
2. Turn on **Developer mode** (left sidebar).
3. Click **Load unpacked**.
4. Select the same folder as above.
5. Confirm the name, version `3.5.0` and ID `ljckgbgnolmopacdgmmgaijleadcmpgn`.
6. Pin the extension from the Extensions menu.

The **Allow extensions from other stores** switch is only needed for Chrome Web
Store installs. It is not required for **Load unpacked**.

### If the basic IDM extension is already loaded

Chrome or Edge will not keep two extensions with the same ID. Remove or disable
**IDM Integration Module** first, then load **IDM Video Assistant**. Both use the
same native host allowlist, so no host re-registration is needed.

## Step 3 — Verify the connection

1. Make sure **IDM is running**.
2. Open the IDM Video Assistant popup.
3. The status should read **Connected** within a few seconds.
4. Click **Test connection**. A success notice shows the IDM version reported by
   the desktop application.
5. If it fails, see **Troubleshooting** below.

The popup also shows the native host version and the active transfer count.

## Step 4 — Test detection and sending

1. Open a normal `http` or `https` page that contains a direct media link, such
   as a page with `<a href="...clip.mp4">` or an HTML5 `<video>` element.
2. Open the popup. The media card lists the detected link, format, size hint,
   quality and duration where the page exposes them.
3. Press **Send to IDM**. A toast confirms the file name; the transfer appears in
   IDM's queue, using IDM's configured save location.
4. Press **Rescan** after the page changes.
5. Right-click a direct link and try **Download with IDM** and **Download with
   IDM to…**.
6. Start an ordinary browser download with interception enabled. Confirm it is
   paused, accepted by IDM, and removed from the browser list. Stop IDM and
   repeat: the browser download must resume.

### YouTube verification

1. Open `https://www.youtube.com/watch?v=...` or `https://music.youtube.com/...`.
2. Open the popup.
3. The card explains that YouTube streams are not extracted and lists the
   official options: YouTube Premium / YouTube Music Premium, YouTube Studio and
   YouTube Help.
4. Each option opens Google's own page in a new tab.
5. No **Send to IDM** button is shown for player streams. This is intentional.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| Page detection | On | Scans the current page only |
| Supported file types | `mp4, webm, m4v, mov, mkv, mp3, m4a, ogg, wav, flac` | Extensions considered media links |
| Send browser downloads to IDM | On | Pauses and hands over ordinary downloads |
| Ask where to save | Off | Opens IDM's folder picker for each intercepted download |
| Show a notification after adding | On | In-page toast and toolbar badge |

File types are normalised to lowercase and may be entered separated by commas,
spaces or semicolons. Press **Save** or Enter. Invalid tokens are ignored; if no
valid token remains, the saved list is unchanged.

## Updating the extension

1. Replace the files in the unpacked folder (or extract the newer ZIP over it).
2. Open `chrome://extensions` or `edge://extensions`.
3. Press **Reload** on the IDM Video Assistant card.
4. Open the popup and run **Test connection** again.

The pinned key keeps the ID stable, so the native host registration remains
valid. If a store build is used instead, the store may assign a different ID; the
native host allowlist must then be updated with `IDM_CHROME_EXTENSION_ID` or
`IDM_EDGE_EXTENSION_ID` before rebuilding the host.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| **Not connected** and "native host is not registered" | Run the installer integration task, or `register_native_host.py install --installed`, then reload the extension. |
| "This extension is not authorised in IDM" | The browser ID does not match the host allowlist. Confirm the popup's **Copy extension ID** value is `ljckgbgnolmopacdgmmgaijleadcmpgn`, or update the host allowlist and rebuild. |
| "IDM is not running" | Start IDM and press **Test connection**. |
| Popup opens but shows no media | Only direct `http(s)` file URLs and observable `<video>`/`<audio>` sources are listed. Blob, MediaSource, HLS/DASH and protected streams are not exposed. |
| YouTube shows no media buttons | By design. Only Google's official download options are shown. |
| Downloads stay in the browser | Interception is off, the URL is not HTTP(S), the download was started by an extension, or IDM rejected it and the browser copy resumed. |
| Browser download disappears but IDM has nothing | Check the popup's last error. If IDM is not running, the extension should resume the browser copy; retry after starting IDM. |
| Extension disappears after a restart | The unpacked folder was moved or deleted, or the profile changed. Load it again from its permanent path. |
| Edge says the extension is from an unknown source | This is expected for **Load unpacked**. The extension is not signed by the Edge Add-ons store. |
| ZIP cannot be loaded | Extract the ZIP. Chrome and Edge load folders, not archives. |

Logs:

- Native host: `%APPDATA%\IDM Download Manager\logs\native_host.log`
- Registration status: `scripts\register_native_host.py status`
- In the browser: `chrome://extensions` → IDM Video Assistant → **Errors**, or
  `edge://extensions` → **Inspect views: service worker**.

## Uninstalling

1. Open `chrome://extensions` or `edge://extensions`.
2. Remove **IDM Video Assistant**.
3. Optional: unregister the native host if you no longer use browser
   integration:

```powershell
.\.venv\Scripts\python.exe scripts\register_native_host.py uninstall --installed
```

The native host is shared with the basic IDM integration. Unregistering it
disables both extensions. IDM's download history, settings and files under
`%APPDATA%\IDM Download Manager` are not affected by removing the extension.
