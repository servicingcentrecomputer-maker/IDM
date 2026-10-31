#Requires -Version 5.1
<#
.SYNOPSIS
    Builds, signs, validates and optionally publishes an IDM release.

.DESCRIPTION
    Repeatable release workflow:

      1. verify the source version and release parameters
      2. build IDM.exe and IDM_Updater.exe with PyInstaller
      3. sign both executables (Authenticode)
      4. compile IDM_Setup.exe with Inno Setup and sign it
      5. compute the installer SHA-256
      6. write latest.json in the IDM-Update-Server checkout
      7. optionally sign the manifest with an Ed25519 key
      8. validate the manifest and installer before publishing
      9. create/upload the GitHub Release asset (never overwrite)
     10. optionally commit and push latest.json

    No GitHub token, PFX password or private key is ever written to the IDM
    desktop application.  Signing credentials come from the local certificate
    store or environment variables.  Publishing uses the user's existing
    `gh auth` login.

.PARAMETER Version
    Expected MAJOR.MINOR.PATCH. Must match idm/version.py. Defaults to that file.

.PARAMETER Channel
    stable or beta.

.PARAMETER MinimumSupportedVersion
    Oldest version that may still receive this release. Defaults to the value
    already in latest.json.

.PARAMETER ReleaseNotes
    One or more release-note lines.

.PARAMETER ReleaseNotesFile
    Text file with one release-note line per item (overrides -ReleaseNotes).

.PARAMETER ManifestRepoPath
    Path to the IDM-Update-Server checkout. Defaults to .\IDM-Update-Server.

.PARAMETER ManifestPrivateKey
    Ed25519 PEM private key used by scripts\sign_manifest.py. Required when
    MANIFEST_PUBLIC_KEY is set in config.py.

.PARAMETER CertThumbprint
    SHA-1 thumbprint of a code-signing certificate in CurrentUser\My or
    LocalMachine\My. Preferred over a PFX file because no password is needed.

.PARAMETER PfxPath
    Code-signing PFX. The password is read from IDM_CODESIGN_PASSWORD; never
    pass it on the command line.

.PARAMETER AllowUnsigned
    Explicitly allow an unsigned build. Only for internal testing; a production
    release must be Authenticode-signed.

.PARAMETER Publish
    Create or update the GitHub Release and upload the installer asset.

.PARAMETER PushManifest
    With -Publish, commit and push latest.json to the update server repository.

.EXAMPLE
    $env:IDM_CODESIGN_PASSWORD = Read-Host -AsSecureString
    .\scripts\build_release.ps1 -CertThumbprint ABCD... -ManifestPrivateKey C:\secure\manifest.pem -ReleaseNotes "Faster resume","Fixed queue" -Publish -PushManifest
#>
[CmdletBinding()]
param(
    [string]$Version = "",
    [ValidateSet("stable", "beta")]
    [string]$Channel = "stable",
    [string]$MinimumSupportedVersion = "",
    [string[]]$ReleaseNotes = @(),
    [string]$ReleaseNotesFile = "",
    [switch]$Mandatory,
    [string]$ManifestRepoPath = "",
    [string]$ManifestPrivateKey = "",
    [string]$CertThumbprint = "",
    [string]$PfxPath = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [string]$InnoSetupPath = "",
    [switch]$AllowUnsigned,
    [switch]$SkipBuild,
    [switch]$SkipTests,
    [switch]$Publish,
    [switch]$PushManifest,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $ScriptRoot))
$DistInstallerDir = Join-Path $AppRoot "dist-installer"
$InstallerPath = Join-Path $DistInstallerDir "IDM_Setup.exe"

if (-not $ManifestRepoPath) {
    $ManifestRepoPath = Join-Path $AppRoot "IDM-Update-Server"
}
$ManifestRepoPath = [System.IO.Path]::GetFullPath($ManifestRepoPath)
$ManifestPath = Join-Path $ManifestRepoPath "latest.json"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail {
    param([string]$Message)
    throw $Message
}

function Find-Python {
    $venv = Join-Path $AppRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return $venv }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    Fail "Python was not found. Run build_windows.ps1 first or install Python 3.12+."
}

