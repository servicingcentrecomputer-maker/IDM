# Windows 10/11 deployment guide

## Supported systems

- Windows 10 x64 (version 1809 or later) and Windows 11 x64.
- The installer targets `x64compatible` and requires Windows 10.0 or later.
- IDM stores its data per user under `%APPDATA%\IDM Download Manager`; there is
  no dependency on the installation directory for user data.

## Install

```powershell
.\IDM_Setup_1.1.0.exe
```

Interactive setup installs for the current user by default
(`PrivilegesRequired=lowest`). Choosing an all-users installation raises UAC.
IDM never bypasses UAC.

Silent installation:

```powershell
# Per-user or previous privilege scope
.\IDM_Setup_1.1.0.exe /SILENT /SP- /NORESTART /LOG=C:\temp\idm-install.log

# Machine-wide (elevated shell)
.\IDM_Setup_1.1.0.exe /ALLUSERS /SILENT /SP- /NORESTART /LOG=C:\temp\idm-install.log
```

`UsePreviousPrivileges=yes` keeps the scope of an existing installation during
an update, so an update does not silently move a per-user install into
Program Files or the reverse.

## Configuration options

Updates can be configured in three ways, highest precedence first:

1. **Environment variables** (managed deployments).
2. **Options → Updates** (saved in the SQLite settings database).
3. **Baked defaults** in the application's `config.py`.

### Baked defaults

Before building the release, edit `config.py`:

```python
GITHUB_OWNER = "<YOUR_GITHUB_USERNAME>"
GITHUB_REPO = "IDM-Update-Server"
GITHUB_MANIFEST_BRANCH = "main"

EXPECTED_PUBLISHER = "<EXACT_AUTHENTICODE_SIGNER_NAME>"
MANIFEST_PUBLIC_KEY = "<BASE64_ED25519_PUBLIC_KEY_OR_EMPTY>"
UPDATE_CHANNEL = "stable"
```

Leaving `GITHUB_OWNER` empty keeps updates disabled with a clear message. This
is intentional: there is no fake endpoint.

### Options → Updates

| Setting | Purpose |
| --- | --- |
| Update server | HTTPS URL of `latest.json`. Blank falls back to the baked default. |
| Update channel | `stable` or `beta`. |
| Trusted publisher | Exact Authenticode signer name. Required to install. |

### Environment variables

Useful for managed fleets:

| Variable | Example |
| --- | --- |
| `IDM_UPDATE_MANIFEST_URL` | `https://raw.githubusercontent.com/Org/IDM-Update-Server/main/latest.json` |
| `IDM_UPDATE_PUBLISHER` | `Your Company Ltd` |
| `IDM_UPDATE_CHANNEL` | `stable` |
| `IDM_UPDATE_TRUSTED_HOSTS` | `cdn.example.com` |
| `IDM_UPDATE_MANIFEST_PUBLIC_KEY` | base64 Ed25519 public key |

Machine-wide example (elevated PowerShell):

```powershell
[Environment]::SetEnvironmentVariable(
  "IDM_UPDATE_MANIFEST_URL",
  "https://raw.githubusercontent.com/Org/IDM-Update-Server/main/latest.json",
  "Machine")
[Environment]::SetEnvironmentVariable(
  "IDM_UPDATE_PUBLISHER", "Your Company Ltd", "Machine")
[Environment]::SetEnvironmentVariable(
  "IDM_UPDATE_CHANNEL", "stable", "Machine")
```

Restart IDM after changing environment variables.

## Network requirements

Allow outbound HTTPS (TCP 443) to:

| Host | Purpose |
| --- | --- |
| `raw.githubusercontent.com` | Manifest download. |
| `github.com` | Release asset URL. |
| `objects.githubusercontent.com` | GitHub asset redirect target. |
| `release-assets.githubusercontent.com` | GitHub asset redirect target. |

No inbound ports, tokens or GitHub authentication are required. TLS
certificate validation is always enabled and cannot be disabled through the UI.

## Update flow

1. User chooses `Help → Check for Updates`.
2. IDM fetches `latest.json` on a background thread with connection/read
   timeouts. The interface stays responsive.
3. The manifest is validated (fields, channel, hosts, optional Ed25519
   signature) and compared using semantic versioning.
4. **Update Now** asks for explicit consent, downloads to
   `%TEMP%\IDM-Update-*`, verifies SHA-256 and Authenticode, saves settings,
   backs up the database, then hands off to `IDM_Updater.exe`.
5. IDM exits; the updater waits (without killing IDM), re-verifies the package,
   runs the signed Inno Setup installer and optionally restarts IDM.
6. Windows may show a UAC prompt for a machine-wide install. This is expected
   and is never bypassed.

Mandatory updates are still installed only with consent; there is no silent
installation.

## Data preservation

| Item | Location |
| --- | --- |
| Settings, download history, queue | `%APPDATA%\IDM Download Manager\database\idm.sqlite3` |
| Pre-update database backups | `%APPDATA%\IDM Download Manager\database\backups\` |
| Logs | `%APPDATA%\IDM Download Manager\logs\` |
| Update temp folder | `%TEMP%\IDM-Update-*` |

Updates never write user data into the installation directory. The uninstaller
asks before deleting `%APPDATA%\IDM Download Manager`; silent uninstall keeps
data unless `/REMOVEDATA` is passed.

## Verify an installed build

```powershell
(Get-Item "$env:LOCALAPPDATA\Programs\IDM\IDM.exe").VersionInfo.FileVersion
Get-AuthenticodeSignature "$env:LOCALAPPDATA\Programs\IDM\IDM.exe" |
  Format-List Status, StatusMessage, SignerCertificate
```

The exact installation path depends on the per-user/all-users choice and any
previous installation.

## Uninstall

```powershell
# Interactive; asks whether to keep user data
"$env:LOCALAPPDATA\Programs\IDM\unins000.exe"

# Silent; keeps user data
"$env:LOCALAPPDATA\Programs\IDM\unins000.exe" /SILENT

# Silent and remove user data (destructive)
"$env:LOCALAPPDATA\Programs\IDM\unins000.exe" /SILENT /REMOVEDATA
```

## Enterprise notes

- Distribute the signed installer through your normal software deployment
  system (Intune, SCCM, PDQ, Group Policy).
- Prefer setting environment variables or baking `GITHUB_OWNER` at build time
  over asking users to configure Options.
- Pin `EXPECTED_PUBLISHER` and, if possible, use signed manifests with an
  embedded public key.
- Do not allow a proxy to substitute the manifest. The client validates TLS,
  hosts and (optionally) the manifest signature; SHA-256 alone is insufficient
  if the manifest itself is not authenticated.
- Keep a copy of each released installer and its SHA-256 for audit.
