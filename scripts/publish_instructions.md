# IDM release publishing instructions

This is the canonical checklist for publishing an IDM update. The full
narrative version is in `IDM-Update-Server/docs/PUBLISHING.md`.

## Before the first release

1. Create a **public** GitHub repository `IDM-Update-Server`.
2. Push the scaffold from `IDM-Update-Server/` to `main`.
3. Set `GITHUB_OWNER` and `EXPECTED_PUBLISHER` in the IDM application's
   `config.py`. Optionally set `MANIFEST_PUBLIC_KEY`.
4. Generate an Ed25519 manifest key pair:

   ```powershell
   .\.venv\Scripts\python.exe scripts\sign_manifest.py keygen `
     --private-key C:\secure\idm-manifest.pem
   ```

   Embed only the printed public key in `config.py`. Store the private key
   offline.
5. Obtain a code-signing certificate and install it in the certificate store
   (preferred) or keep the PFX outside the repository.

## Every release

1. **Bump the version** in `idm/version.py`, `version_info.txt`,
   `version_info_updater.txt` and `installer/IDM_Setup.iss`.
2. **Run the tests**:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests -q
   ```

3. **Build, sign, hash, write the manifest and validate**:

   ```powershell
   .\scripts\build_release.ps1 `
     -CertThumbprint <SHA1_THUMBPRINT> `
     -ManifestPrivateKey C:\secure\idm-manifest.pem `
     -ReleaseNotes "Release note one","Release note two" `
     -Channel stable
   ```

   This is a dry run. It refuses to continue if the release asset already
   exists (when `-Publish` is used) or if validation fails.

4. **Inspect the result**:

   - `dist-installer\IDM_Setup_<version>.exe`
   - `IDM-Update-Server\latest.json`
   - `scripts\generate_hash.ps1 -Path <versioned installer>` should match
     `sha256`.

5. **Publish**:

   ```powershell
   .\scripts\build_release.ps1 `
     -CertThumbprint <SHA1_THUMBPRINT> `
     -ManifestPrivateKey C:\secure\idm-manifest.pem `
     -ReleaseNotes "Release note one","Release note two" `
     -Channel stable `
     -Publish `
     -PushManifest
   ```

   Or publish manually with `gh release create` / `gh release upload` and
   `git push`. **Never use `--clobber`.** A bad asset must be replaced by a new
   version.

6. **Verify the public endpoint**:

   ```powershell
   curl.exe -fsSL https://raw.githubusercontent.com/<owner>/IDM-Update-Server/main/latest.json
   ```

7. **Test the real update** from the previous installed version in a clean
   Windows 10/11 VM: check, download, hash/signature verification, UAC,
   install, restart and data preservation.

## Security rules

- Never put a GitHub PAT or token in the desktop application.
- Never commit the PFX, its password, or the Ed25519 private key.
- `gh` uses the operator's existing login; the app uses anonymous public reads.
- `build_release.ps1` reads the PFX password from
  `IDM_CODESIGN_PASSWORD`; never pass it as a command-line argument.
- Published release assets are immutable. `-Publish` checks for an existing
  asset and uploads without `--clobber`.
- An unsigned or wrong-publisher installer is rejected by IDM even if the
  SHA-256 matches.
- A manifest signature protects the manifest itself; SHA-256 alone does not
  authenticate the manifest.

## Do not claim the server is live until

- the public manifest URL returns HTTP 200 from an unauthenticated client;
- `latest.json` matches the uploaded installer hash;
- a previous IDM version successfully checks, downloads, verifies and installs
  the update on Windows 10/11.

Unit tests and a dry run do not prove the public endpoint or the real
installation path.
