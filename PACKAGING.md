# IDM Packaging and Deployment Guide

This document describes how to build, install, upgrade, uninstall and sign the
Windows distribution of IDM (`IDM-Setup-3.6.1.exe`).

## Status

| Item | Status |
| --- | --- |
| PyInstaller onedir build (`dist\IDM\IDM.exe`) | Built and verified |
| Native messaging host (`dist\IDM\IDM_NativeHost.exe`) | Built by the spec as a Qt-free one-file executable |
| Browser extensions (`dist-extensions\*.zip`) | Basic Chrome/Edge/Firefox packages by `scripts\package_extensions.py`; IDM Video Assistant by `scripts\package_video_assistant.py` |
| Standalone updater (`dist\IDM\IDM_Updater.exe`) | Built and verified (frozen `--version` exits 0; version resource 3.6.1.0) |
| Inno Setup installer (`dist-installer\IDM-Setup-3.6.1.exe`) | Built and verified on Windows 11 x64 (browser registration tasks require Inno Setup to compile) |
| Automated test suite | 582 tests passed |
| Automatic update system | Update checks and Ed25519-signed manifests are operational; automatic installation requires a CA-issued code-signing certificate |
| Browser integration | Implemented and unit-tested; real browser interception requires manual verification |
| Silent install / launch / uninstall / upgrade / data preservation | Passed on Windows 11 x64 |
| Windows 10 x64 | **Not tested** — no Windows 10 machine was available |
| Code signing | **Not signed** |
| Production-ready for public distribution | **No** — Windows 10 validation and code signing are still required |

