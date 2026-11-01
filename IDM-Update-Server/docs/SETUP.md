# Update server setup

## 1. Create the GitHub repository

1. Sign in to GitHub.
2. Create a **public** repository named exactly `IDM-Update-Server`.
   - Public read access is required. A private repository makes
     `raw.githubusercontent.com` return 404 and IDM cannot check for updates.
   - Do not use GitHub Releases-only hosting for the manifest: the manifest URL
     must stay stable.
3. Use `main` as the default branch (or change `GITHUB_MANIFEST_BRANCH` in
   IDM's `config.py` to match).
4. Push the contents of this folder. The expected layout is:

   ```text
   IDM-Update-Server/
     latest.json
     manifest.schema.json
     README.md
     releases/
     docs/
     .github/workflows/validate-manifest.yml
   ```

5. Do not commit installers. Upload them as GitHub Release assets.

## 2. Configure IDM

Edit the IDM application's top-level `config.py`:

```python
GITHUB_OWNER = "<YOUR_GITHUB_USERNAME>"
GITHUB_REPO = "IDM-Update-Server"
GITHUB_MANIFEST_BRANCH = "main"
GITHUB_MANIFEST_PATH = "latest.json"

EXPECTED_PUBLISHER = "<EXACT_AUTHENTICODE_SIGNER_NAME>"
MANIFEST_PUBLIC_KEY = ""  # or the base64 Ed25519 public key
UPDATE_CHANNEL = "stable"
```

`UPDATE_MANIFEST_URL` is derived automatically:

```text
https://raw.githubusercontent.com/<YOUR_GITHUB_USERNAME>/IDM-Update-Server/main/latest.json
```

`config.py` is bundled into the PyInstaller build. Set these values before
building the release.

`EXPECTED_PUBLISHER` is the exact Authenticode signer name reported by Windows,
not the product name. Check it with:

```powershell
(Get-AuthenticodeSignature .\dist-installer\IDM_Setup.exe).SignerCertificate.GetNameInfo(
  [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false)
```

## 3. Verify public access

From a machine or network that is not signed in to GitHub:

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/<YOUR_GITHUB_USERNAME>/IDM-Update-Server/main/latest.json
```

Expected: HTTP 200 and the JSON document.

Other checks:

```powershell
# Content type and cache headers
curl.exe -I https://raw.githubusercontent.com/<YOUR_GITHUB_USERNAME>/IDM-Update-Server/main/latest.json

# Confirm the file is on main
git -C IDM-Update-Server log -1 --oneline -- latest.json
```

`raw.githubusercontent.com` is cached for a few minutes. After pushing a new
manifest, allow for propagation, then re-run the check. IDM sends
`Cache-Control: no-cache`, but the CDN may still briefly serve the previous
document.

## 4. Managed configuration

Environment variables override saved settings and baked defaults:

| Variable | Meaning |
| --- | --- |
| `IDM_UPDATE_MANIFEST_URL` | Full manifest URL. Use only if not using `GITHUB_OWNER`. |
| `IDM_UPDATE_PUBLISHER` | Exact Authenticode signer name. |
| `IDM_UPDATE_CHANNEL` | `stable` or `beta`. |
| `IDM_UPDATE_TRUSTED_HOSTS` | Extra comma/semicolon separated download hosts. |
| `IDM_UPDATE_MANIFEST_PUBLIC_KEY` | Base64 Ed25519 public key (normally baked in). |

Never put a GitHub PAT, token or credential in these variables or in the
desktop application. The manifest repository must be readable anonymously.

## 5. Signed manifests

Optional but recommended for high-value deployments:

1. Generate a key pair on an offline/secure machine:

   ```powershell
   .\.venv\Scripts\python.exe scripts\sign_manifest.py keygen `
     --private-key C:\Users\<you>\.idm-signing\manifest-private.pem
   ```

2. Put the printed base64 public key in IDM's `config.py`
   (`MANIFEST_PUBLIC_KEY`).
3. Sign `latest.json` before publishing:

   ```powershell
   .\.venv\Scripts\python.exe scripts\sign_manifest.py sign `
     --manifest IDM-Update-Server\latest.json `
     --private-key C:\Users\<you>\.idm-signing\manifest-private.pem
   ```

4. Set the repository variable `MANIFEST_PUBLIC_KEY` (Settings → Secrets and
   variables → Actions → Variables) so CI verifies the signature.

If a public key is configured, an unsigned or incorrectly signed manifest is
rejected. Keep the private key out of the repository and out of GitHub Actions
unless you use an encrypted secret and a controlled workflow.

## 6. Initial CI state

The committed `latest.json` is a template with `YOUR_GITHUB_USERNAME` and
`REPLACE_WITH_...` values. The validation workflow intentionally fails until
you replace it with a real release. This prevents an accidental public
template from being mistaken for a working update.
