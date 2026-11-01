# Publishing an IDM release

This is the repeatable release workflow. It produces a signed installer,
uploads it as a GitHub Release asset, updates the public manifest and verifies
the result.

> A release is not operational until the public manifest endpoint and the
> actual installer have been tested from a previous IDM version. Do not report
> the update server as live before that test succeeds.

## Prerequisites

- Windows 10/11 x64 build machine.
- Python 3.12+ and the project `.venv`.
- PyInstaller and Inno Setup 6.3+ / 7.x.
- An Authenticode code-signing certificate (PFX or certificate store).
- GitHub CLI (`gh`) authenticated with an account that can publish releases
  for `<YOUR_GITHUB_USERNAME>/IDM-Update-Server`.
- A clone of `IDM-Update-Server` next to the IDM project (or pass
  `-ManifestRepoPath`).

## 1. Bump the version in all required files

Use semantic versioning: `MAJOR.MINOR.PATCH`.

| File | Field |
| --- | --- |
| `idm/version.py` | `CURRENT_VERSION` |
| `version_info.txt` | `filevers`, `prodvers`, `FileVersion`, `ProductVersion` |
| `version_info_updater.txt` | the same fields |
| `installer/IDM_Setup.iss` | `MyAppVersion`, `MyAppVerName`, `VersionInfoVersion` |

`config.py` imports `CURRENT_VERSION` from `idm/version.py`, so there is no
duplicate version constant to edit there. `build_windows.ps1` fails if the
resources and installer disagree with `idm/version.py`.

## 2. Run the tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

## 3. Build, sign, hash, update and validate

The automated path:

```powershell
# Certificate in CurrentUser\My / LocalMachine\My (recommended: no password in process args)
.\scripts\build_release.ps1 `
  -CertThumbprint <SHA1_THUMBPRINT> `
  -ManifestPrivateKey C:\Users\<you>\.idm-signing\manifest-private.pem `
  -ReleaseNotes "Faster pause/resume","Fixed queue ordering" `
  -Channel stable `
  -Publish `
  -PushManifest
```

Or with a PFX; the password is read from an environment variable, never a
command-line argument:

```powershell
$env:IDM_CODESIGN_PASSWORD = Read-Host -AsSecureString
.\scripts\build_release.ps1 `
  -PfxPath C:\secure\idm-codesign.pfx `
  -ManifestPrivateKey C:\Users\<you>\.idm-signing\manifest-private.pem `
  -ReleaseNotesFile .\release-notes.txt `
  -Publish `
  -PushManifest
```

Without `-Publish`, the script stops after producing and validating the
versioned installer and `latest.json`. That is the recommended dry run.

The script:

1. checks the requested version against `idm/version.py`;
2. verifies no release asset with the same name already exists;
3. builds `IDM.exe` and `IDM_Updater.exe` with PyInstaller;
4. signs both executables and verifies the signer;
5. compiles and signs `IDM_Setup.exe`;
6. copies it to `IDM_Setup_<version>.exe` and computes SHA-256;
7. writes `IDM-Update-Server/latest.json`;
8. signs the manifest when `MANIFEST_PUBLIC_KEY` is set;
9. validates manifest + installer before any publish;
10. creates/uploads the release asset without `--clobber`;
11. optionally commits and pushes `latest.json`.

If validation fails, the previous `latest.json` is restored.

## 4. Manual equivalent

### Build and sign

```powershell
# Build application and updater only
.\build_windows.ps1 -SkipInstaller -Force

# Sign both executables
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /sha1 <SHA1_THUMBPRINT> `
  /d "IDM Internet Download Manager" .\dist\IDM\IDM.exe
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /sha1 <SHA1_THUMBPRINT> `
  /d "IDM Updater" .\dist\IDM\IDM_Updater.exe

# Compile and sign the installer
& "C:\Program Files\Inno Setup 7\ISCC.exe" .\installer\IDM_Setup.iss
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /sha1 <SHA1_THUMBPRINT> `
  /d "IDM Setup" .\dist-installer\IDM_Setup.exe
```