function Get-ConfigValue {
    param([string]$Name)
    Push-Location $AppRoot
    try {
        $value = & $Python -c "import config; print(config.$Name)"
        if ($LASTEXITCODE -ne 0) { Fail "Could not read config.$Name." }
        return (($value | Select-Object -First 1) -as [string]).Trim()
    }
    finally {
        Pop-Location
    }
}

function Get-SourceVersion {
    $source = Get-Content -LiteralPath (Join-Path $AppRoot "idm\version.py") -Raw
    $match = [regex]::Match($source, 'CURRENT_VERSION\s*=\s*"([^"]+)"')
    if (-not $match.Success) { Fail "Could not read CURRENT_VERSION from idm\version.py." }
    return $match.Groups[1].Value
}

function Get-ReleaseNotes {
    if ($ReleaseNotesFile) {
        $file = [System.IO.Path]::GetFullPath($ReleaseNotesFile)
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            Fail "Release notes file not found: $file"
        }
        $lines = Get-Content -LiteralPath $file | Where-Object { $_.Trim() }
    }
    else {
        $lines = $ReleaseNotes | Where-Object { $_ -and $_.Trim() }
    }
    $clean = @($lines | ForEach-Object { $_.Trim() })
    if ($clean.Count -eq 0) {
        Fail "Provide -ReleaseNotes or -ReleaseNotesFile."
    }
    return $clean
}

