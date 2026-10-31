# releases/

Release installers belong in **GitHub Releases**, not in this folder.

GitHub Release assets keep large binaries out of the source repository and let
IDM download them over HTTPS with resume support. The manifest `download_url`
must point at the versioned asset, for example:

```
https://github.com/<owner>/IDM-Update-Server/releases/download/v1.1.0/IDM_Setup_1.1.0.exe
```

This folder may contain small text files such as:

- `IDM_Setup_<version>.exe.sha256` checksum files
- release note drafts
- archived `latest-<version>.json` snapshots for rollback reference

Do not commit `.exe`, `.msi`, `.zip` or other installer binaries.