The installer and application are unsigned. Windows SmartScreen will warn when
they are run on a machine that has not seen them before. See
[Code signing](#code-signing).

## Deliverables

| Path | Purpose |
| --- | --- |
| `idm\version.py` | Single source of truth for `CURRENT_VERSION` and app identity |
| `IDM.spec` | PyInstaller configuration for the app (onedir) and updater (onefile) |
| `version_info.txt` | Windows version resource for `IDM.exe` |
| `version_info_updater.txt` | Windows version resource for `IDM_Updater.exe` |
| `updater_main.py` | Entry point for the standalone updater build |
| `native_host_main.py` | Entry point for the standalone native messaging host build |
| `version_info_native_host.txt` | Windows version resource for `IDM_NativeHost.exe` |
| `integrations\` | Native host, protocol, bridge, registration, browser detection and desktop service |
| `extensions\chrome`, `extensions\edge`, `extensions\firefox` | Browser extension sources |
| `BrowserExtension\IDMVideoAssistant\` | Manifest V3 media-detection extension source, docs and icons |
| `downloads\location_manager.py` | Browser/default/ask/file-type destination policy |
| `scripts\register_native_host.py` | Manual/development native host registration and status |
| `installer\assets\Install-PythonDeps.ps1` | Python runtime bootstrap, shipped as `{app}\tools\` |
| `scripts\package_extensions.py` | Extension validation and store ZIP packaging |
| `scripts\package_video_assistant.py` | IDM Video Assistant validation and unpacked ZIP packaging (no CRX) |
| `scripts\package_release.py` | Release bundle assembly, version validation and checksums |
| `idm\updater\` | Qt-free update core: manifest validator, checker, downloader, verifier, updater |
| `config.py` | Central GitHub owner/repo, endpoint, channel, publisher and manifest key |
| `scripts\` | Release build/sign/hash/validate scripts and publishing checklist |
| `IDM-Update-Server\` | Manifest schema, CI workflow and docs for an optional separate manifest repository |
| `update\latest.json` | Signed live update manifest for the configured GitHub repository |
| `docs\UPDATES.md` | Update-system configuration, signing and publishing guide |
| `docs\BROWSER_INTEGRATION.md` | Browser installation, protocol, limitations and test checklist |
| `docs\BROWSER_STORE_PUBLISHING.md` | Chrome Web Store, Edge Add-ons and Mozilla Add-ons submission |
| `requirements.txt` | Runtime dependencies |
| `requirements-build.txt` | Build and test dependencies |
| `build_windows.ps1` | One-command build automation |
| `installer\IDM_Setup.iss` | Inno Setup script |
| `installer\assets\wizard-large.bmp`, `wizard-small.bmp` | Custom wizard graphics |
| `assets\logo\idm.ico`, `idm.png` | Application and installer icon |
| `tools\generate_branding_assets.py` | Regenerates the icon and wizard bitmaps from the app logo |
| `tests\` | Automated test suite, including the app-data layout and update tests |
| `dist\IDM\IDM.exe` | Packaged application |
| `dist\IDM\IDM_NativeHost.exe` | Native messaging host staged next to the app |
| `dist\IDM\browser-extensions\*.zip` | Store-ready extension packages (also shipped separately) |
| `dist-extensions\IDM_*_Extension.zip` | Chrome, Edge and Firefox packages with printed SHA-256 |
| `dist-extensions\IDM_Video_Assistant_<version>.zip` | Unpacked IDM Video Assistant package with printed SHA-256 |
| `dist\IDM\IDM_Updater.exe` | Standalone updater staged next to the app |
| `dist-installer\IDM-Setup-3.6.1.exe` | Final installer |
| `ReleaseNotes.md` | User-facing release notes copied into the release package |
| `release\IDM-<version>-win64\` | Generated release directory with docs, checksums and metadata |
| `release\IDM-<version>-win64.zip` | Generated distributable archive (plus `.sha256` sidecar) |

The updater executable is built from the same spec in a separate PyInstaller
one-file pass. It does not import PySide6, so it can run while IDM and its Qt
libraries are being replaced.

## Release package

The release bundle is assembled from the build output, never from source:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1 -Package
```

`-Package` runs after Inno Setup succeeds. With `-SkipInstaller` it produces a
portable-only bundle. The packager can also be invoked directly:

```powershell
.\.venv\Scripts\python.exe scripts\package_release.py
.\.venv\Scripts\python.exe scripts\package_release.py --no-portable --no-zip
```

The output layout is:

```
release\IDM-<version>-win64\
  IDM_Setup_<version>.exe
  portable\IDM\...
  browser-extensions\IDM_Chrome_Extension.zip
  browser-extensions\IDM_Edge_Extension.zip
  browser-extensions\IDM_Firefox_Extension.zip
  docs\README.md, PACKAGING.md, BROWSER_INTEGRATION.md,
       BROWSER_STORE_PUBLISHING.md, UPDATES.md
  README.txt
  ReleaseNotes.md
  VERSION.json
  SHA256SUMS.txt
release\IDM-<version>-win64.zip
release\IDM-<version>-win64.zip.sha256
```

`VERSION.json` records the application version, packaging time, component
versions and the SHA-256 of each binary. `SHA256SUMS.txt` uses the standard
`sha256sum` format and covers every other file in the directory. The ZIP uses
fixed entry timestamps and sorted entries.

Before copying anything, the packager fails when:

- `IDM_Setup.iss`, `version_info*.txt`, an extension manifest or an extension
  ZIP disagrees with `idm\version.py`
- the installer or portable build requested by the command is missing
- a documentation file or `ReleaseNotes.md` is missing

It prints a warning, but still packages, when the installer or portable build
is older than the newest runtime source change. Rebuild before publishing when
that happens. Use `--no-installer`, `--no-portable` or `--no-zip` to omit
components, and `--force` only if an unrecognised directory occupies the
package path.

The release package is not code-signed by this step. Sign the installer and
executables before building the package, then package the signed artifacts.

## Build requirements

- Windows 10 or Windows 11, 64-bit
- Python 3.11+ 64-bit (3.12.x recommended; this build uses 3.12.14)
- Inno Setup 6.3+ or 7.x (`ISCC.exe`)
- PowerShell 5.1+ (the script uses Windows PowerShell)
- Internet access on the first run to install dependencies

The repository already contains a `.venv` created with Python 3.12. The build
script reuses it unless `-RecreateVenv` is passed. If Python is not on `PATH`,
pass the full interpreter path with `-Python`.

## Build

```powershell
cd D:\IDM
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1 -Force
```

What the script does:

1. Finds a 64-bit Python 3.11+ interpreter and creates or reuses `.venv`.
2. Installs `requirements.txt` and `requirements-build.txt`.
3. Reads `CURRENT_VERSION` from `idm\version.py` and verifies that both
   version resources, `installer\IDM_Setup.iss`, all three extension manifests
   and `VersionInfoVersion` match its numeric tuple. A drifted build stops
   here.
4. Optionally regenerates branding assets (`-RegenerateAssets`).
5. Compiles all Python files and imports `main`, `updater_main` and the native
   host to catch syntax and import errors before packaging.
6. Runs `pytest` with Qt's offscreen platform.
7. Deletes only `build\IDM`, `build\IDM_Updater`, `build\IDM_NativeHost`,
   `dist\IDM`, stale executables and `dist-extensions` (never source, user data
   or downloads).
8. Validates and packages the three browser extensions into
   `dist-extensions\IDM_*_Extension.zip`.
9. Runs PyInstaller with `IDM.spec`, producing `dist\IDM\IDM.exe` (onedir),
   `dist\IDM\IDM_NativeHost.exe` (one-file, no Qt) and `dist\IDM_Updater.exe`
   (onefile).
10. Verifies the app bundle, bundled assets, the Qt `qwindows.dll` plugin and
    the native host, and copies the updater next to the app for the installer.
11. Locates `ISCC.exe` (Inno Setup 6 or 7, Program Files or per-user install),
    or uses `-InnoSetupPath`.
12. Runs Inno Setup with quiet progress output.
13. Verifies `dist-installer\IDM-Setup-3.6.1.exe` and prints sizes and SHA256 hashes
    for the app, the updater, the native host and the installer.

The script refuses to overwrite an existing installer unless `-Force` is
passed. Without `-Force` it asks before replacing a previously generated
installer.

### Parameters

| Parameter | Effect |
| --- | --- |
| `-Python <path>` | Base interpreter used to create `.venv` |
| `-InnoSetupPath <path>` | `ISCC.exe` or the Inno Setup directory |
| `-Force` | Replace an existing `IDM-Setup-3.6.1.exe` without prompting |
| `-RecreateVenv` | Delete and recreate `.venv` |
| `-RegenerateAssets` | Rebuild `idm.ico` and the wizard bitmaps first |
| `-SkipTests` | Skip pytest (not recommended for release) |
| `-SkipInstaller` | Build `IDM.exe` and `IDM_Updater.exe` only, skip Inno Setup |

Examples:

```powershell
# Rebuild everything without prompting
.\build_windows.ps1 -Force

# Rebuild icon and wizard graphics, then the whole distribution
.\build_windows.ps1 -RegenerateAssets -Force

# Application only, faster iteration
.\build_windows.ps1 -SkipInstaller
```

The branding generator needs Pillow and PySide6 (both in the venv):

```powershell
.\.venv\Scripts\python.exe tools\generate_branding_assets.py
```

### Release version bump

Update all of the following, then rebuild and repeat the upgrade test:

1. `CURRENT_VERSION` in `idm\version.py` (this drives `APP_VERSION` and the
   About dialog; do not declare the version anywhere else in Python)
2. `filevers` / `prodvers` and the version strings in `version_info.txt`
3. `filevers` / `prodvers` and the version strings in `version_info_updater.txt`
4. `MyAppVersion`, `MyAppVerName` and `VersionInfoVersion` in
   `installer\IDM_Setup.iss`

The build script enforces items 1–4 and refuses a prerelease suffix in release
builds. The update manifest's `latest_version` must match the version of the
signed installer you publish; see [docs/UPDATES.md](docs/UPDATES.md).

## Installation

### Interactive

Run `IDM-Setup-3.6.1.exe` and follow the wizard. It offers:

- Install for all users (requires elevation) or only the current user.
- Installation folder, defaulting to `C:\Program Files\IDM` for all users or
  `%LOCALAPPDATA%\Programs\IDM` for the current user.
- Start Menu shortcut (always created).
- Optional desktop shortcut (unchecked by default).
- Optional launch at Windows sign-in (unchecked by default).
- A Python runtime task, shown only when no Python 3.11+ with PySide6 and
  Requests is found on the machine (checked by default). See
  [Python runtime bootstrap](#python-runtime-bootstrap).
- Launch IDM after installation.

The installer requests the lowest privileges needed. It only elevates when the
user chooses an all-users installation.

### Silent

Current user, custom folder, desktop and startup shortcuts:

```bat
IDM-Setup-3.6.1.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER ^
  /DIR="D:\Apps\IDM" /TASKS="desktopicon,startup" ^
  /LOG="%TEMP%\IDM_install.log"
```

All users (run from an elevated prompt):

```bat
IDM-Setup-3.6.1.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS ^
  /DIR="C:\Program Files\IDM"
```

In silent mode, optional tasks default to off. Pass
`/TASKS="desktopicon,startup"` to enable them. The Python runtime task is not
offered in silent mode; use `/PYDEPS` instead.

When invoking the setup or uninstaller from Git Bash, double the leading slash
(`//VERYSILENT //SUPPRESSMSGBOXES`) or run it through PowerShell. MSYS otherwise
rewrites `/VERYSILENT` into a Windows path, so the uninstaller starts in
interactive mode and may ask whether to delete user data.

Useful Inno Setup switches:

| Switch | Meaning |
| --- | --- |
| `/CURRENTUSER` | Install for the current user without elevation |
| `/ALLUSERS` | Install for all users (requires elevation) |
| `/DIR=<path>` | Installation folder |
| `/TASKS=...` | Comma-separated tasks; empty string for none |
| `/CLOSEAPPLICATIONS` | Close a running IDM via Restart Manager |
| `/LOG=<file>` | Write an installation log |
| `/NORESTART` | Never restart Windows |
| `/PYDEPS` | Also bootstrap the Python runtime, even in silent mode |
| `/NOPYDEPS` | Never offer or run the Python runtime bootstrap |

### Python runtime bootstrap

The project brief lists Python 3.11+ (3.12+ recommended), PySide6 and Requests
as prerequisites for running IDM from source. The packaged `IDM.exe` bundles
its own runtime, so this bootstrap exists only for source use, the test suite
and the helper scripts.

When the wizard finds no interpreter that can already import everything listed
in `requirements.txt` (PySide6, Requests and cryptography), it offers the
`pydeps` task. With that task selected (or `/PYDEPS` passed) IDM runs
`tools\Install-PythonDeps.ps1` after copying its own files:

1. Search the registry (`PythonCore`, both 32-bit views), the standard
   installation folders and the `py` launcher for a Python 3.11+ interpreter.
2. If none exists, download the pinned python.org amd64 installer, verify its
   Windows Authenticode signature (must be issued to the Python Software
   Foundation) and the SHA-256 compiled into the setup, then install it
   silently for the current user only.
3. Run `python -m pip install -r requirements.txt` and re-check that the
   interpreter can import everything the file lists.

Nothing in this flow needs elevation, and a failure never rolls back the IDM
installation: the console reports the reason, `%TEMP%\IDM-PythonDeps-<version>.log`
keeps the detail, and the task can be retried later:

```bat
powershell -NoProfile -ExecutionPolicy Bypass ^
  -File "%LOCALAPPDATA%\Programs\IDM\tools\Install-PythonDeps.ps1" ^
  -RequirementsFile "%LOCALAPPDATA%\Programs\IDM\tools\requirements.txt"
```

The script exits with `0` when it installed something, `10` when the runtime
was already complete, and `20`..`25` for download, signature, Python install,
pip, verification and usage failures. `-CheckOnly` reports without changing
anything. Update `PythonInstallerUrl` and `PythonInstallerSha256` in
`installer\IDM_Setup.iss` together when the pinned interpreter changes; the
build machine was validated with the 3.13.12 installer.

## Data layout

User data is never written to the installation directory. It lives under the
roaming AppData folder:

```
%APPDATA%\IDM Download Manager\
    database\idm.sqlite3      Settings, history, queue, segment state
    database\backups\         Pre-update database snapshots (last five kept)
    logs\idm.log              Rotating diagnostic log
    logs\updater.log          Standalone updater log (no credentials)
    logs\native_host.log      Browser native host log (rotated, no credentials)
    runtime\browser_bridge.json  Loopback port/token, removed when IDM exits
    native_messaging\         Generated browser manifests and optional dev launcher
    settings\settings.ini     Legacy import only (read once, not created)
    settings\schedules.json   Scheduler entries
    downloads\                Default download folder
```

Temporary update packages live outside the data folder in
`%TEMP%\IDM-Update-<random>\`. They contain the verified installer, the staged
updater, the handoff file and a completion marker. The updater removes the
folder after a successful install; if it cannot delete its own running file,
the restarted application removes the marked folder on the next launch. Stale
unmarked folders older than 24 hours are also cleaned.

The folder is deliberately **not** `%APPDATA%\IDM`. The commercial Internet
Download Manager uses that directory for its own downloads and `idm.log`;
sharing it would mix two products' data and make optional data cleanup unsafe.
The test suite asserts that the commercial folder is never touched.

Users can choose any download folder per download or globally in Options.
Files saved outside `%APPDATA%\IDM Download Manager` are never removed by the
uninstaller.

## Upgrade behavior

- The AppId is stable (`{A52627A1-E4C9-456C-A397-BB6D9FD48F1B}`), so a newer
  installer upgrades the existing installation instead of creating a second
  entry.
- The previous installation folder, tasks, setup type, language and privilege
  scope are reused (`UsePrevious*`), so an automatic update never moves a
  per-user install into Program Files or the reverse.
- A running IDM is closed through Restart Manager (`CloseApplications=yes`).
  The updater waits for IDM's process to exit before launching setup. The
  application is not restarted automatically after a manual upgrade; the
  automatic update path restarts it only if the user chose to.
- User data is never touched. The database, settings, history, schedules and
  downloads are preserved. The app writes an online SQLite backup to
  `database\backups\` before handing control to the updater.
- Shortcuts are recreated in place; no duplicates are created.
- Add/Remove Programs shows a single entry with the new version.

Upgrade test performed: installed 1.0.0, seeded settings and data, ran a
temporary 1.0.1 build over it while IDM was running, and confirmed the running
process was closed, shortcuts and data were preserved, `DisplayVersion`
changed to 1.0.1, and one uninstall entry remained.

## Automatic updates

The checker, downloader, verifier and standalone updater are implemented in
this repository. 3.6.1 ships with the public GitHub endpoint and an Ed25519
manifest public key, so **Check for Updates** works and every manifest is
signature-verified. `EXPECTED_PUBLISHER` is empty because no CA-issued
code-signing certificate exists, so installation trusts the signed manifest and
SHA-256 instead of Authenticode. The **Install Update** button downloads and
installs the matching package after explicit consent; **Download Installer**
remains available as a manual alternative. Full setup, manifest schema, hosting
and publishing steps are in [docs/UPDATES.md](docs/UPDATES.md);
`IDM-Update-Server/` remains the schema and CI scaffold for a separate manifest
repository.

What is shipped:

- **Check for Updates** in Help and in About, running on a background thread
  with a timeout and HTTPS-only manifest retrieval.
- Strict manifest validation (`app_name`, `channel`, `latest_version`,
  `minimum_supported_version`, `release_date`, `release_notes`, `download_url`,
  `sha256`, `optional package_size`, `mandatory`, `manifest_signature`),
  unknown/duplicate field rejection, stable/beta channel policy, mandatory
  Ed25519 manifest signature and semantic-version comparison with a downgrade
  guard.
- Download to `%TEMP%\IDM-Update-*` with progress, cancel and retry; SHA-256
  verification; Windows Authenticode verification with an exact publisher
  match.
- Explicit confirmation before installing. Mandatory updates still require
  consent and never bypass UAC or Defender/SmartScreen.
- A separate `IDM_Updater.exe` that waits for IDM to exit, opens the verified
  Inno Setup installer (`/SILENT /SP- /NORESTART /CLOSEAPPLICATIONS`), logs the
  result, optionally restarts IDM and removes the temporary folder.
- Pre-update SQLite backup and settings save; user data is never replaced by
  the installer.

Configuration required before release:

1. Set `GITHUB_OWNER`, `EXPECTED_PUBLISHER` and optionally
   `MANIFEST_PUBLIC_KEY` in the IDM application's `config.py`.
2. Publish the `IDM-Update-Server` repository with a real `latest.json` and a
   signed installer release asset.
3. Sign `IDM.exe` and `IDM_Updater.exe` with the certificate whose subject
   matches the configured publisher, then sign `IDM-Setup-3.6.1.exe`.

Source checkouts and unpackaged runs cannot install updates automatically; the
About dialog explains that the packaged updater is required. No signed
end-to-end update has been executed in this repository because no code-signing
certificate or public update host is provisioned.

## Uninstall

Interactive uninstall is available from Settings → Apps → Installed apps or
the Start Menu. The uninstaller removes:

- The installation folder and `IDM.exe`
- Start Menu, desktop and startup shortcuts
- The uninstall registry entry
- The native messaging host and IDM's own per-user manifests, for browser
  tasks that were selected during installation (only IDM's registry value is
  removed; unrelated values and keys are preserved)

By default it **keeps** user data.

During an interactive uninstall, if the data folder exists, the uninstaller
asks whether to delete it. The default button is **No**. Choosing Yes deletes
only `%APPDATA%\IDM Download Manager` (database, settings, logs and downloads
stored inside it). Files saved elsewhere are untouched.

Silent uninstall:

```bat
"C:\Program Files\IDM\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Silent uninstall keeps user data. To delete it explicitly:

```bat
"C:\Program Files\IDM\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /REMOVEDATA
```

`/REMOVEDATA` is only honored by the uninstaller. The installer never deletes
user data. Because the data path is product-specific, the switch cannot touch
the commercial IDM's `%APPDATA%\IDM` folder.

## Windows integration

- Custom application icon in Explorer, shortcuts, the taskbar and Add/Remove
  Programs.
- Start Menu shortcut under `IDM\IDM.lnk`.
- Optional desktop shortcut (including OneDrive-redirected desktops).
- Optional per-user startup shortcut via `{userstartup}\IDM.lnk`; removed by
  the uninstaller.
- Add/Remove Programs entry with display name, version, publisher, icon and
  uninstall string.
- Optional per-browser browser integration tasks register
  `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.idm.native`,
  `HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.idm.native` and
  `HKCU\Software\Mozilla\NativeMessagingHosts\com.idm.native` in both registry
  views. Extension ZIPs are copied to `{app}\browser-extensions`; extensions
  are never installed or updated automatically.
- The optional Python runtime bootstrap writes outside `{app}`: a per-user
  Python under `%LOCALAPPDATA%\Programs\Python`, its own `HKCU\Software\Python`
  keys and site-packages. It passes `PrependPath=0`, so PATH is not touched.
- Version resources in `IDM.exe`, `IDM_NativeHost.exe` and `IDM_Updater.exe`:
  `FileVersion` / `ProductVersion` 1.0.0.0, description “IDM Internet Download
  Manager” / “IDM Browser Integration Host” / “IDM Updater”.
- No file associations, no environment changes, no services, no global
  registry entries beyond the uninstall entry and the selected per-user native
  messaging keys.

## Security notes

- The installer does not include secrets, API keys or personal data.
- It does not disable Windows Defender, add exclusions, or bypass SmartScreen.
- It does not request administrator rights unless the user selects an
  all-users installation.
- It does not download or execute anything during setup.
- It does not delete user data during install or upgrade.
- Downloading is restricted to HTTP/HTTPS links; downloaded files are never
  executed automatically by the application.
- The application stores data only in the paths listed above and does not
  write into Program Files.
- The update system accepts HTTPS only, rejects non-configured download hosts
  and redirect targets, caps manifest and package sizes, verifies SHA-256,
  verifies the Authenticode publisher exactly, refuses downgrades, and never
  executes scripts or commands from the manifest. It only launches the
  verified Inno Setup installer.
- Update logs record URLs, versions and verification results but never
  credentials, cookies or tokens.
- The browser integration accepts only HTTP/HTTPS requests from allowlisted
  extension IDs, validates URLs and file names twice, binds its bridge to
  127.0.0.1 with a per-run token, and never executes shell commands or reads
  arbitrary local files. It does not collect browser credentials, cookies or
  tokens.
- Distribution recommendation: publish the SHA256 hashes below with the
  installer, sign IDM, the updater, the native host and the installer before
  public release, and configure the update endpoint and publisher before
  advertising automatic updates.

Current build hashes (rebuild produces new values):

| Artifact | Size | SHA256 |
| --- | --- | --- |
| `dist\IDM\IDM.exe` | 5,133,666 bytes | `2052C058266BD375CAAC8D6CCAA3A332B192BE2401F63A577F899D09F40C4F65` |
| `dist\IDM\IDM_Updater.exe` | 15,616,401 bytes | `E14F02E4D08201389045A3561E1AF1CAD20CF35ADBBA9D1AABCFC07D0A2FC03C` |
| `dist\IDM\IDM_NativeHost.exe` | 8,304,718 bytes | `F95D76119F7325CE15154EE128635ABA80EB307FFC21D5BF63311ECD0C4EEE0D` |
| `dist-installer\IDM-Setup-3.6.1.exe` | 62,466,466 bytes | `51B8F1F7B2FAF304C6A12B30496AE8792DFDF48ADDE166B6FB79CB20D7FD501C` |

## Code signing

All artifacts are currently `NotSigned`. Before distributing IDM publicly:

1. Obtain an Authenticode code-signing certificate. An EV certificate gives
   immediate SmartScreen reputation; an OV certificate builds reputation over
   time. A standard “code signing” certificate is sufficient for trust, but not
   for instant SmartScreen bypass.
2. Sign `IDM.exe` after PyInstaller finishes and **before** compiling the
   installer, so the embedded application is signed.
3. Sign `IDM_Updater.exe` as well. The update system compares the installer's
   publisher against the configured expected publisher and refuses the update
   on a mismatch, so the updater and installer must be signed by the same
   certificate you configure.
4. Sign `IDM-Setup-3.6.1.exe` after Inno Setup finishes, then publish its real
   SHA-256 in the update manifest. The setup signature is what the update
   system checks before launching it.

Example commands (adjust the certificate path and timestamp service):

```bat
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
  /f "C:\secure\idm-codesign.pfx" /p "<password>" ^
  /d "IDM Internet Download Manager" dist\IDM\IDM.exe

signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
  /f "C:\secure\idm-codesign.pfx" /p "<password>" ^
  /d "IDM Browser Integration Host" dist\IDM\IDM_NativeHost.exe

signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
  /f "C:\secure\idm-codesign.pfx" /p "<password>" ^
  /d "IDM Updater" dist\IDM\IDM_Updater.exe

iscc installer\IDM_Setup.iss

signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
  /f "C:\secure\idm-codesign.pfx" /p "<password>" ^
  /d "IDM Setup" dist-installer\IDM-Setup-3.6.1.exe
```

The updater is copied from `dist\IDM_Updater.exe` into `dist\IDM\` by the
build script, so sign it before the installer is compiled. Because the script
compiles the installer immediately, a signed release currently requires
running the last steps manually after the build, or adding a signing step to
the pipeline.

Do not work around SmartScreen by instructing users to disable protections.
Unsigned builds are expected to show “Windows protected your PC”; that warning
disappears only through signing and reputation.

## Testing checklist and results

Environment: Windows 11 x64 (build 26300), Python 3.12.14, PySide6 6.12.0,
Inno Setup 7. All application data used in tests was isolated in a disposable
folder or a throwaway AppId. The real `%APPDATA%\IDM Download Manager` and the
commercial `%APPDATA%\IDM` folder were never modified.

| Test | Result |
| --- | --- |
| Automated suite (`pytest tests -q`) | 374 passed |
| Browser integration tests: protocol, allowlist, locations, bridge auth, service, native host, registry, extension packages | Passed |
| Manual interception on Chrome, Edge and Firefox with a running IDM | **Not tested in this environment** — requires interactive browsers and per-user registration |
| Native host frozen and started through a real browser | **Not tested in this environment**; build/staging is included in `IDM.spec` and `build_windows.ps1` |
| Updater unit tests: version comparison, manifest validation, checker, downloader, SHA-256/signature verification, handoff, stale cleanup | Passed (fake HTTP sessions and fake verifiers) |
| Update UI tests: no-update text, update available, latest-version link, error/retry, confirmation, refusal on missing updater | Passed (Qt offscreen) |
| Frozen `IDM.exe` launch with isolated `%APPDATA%` | Passed (window opened, closed with exit code 0, data written only to the isolated folder) |
| Frozen `IDM_Updater.exe --version` | Passed (exit code 0; version resource 1.0.0.0) |
| Installer embeds `IDM_Updater.exe` | Passed (listed in the Inno Setup compression log) |
| Live end-to-end update from a signed installer | **Not tested** — no signing certificate or public update host |
| Silent current-user install to a custom directory | Passed |
| Start Menu group shortcut `IDM\IDM.lnk` | Passed |
| Optional desktop shortcut (OneDrive desktop) | Passed |
| Optional startup shortcut | Passed |
| Uninstall registry entry, version and location | Passed |
| Installed exe version resource 1.0.0.0 | Passed |
| Launch installed app with `qwindows` platform plugin | Passed |
| Window title and graceful exit | Passed |
| SQLite created under isolated AppData layout | Passed |
| Theme setting persisted across restart | Passed |
| Default uninstall removes app, shortcuts and registry | Passed |
| User database hash unchanged by install and uninstall | Passed |
| Upgrade over a running 1.0.0 installation | Passed |
| Running app closed by Restart Manager | Passed |
| True 1.0.0 → 1.0.1 version upgrade (temporary installer) | Passed |
| Single uninstall entry after upgrade | Passed |
| `/REMOVEDATA` opt-in deletion (throwaway AppId/data folder) | Passed |
| Default uninstall keeps data without prompting in silent mode | Passed |
| Commercial `%APPDATA%\IDM` folder untouched | Passed |
| Bundled Qt plugins and assets present | Passed |
| Missing-DLL check at startup | Passed (app runs with no missing DLLs) |
| Install on Windows 10 x64 | **Not tested** |
| Signed artifacts | **No** |

Known limitations:

- The installer is unsigned, so SmartScreen warnings are expected.
- Automatic updates are implemented and unit/UI-tested but require a configured
  HTTPS manifest endpoint, a trusted publisher, and correctly signed binaries.
  No live signed update was executed during this build.
- Windows 10 compatibility is implemented (`MinVersion=10.0`, x64) but was not
  executed on Windows 10 hardware.
- Inno Setup's all-users mode requires elevation; this is intentional and only
  requested when the user selects that option.
- The application itself is onedir, not a single file, so the installation
  folder contains `_internal\` with Qt libraries. Do not copy only `IDM.exe`.
- The updater is a one-file executable and must ship next to the application;
  deleting `IDM_Updater.exe` disables automatic installation (checking still
  works, and the UI explains how to repair it).

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| “Windows protected your PC” | Expected for an unsigned installer. Sign the binaries; do not tell users to disable SmartScreen. |
| Antivirus flags the installer | Unsigned PyInstaller bootloaders are sometimes heuristic false positives. Sign the files and submit a false-positive report to the vendor. |
| Installer cannot close IDM | Close IDM manually, or pass `/CLOSEAPPLICATIONS`; check that no other process holds files in the install folder. |
| App starts with a blank window | Missing Qt platform plugin. Reinstall; confirm `_internal\PySide6\plugins\platforms\qwindows.dll` exists. |
| Settings or history disappeared | Check `%APPDATA%\IDM Download Manager`. A different Windows user or a cleaned profile has separate data. |
| Downloads missing after uninstall | They were saved outside the app data folder and are intentionally untouched; look in the folder chosen in Options. |
| Installer reports an existing version | A newer version is already installed. Uninstall it first or use the newer installer; the AppId is the same by design. |
| Build cannot find ISCC | Install Inno Setup 6.3+ or 7.x, or pass `-InnoSetupPath` with the install directory (for example `C:\Program Files\Inno Setup 7` or the per-user `%LOCALAPPDATA%\Programs\Inno Setup 7`). |
| Build cannot find Python | Pass `-Python "C:\path\to\python.exe"` (64-bit, 3.11+). |

Logs:

- Application: `%APPDATA%\IDM Download Manager\logs\idm.log`
- Installer (when `/LOG=` is passed): the chosen log path
- Uninstaller (when `/LOG=` is passed): the chosen log path

## Reproducing the installer tests

The disposable scripts used for validation live under
`build\installer-test\` (ignored by version control). They install into
`build\installer-test\app` and use `build\installer-test\appdata` for isolated
application data. To re-run the main flow:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build\installer-test\install-test.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\build\installer-test\launch-test.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\build\installer-test\uninstall-test.ps1
```

These tests create real shortcuts and a real uninstall registry entry for the
current user, then remove them during uninstall. Do not run them on a machine
that already has IDM installed from this project.

Python runtime detection can be checked without touching the machine: compile
with `/DPyDepsProbe`, run the result with `/VERYSILENT`, and read
`%TEMP%\idm-pydeps-probe.txt`. That build lists every interpreter found, which
of them can import `requirements.txt`, and whether the `pydeps` task would be
offered; `InitializeSetup` then aborts before anything is installed.

```bat
ISCC.exe /Qp /DPyDepsProbe=1 installer\IDM_Setup.iss
```