### Hash

```powershell
.\scripts\generate_hash.ps1 -Path .\dist-installer\IDM_Setup.exe
```

### Create the GitHub Release and upload the asset

```powershell
Copy-Item .\dist-installer\IDM_Setup.exe .\dist-installer\IDM_Setup_1.1.0.exe
gh release create v1.1.0 .\dist-installer\IDM_Setup_1.1.0.exe `
  --repo <YOUR_GITHUB_USERNAME>/IDM-Update-Server `
  --title "IDM 1.1.0" `
  --notes "Faster pause/resume. Fixed queue ordering."
```

The installer is a release **asset**, not a repository file.

If the release already exists but the asset does not:

```powershell
gh release upload v1.1.0 .\dist-installer\IDM_Setup_1.1.0.exe `
  --repo <YOUR_GITHUB_USERNAME>/IDM-Update-Server
```

Never use `gh release upload --clobber`. Published assets are immutable. If a
bad installer was published, publish a new version instead of overwriting it.

### Update latest.json

```json
{
  "app_name": "IDM",
  "channel": "stable",
  "latest_version": "1.1.0",
  "minimum_supported_version": "1.0.0",
  "release_date": "2026-11-15",
  "release_notes": [
    "Faster pause/resume",
    "Fixed queue ordering"
  ],
  "download_url": "https://github.com/<YOUR_GITHUB_USERNAME>/IDM-Update-Server/releases/download/v1.1.0/IDM_Setup_1.1.0.exe",
  "sha256": "<LOWERCASE_SHA256_OF_IDM_SETUP_1.1.0.EXE>",
  "package_size": 73400320,
  "mandatory": false,
  "manifest_signature": ""
}
```

If signed manifests are enabled, sign it:

```powershell
.\.venv\Scripts\python.exe scripts\sign_manifest.py sign `
  --manifest .\IDM-Update-Server\latest.json `
  --private-key C:\Users\<you>\.idm-signing\manifest-private.pem
```

### Validate before publishing

```powershell
.\.venv\Scripts\python.exe scripts\validate_manifest.py `
  .\IDM-Update-Server\latest.json `
  --channel stable `
  --installer .\dist-installer\IDM_Setup_1.1.0.exe
```

If no manifest public key is configured, add `--allow-unsigned` explicitly.

### Publish the manifest

```powershell
git -C .\IDM-Update-Server add latest.json
git -C .\IDM-Update-Server commit -m "Release IDM 1.1.0"
git -C .\IDM-Update-Server push
```

## 5. Test the public endpoint

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/<YOUR_GITHUB_USERNAME>/IDM-Update-Server/main/latest.json
```

Confirm:

- HTTP 200;
- the expected `latest_version`, `channel` and `sha256`;
- `download_url` opens the release asset;
- the asset SHA-256 equals the manifest value.

## 6. Test the real update path

1. Install the previous version (for example 1.0.0) in a clean Windows VM.
2. Confirm `Help → About IDM` shows 1.0.0.
3. Run `Help → Check for Updates`.
4. Confirm the update is offered.
5. Click **Update Now**, confirm the download progress bar, hash/signature
   verification, UAC prompt, installer completion and restart.
6. Confirm `Help → About IDM` shows the new version.
7. Confirm download history, settings, queue and database are preserved
   (`%APPDATA%\IDM Download Manager`).

Only after this succeeds may the update server be described as operational.

## 7. Channel rules

| Installed channel | Accepts manifest channel |
| --- | --- |
| `stable` | `stable` only |
| `beta` | `stable` or `beta` |

A stable installation that sees a beta manifest reports a channel mismatch and
does not offer the update. Downgrades are never offered on either channel.

## 8. Rollback

- Publish a new, higher version with a fix. Published assets are never
  overwritten.
- If a manifest is wrong, publish a corrected manifest. IDM will not downgrade
  an already-updated installation.
- Keep the previous `latest.json` in `releases/latest-<version>.json` for
  reference if desired, but never point IDM at an older manifest expecting a
  downgrade.
