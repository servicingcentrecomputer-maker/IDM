# Troubleshooting

All messages below are produced by the client and are safe to show to users.
Logs are written to `%APPDATA%\IDM Download Manager\logs\idm.log` and
`updater.log`. They contain versions, URLs without query strings, hashes and
error details, but no credentials or tokens.

## Manifest and endpoint

| Symptom | Cause and fix |
| --- | --- |
| “Updates are not configured.” | `GITHUB_OWNER` in `config.py` is empty and no manifest URL is saved or set through `IDM_UPDATE_MANIFEST_URL`. Fill one of them. |
| Public `curl` returns 404 | Repository is private, wrong branch, wrong path, or the file has not been pushed. Confirm the repository is public and the raw URL ends in `/main/latest.json`. |
| Public `curl` returns old content | `raw.githubusercontent.com` CDN cache. Wait a few minutes and re-check; include `-H "Cache-Control: no-cache"`. IDM already sends no-cache headers. |
| “The update server returned HTTP 403” | A proxy or GitHub is blocking anonymous access. The client does not send a token; do not add one. Use a public repository. |
| “The update server did not respond in time.” | 10 s connect / 30 s read timeout. Check proxy, DNS and firewall; retry. |
| “Could not connect to the update server.” | Offline, DNS failure or TLS interception. Confirm HTTPS 443 to `raw.githubusercontent.com`. |
| “A secure HTTPS connection … could not be established.” | Invalid/expired TLS certificate or an intercepting proxy. Do not add a TLS-bypass option; fix the certificate trust chain. |
| “The update manifest host is not trusted by this installation.” | The configured URL host is not derived from `config.py` or listed in `IDM_UPDATE_TRUSTED_HOSTS`. Prefer the standard raw GitHub URL. |
| “The update server redirected to an untrusted host …” | A redirect left the allow-list or downgraded to HTTP. Inspect the endpoint; do not weaken the host list. |

## Manifest content

| Symptom | Cause and fix |
| --- | --- |
| “The update manifest is not valid JSON …” | Fix trailing commas, comments or quoting. Validate with `scripts\validate_manifest.py`. |
| “unsupported field(s): …” | The client rejects unknown fields. Remove them (for example comments or `_note`). |
| “duplicate field …” | JSON contains the same key twice. Remove the duplicate. |
| “channel must be either “stable” or “beta”.” | Use exactly `stable` or `beta`. |
| “This installation follows the stable channel, but the update server is publishing the beta channel.” | Expected. Switch to beta in Options → Updates if the user should receive it, or publish a stable manifest. |
| “minimum_supported_version cannot be newer than latest_version.” | Fix the manifest. An installed version below the minimum is treated as mandatory. |
| “download_url must use HTTPS.” | Use the GitHub Release HTTPS URL. |
| “The download host “X” is not trusted.” | Use `github.com` for release assets or list a legitimate CDN in `IDM_UPDATE_TRUSTED_HOSTS`. |
| “download_url must point to the Windows installer (.exe).” | The asset name must end in `.exe`; GitHub release asset URLs normally do. |
| “sha256 must be exactly 64 hexadecimal characters.” | Recompute: `scripts\generate_hash.ps1 -Path <installer>`. |
| “manifest_signature is required.” | Include `"manifest_signature": ""` for an unsigned manifest, or sign it. |
| “The update manifest signature is invalid.” | The manifest changed after signing or was signed with a different key. Re-sign with the private key matching `MANIFEST_PUBLIC_KEY`. |
| “The update manifest is unsigned, but this build requires a signed manifest.” | Sign `latest.json` or remove `MANIFEST_PUBLIC_KEY` from the build (not recommended). |
| “MANIFEST_PUBLIC_KEY must decode to exactly 32 Ed25519 public key bytes.” | Use the base64 output of `scripts\sign_manifest.py keygen`, not a PEM file. |
| “Signed manifests are required, but the cryptography package is not available.” | Install `cryptography` (`requirements.txt`) and rebuild. |