function Find-SignTool {
    if ($env:IDM_SIGNTOOL) {
        if (Test-Path -LiteralPath $env:IDM_SIGNTOOL -PathType Leaf) { return $env:IDM_SIGNTOOL }
        Fail "IDM_SIGNTOOL does not point to signtool.exe: $env:IDM_SIGNTOOL"
    }
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $kitsRoots = @()
    if (${env:ProgramFiles(x86)}) { $kitsRoots += Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin" }
    if ($env:ProgramFiles) { $kitsRoots += Join-Path $env:ProgramFiles "Windows Kits\10\bin" }
    foreach ($root in $kitsRoots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        $candidates = Get-ChildItem -LiteralPath $root -Directory |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
        $found = $candidates | Select-Object -First 1
        if ($found) { return $found }
    }
    Fail "signtool.exe was not found. Install the Windows SDK or set IDM_SIGNTOOL."
}

function Find-ISCC {
    if ($InnoSetupPath) {
        if (Test-Path -LiteralPath $InnoSetupPath -PathType Leaf) { return $InnoSetupPath }
        $candidate = Join-Path $InnoSetupPath "ISCC.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        Fail "ISCC.exe was not found at -InnoSetupPath '$InnoSetupPath'."
    }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $roots = @(${env:ProgramFiles(x86)}, $env:ProgramFiles) | Where-Object { $_ }
    foreach ($root in $roots) {
        foreach ($edition in @("Inno Setup 7", "Inno Setup 6")) {
            $candidate = Join-Path $root "$edition\ISCC.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    Fail "Inno Setup was not found. Install Inno Setup 6.3+ or pass -InnoSetupPath."
}

function Invoke-SignTool {
    param([string]$FilePath, [string]$Description)
    $arguments = @("sign", "/fd", "SHA256", "/tr", $TimestampUrl, "/td", "SHA256")
    if ($CertThumbprint) {
        $arguments += @("/sha1", $CertThumbprint)
    }
    elseif ($PfxPath) {
        $password = $env:IDM_CODESIGN_PASSWORD
        if (-not $password) {
            Fail "IDM_CODESIGN_PASSWORD is not set. It must contain the PFX password."
        }
        $arguments += @("/f", [System.IO.Path]::GetFullPath($PfxPath), "/p", $password)
    }
    else {
        Fail "No signing credentials. Pass -CertThumbprint or -PfxPath, or use -AllowUnsigned for a test build."
    }
    $arguments += @("/d", $Description, [System.IO.Path]::GetFullPath($FilePath))
    & $SignTool @arguments
    if ($LASTEXITCODE -ne 0) {
        Fail "signtool failed for $FilePath with exit code $LASTEXITCODE."
    }
}

function Assert-Signature {
    param([string]$FilePath, [string]$ExpectedPublisher)
    $signature = Get-AuthenticodeSignature -LiteralPath $FilePath
    if ($signature.Status -ne "Valid") {
        if ($AllowUnsigned) {
            Write-Warning "Unsigned or invalid signature on $FilePath ($($signature.Status)); allowed by -AllowUnsigned."
            return
        }
        Fail "$FilePath does not have a valid Authenticode signature ($($signature.Status))."
    }
    $certificate = $signature.SignerCertificate
    if ($null -eq $certificate) {
        Fail "$FilePath has no signer certificate."
    }
    $simpleName = [string]$certificate.GetNameInfo(
        [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName,
        $false)
    $subject = [string]$certificate.Subject
    if (-not $ExpectedPublisher) {
        if ($AllowUnsigned) {
            Write-Warning "EXPECTED_PUBLISHER is empty; publisher identity was not checked."
            return
        }
        Fail "EXPECTED_PUBLISHER is empty in config.py. Set the exact signer name before publishing."
    }
    if ($simpleName -ine $ExpectedPublisher -and $subject -ine $ExpectedPublisher) {
        Fail "$FilePath was signed by '$simpleName' / '$subject', not the configured publisher '$ExpectedPublisher'."
    }
}

function Test-ReleaseAssetExists {
    param([string]$Owner, [string]$Repo, [string]$Tag, [string]$AssetName)
    $json = & gh release view $Tag --repo "$Owner/$Repo" --json assets 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    try {
        $data = $json | ConvertFrom-Json
    }
    catch {
        return $false
    }
    foreach ($asset in @($data.assets)) {
        if ($asset.name -eq $AssetName) { return $true }
    }
    return $false
}

# ------------------------------------------------------------------ parameters
$Python = Find-Python
$SourceVersion = Get-SourceVersion
if (-not $Version) { $Version = $SourceVersion }
if ($Version -ne $SourceVersion) {
    Fail "Requested version $Version does not match idm\version.py ($SourceVersion). Bump the version files first."
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Fail "Release builds require MAJOR.MINOR.PATCH; found '$Version'."
}

$Owner = Get-ConfigValue "GITHUB_OWNER"
$Repo = Get-ConfigValue "GITHUB_REPO"
$ExpectedPublisher = Get-ConfigValue "EXPECTED_PUBLISHER"
$ManifestPublicKey = Get-ConfigValue "MANIFEST_PUBLIC_KEY"
$Notes = Get-ReleaseNotes
$Tag = "v$Version"
$VersionedName = "IDM_Setup_$Version.exe"
$VersionedInstaller = Join-Path $DistInstallerDir $VersionedName

if ($Publish) {
    if (-not $Owner) { Fail "GITHUB_OWNER is empty in config.py; cannot publish." }
    if (-not $Repo) { Fail "GITHUB_REPO is empty in config.py; cannot publish." }
    $gh = Get-Command gh.exe -ErrorAction SilentlyContinue
    if (-not $gh) {
        $gh = Get-Command gh -ErrorAction SilentlyContinue
    }
    if (-not $gh) { Fail "GitHub CLI (gh) is required for -Publish." }
    & gh auth status *> $null
    if ($LASTEXITCODE -ne 0) { Fail "gh is not authenticated. Run 'gh auth login' first." }

    Write-Step "Checking that the release asset does not already exist"
    if (Test-ReleaseAssetExists -Owner $Owner -Repo $Repo -Tag $Tag -AssetName $VersionedName) {
        Fail "Release asset $VersionedName already exists on $Tag. Published assets are never overwritten."
    }
    Write-Host "No existing asset $VersionedName on $Tag."
}

# ------------------------------------------------------------------ build/sign
if (-not $SkipBuild) {
    Write-Step "Building IDM.exe and IDM_Updater.exe"
    $buildScript = Join-Path $AppRoot "build_windows.ps1"
    $buildArgs = @("-File", $buildScript, "-SkipInstaller")
    if ($SkipTests) { $buildArgs += "-SkipTests" }
    if ($Force) { $buildArgs += "-Force" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass @buildArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "build_windows.ps1 failed with exit code $LASTEXITCODE."
    }

    $appExe = Join-Path $AppRoot "dist\IDM\IDM.exe"
    $updaterExe = Join-Path $AppRoot "dist\IDM\IDM_Updater.exe"
    if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) { Fail "Missing $appExe" }
    if (-not (Test-Path -LiteralPath $updaterExe -PathType Leaf)) { Fail "Missing $updaterExe" }

    if (-not $AllowUnsigned -or $CertThumbprint -or $PfxPath) {
        $SignTool = Find-SignTool
        Write-Step "Signing IDM.exe and IDM_Updater.exe"
        Invoke-SignTool -FilePath $appExe -Description "IDM Internet Download Manager"
        Invoke-SignTool -FilePath $updaterExe -Description "IDM Updater"
        Assert-Signature -FilePath $appExe -ExpectedPublisher $ExpectedPublisher
        Assert-Signature -FilePath $updaterExe -ExpectedPublisher $ExpectedPublisher
    }
    else {
        Write-Warning "Skipping executable signing because -AllowUnsigned was supplied."
    }

    Write-Step "Compiling IDM_Setup.exe"
    $iscc = Find-ISCC
    New-Item -ItemType Directory -Force -Path $DistInstallerDir | Out-Null
    & $iscc "/Qp" (Join-Path $AppRoot "installer\IDM_Setup.iss")
    if ($LASTEXITCODE -ne 0) { Fail "Inno Setup failed with exit code $LASTEXITCODE." }

    if ($CertThumbprint -or $PfxPath) {
        Write-Step "Signing IDM_Setup.exe"
        Invoke-SignTool -FilePath $InstallerPath -Description "IDM Setup"
    }
    elseif (-not $AllowUnsigned) {
        Fail "No signing credentials. A production installer must be signed; use -AllowUnsigned only for testing."
    }
}
elseif (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    Fail "-SkipBuild was used but $InstallerPath does not exist."
}

if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    Fail "Installer was not produced: $InstallerPath"
}

Write-Step "Verifying the installer signature"
Assert-Signature -FilePath $InstallerPath -ExpectedPublisher $ExpectedPublisher

Copy-Item -LiteralPath $InstallerPath -Destination $VersionedInstaller -Force
$size = (Get-Item -LiteralPath $VersionedInstaller).Length
if ($size -le 0) { Fail "The installer is empty." }
$sha256 = (Get-FileHash -LiteralPath $VersionedInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Installer: $VersionedInstaller"
Write-Host "Size     : $size bytes"
Write-Host "SHA-256  : $sha256"

# ------------------------------------------------------------------ manifest
Write-Step "Updating latest.json"
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    Fail "Manifest not found: $ManifestPath. Clone IDM-Update-Server first."
}
if (-not $MinimumSupportedVersion) {
    $existing = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    $MinimumSupportedVersion = [string]$existing.minimum_supported_version
}
if (-not $MinimumSupportedVersion) { $MinimumSupportedVersion = $Version }
try {
    $minimumParsed = [version]$MinimumSupportedVersion
    $versionParsed = [version]$Version
}
catch {
    Fail "MinimumSupportedVersion is not a numeric MAJOR.MINOR.PATCH: $MinimumSupportedVersion"
}
if ($minimumParsed -gt $versionParsed) {
    Fail "MinimumSupportedVersion ($MinimumSupportedVersion) cannot be newer than $Version."
}

$downloadUrl = "https://github.com/$Owner/$Repo/releases/download/$Tag/$VersionedName"
$manifest = [ordered]@{
    app_name                 = "IDM"
    channel                  = $Channel
    latest_version           = $Version
    minimum_supported_version = $MinimumSupportedVersion
    release_date             = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
    release_notes            = @($Notes)
    download_url             = $downloadUrl
    sha256                   = $sha256
    mandatory                = [bool]$Mandatory
    manifest_signature       = ""
}

$manifestBackup = Get-Content -LiteralPath $ManifestPath -Raw
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Save-Manifest {
    param($Object)
    $json = $Object | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($ManifestPath, $json + "`n", $utf8NoBom)
}

try {
    Save-Manifest $manifest

    if ($ManifestPublicKey) {
        if (-not $ManifestPrivateKey) {
            Fail "MANIFEST_PUBLIC_KEY is set, so -ManifestPrivateKey is required to sign latest.json."
        }
        Write-Step "Signing latest.json with Ed25519"
        Push-Location $AppRoot
        try {
            & $Python (Join-Path $ScriptRoot "sign_manifest.py") sign `
                --manifest $ManifestPath --private-key $ManifestPrivateKey
            if ($LASTEXITCODE -ne 0) { Fail "Manifest signing failed." }
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Warning "MANIFEST_PUBLIC_KEY is empty; latest.json will be published unsigned. Configure a key for stronger protection."
    }

    Write-Step "Validating latest.json and the installer"
    Push-Location $AppRoot
    try {
        $validateArgs = @(
            (Join-Path $ScriptRoot "validate_manifest.py"),
            $ManifestPath,
            "--channel", $Channel,
            "--installer", $VersionedInstaller
        )
        if (-not $ManifestPublicKey) { $validateArgs += "--allow-unsigned" }
        & $Python @validateArgs
        if ($LASTEXITCODE -ne 0) { Fail "Manifest validation failed; latest.json was not published." }
    }
    finally {
        Pop-Location
    }
}
catch {
    [System.IO.File]::WriteAllText($ManifestPath, $manifestBackup, $utf8NoBom)
    Write-Warning "Restored the previous latest.json because the release was not valid."
    throw
}

Write-Host ""
Write-Host "Local release package is ready." -ForegroundColor Green
Write-Host "  Installer: $VersionedInstaller"
Write-Host "  Manifest : $ManifestPath"
Write-Host "  URL      : $downloadUrl"

if (-not $Publish) {
    Write-Host ""
    Write-Host "Dry run only. Re-run with -Publish (and optionally -PushManifest) to publish." -ForegroundColor Yellow
    exit 0
}

# ------------------------------------------------------------------ publish
Write-Step "Publishing the GitHub Release"
$releaseView = & gh release view $Tag --repo "$Owner/$Repo" --json assets 2>$null
if ($LASTEXITCODE -eq 0) {
    $assets = @(($releaseView | ConvertFrom-Json).assets)
    if ($assets.name -contains $VersionedName) {
        Fail "Release asset $VersionedName already exists on $Tag. Nothing was overwritten."
    }
    & gh release upload $Tag $VersionedInstaller --repo "$Owner/$Repo"
    if ($LASTEXITCODE -ne 0) { Fail "gh release upload failed." }
}
else {
    $createArgs = @(
        "release", "create", $Tag, $VersionedInstaller,
        "--repo", "$Owner/$Repo",
        "--title", "IDM $Version",
        "--notes", ($Notes -join "`n")
    )
    if ($Channel -eq "beta") { $createArgs += "--prerelease" }
    & gh @createArgs
    if ($LASTEXITCODE -ne 0) { Fail "gh release create failed." }
}
Write-Host "Release asset uploaded: $downloadUrl"

if ($PushManifest) {
    Write-Step "Committing and pushing latest.json"
    if (-not (Test-Path -LiteralPath (Join-Path $ManifestRepoPath ".git") -PathType Container)) {
        Fail "$ManifestRepoPath is not a git repository; push latest.json manually."
    }
    & git -C $ManifestRepoPath add latest.json
    if ($LASTEXITCODE -ne 0) { Fail "git add failed." }
    & git -C $ManifestRepoPath commit -m "Release IDM $Version ($Channel)"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Nothing to commit; latest.json may already be published."
    }
    else {
        & git -C $ManifestRepoPath push
        if ($LASTEXITCODE -ne 0) { Fail "git push failed. The release asset exists but the manifest was not published." }
    }
}

Write-Host ""
Write-Host "Release $Tag published." -ForegroundColor Green
Write-Host "Verify the public manifest with:"
Write-Host "  curl.exe -fsSL https://raw.githubusercontent.com/$Owner/$Repo/main/latest.json"
Write-Host "Then run Help > Check for Updates in the previous IDM version."