## Version decisions

| Symptom | Cause and fix |
| --- | --- |
| “You are using the latest version of IDM.” but a release exists | Manifest `latest_version` is not greater than the installed version, or the channel does not match. |
| No update offered after a downgrade attempt | Downgrades are always rejected, even if `mandatory` is true. |
| “The installed version is newer than the latest published release.” | The user is on a beta/newer build than the stable manifest. This is informational, not an error. |
| Mandatory update not silent | By design. Mandatory updates still require explicit consent and are cancelled by default. |

## Download and verification

| Symptom | Cause and fix |
| --- | --- |
| “The downloaded installer failed SHA-256 verification.” | The manifest hash does not match the uploaded asset. Recompute from the exact uploaded file; replace the asset with a new version rather than overwriting. |
| “The installer does not have a valid Windows Authenticode signature.” | Upload the signed installer. Signing the installer after Inno Setup is required; signing only `IDM.exe` is not enough. |
| “The installer was signed by “X”, not the configured publisher “Y”.” | Copy the exact signer name from `Get-AuthenticodeSignature`. Partial matches are rejected on purpose. |
| “No trusted update publisher is configured.” | Set `EXPECTED_PUBLISHER` in `config.py` or Options → Updates, or `IDM_UPDATE_PUBLISHER`. Installation is blocked without it. |
| Download stops partway | Retry resumes with HTTP Range. The `.part` file lives under `%TEMP%\IDM-Update-*`. |
| “The installer is larger than the configured size limit.” | Default cap is 512 MiB. A larger legitimate installer requires a code change, not a manifest override. |
| “The update server returned an empty installer.” | The release asset is missing or truncated. Re-upload as a new release. |

## Installation

| Symptom | Cause and fix |
| --- | --- |
| “The Updater component is missing.” | Running from source or a broken install. Use the packaged build or reinstall; `IDM_Updater.exe` must sit next to `IDM.exe`. |
| “IDM did not close, so the update was not installed.” | IDM did not exit within 180 seconds. Close it manually and retry. The updater never force-kills IDM. |
| UAC appears | Expected for a machine-wide install. The updater never bypasses UAC. |
| Update installed but IDM did not restart | Start it from the Start menu. Check `updater.log` for the restart error. |
| Temp update folder remains | The updater executable was locked during cleanup. The next IDM start removes marked/stale `IDM-Update-*` folders after 24 hours. |
| Settings/history disappeared | User data lives in `%APPDATA%\IDM Download Manager`. Check whether an uninstall used `/REMOVEDATA` or the interactive “remove data” choice. |

## Release automation

| Symptom | Cause and fix |
| --- | --- |
| CI workflow fails on `latest.json` | The repository still contains the template (`YOUR_GITHUB_USERNAME`, `REPLACE_WITH`). Replace values with a real release. |
| `build_release.ps1` says a release asset already exists | Published assets are immutable. Bump the version and publish a new release; do not use `--clobber`. |
| `signtool` not found | Install the Windows SDK or set `IDM_SIGNTOOL` to the full path. |
| `IDM_CODESIGN_PASSWORD` is not set | For PFX signing, set it in the current shell. Prefer a certificate-store thumbprint (`-CertThumbprint`) to avoid passwords entirely. |
| `MANIFEST_PUBLIC_KEY is set, so -ManifestPrivateKey is required` | Pass the Ed25519 private key or clear the public key. The private key must not be committed. |
| `gh` authentication error | Run `gh auth login`; the script uses the user's existing GitHub CLI login. No PAT is embedded in IDM. |

## Test matrix

The automated suite covers: public manifest parsing (with injected/fake
transport), invalid JSON and fields, unknown fields, channel policy, incorrect
version, missing download URL, untrusted host, invalid SHA-256, invalid
signature, network failures, update available, no update available, download
resume, updater handoff and settings/database persistence. A real end-to-end
signed update and the actual public GitHub endpoint must be tested manually;
they are not proven by unit tests alone.
