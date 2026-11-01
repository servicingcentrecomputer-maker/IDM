<#
.SYNOPSIS
    Builds IDM.exe, IDM_NativeHost.exe, IDM_Updater.exe, the browser
    extension packages and IDM-Setup-<version>.exe.

.DESCRIPTION
    Creates or reuses .venv, installs runtime and build dependencies, validates
    Python syntax, runs the test suite, cleans only generated build output,
    runs PyInstaller and Inno Setup, and verifies the final artifacts.

    The script never touches source files, %APPDATA%\IDM Download Manager or
    user downloads.

.PARAMETER Python
    Full path to a 64-bit Python interpreter used to create .venv.

.PARAMETER InnoSetupPath
    ISCC.exe or the Inno Setup installation directory.

.PARAMETER Force
    Replace an existing dist-installer\IDM-Setup-<version>.exe without prompting.

.PARAMETER RecreateVenv
    Delete and recreate .venv before installing dependencies.

.PARAMETER RegenerateAssets
    Regenerate assets\logo\idm.ico and the Inno Setup wizard images.

.PARAMETER SkipTests
    Skip pytest (not recommended for release builds).

.PARAMETER SkipInstaller
    Build only IDM.exe and skip Inno Setup.

.PARAMETER Package
    Assemble release\IDM-<version>-win64 and its ZIP after a successful build.
    When -SkipInstaller is used, the package contains the portable build only.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1 -Force -Package

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1 -SkipTests -SkipInstaller -Package
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$InnoSetupPath = "",
    [switch]$Force,
    [switch]$RecreateVenv,
    [switch]$RegenerateAssets,
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$Package
)

$ErrorActionPreference = "Stop"
$Root = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$BuildWorkDir = Join-Path $Root "build\IDM"
$BuildUpdaterWorkDir = Join-Path $Root "build\IDM_Updater"
$BuildNativeHostWorkDir = Join-Path $Root "build\IDM_NativeHost"
$DistAppDir = Join-Path $Root "dist\IDM"
$DistUpdaterExe = Join-Path $Root "dist\IDM_Updater.exe"
$DistNativeHostExe = Join-Path $Root "dist\IDM_NativeHost.exe"
$StagedUpdaterExe = Join-Path $DistAppDir "IDM_Updater.exe"
$StagedNativeHostExe = Join-Path $DistAppDir "IDM_NativeHost.exe"
$DistExtensionsDir = Join-Path $Root "dist-extensions"
$DistInstallerDir = Join-Path $Root "dist-installer"
$InstallerPath = $null

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Description
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Test-PythonCandidate {
    param([string]$Executable)
    if (-not $Executable) { return $false }
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    try {
        $result = & $Executable -c "import sys, struct; print(sys.executable); assert struct.calcsize('P') == 8" 2>$null
        return ($LASTEXITCODE -eq 0 -and $result)
    }
    catch {
        return $false
    }
}

function Find-BasePython {
    if ($Python) {
        if (Test-PythonCandidate $Python) { return (Resolve-Path -LiteralPath $Python).Path }
        throw "The interpreter passed with -Python is missing, not 64-bit, or not runnable: $Python"
    }
    if ($env:IDM_PYTHON) {
        if (Test-PythonCandidate $env:IDM_PYTHON) { return (Resolve-Path -LiteralPath $env:IDM_PYTHON).Path }
        throw "IDM_PYTHON is set but does not point to a usable 64-bit Python: $env:IDM_PYTHON"
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @("-3.12", "-3.13", "-3.11", "-3.14", "-3")) {
            try {
                $candidate = & py.exe $version -c "import sys, struct; assert struct.calcsize('P') == 8; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $candidate) {
                    return $candidate.Trim()
                }
            }
            catch {
                continue
            }
        }
    }

    $known = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe")
    )
    foreach ($candidate in $known) {
        if (Test-PythonCandidate $candidate) { return $candidate }
    }

    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and (Test-PythonCandidate $command.Source)) {
        return $command.Source
    }

    throw "No 64-bit Python 3.11+ installation was found. Install Python from python.org and rerun, or pass -Python <path>."
}

function Remove-GeneratedDirectory {
    param([string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $prefix = $Root.TrimEnd('\') + '\'
    if (-not $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete a path outside the project: $full"
    }
    if (Test-Path -LiteralPath $full) {
        Remove-Item -LiteralPath $full -Recurse -Force
    }
}

function Find-ISCC {
    if ($InnoSetupPath) {
        if (Test-Path -LiteralPath $InnoSetupPath -PathType Leaf) {
            return (Resolve-Path -LiteralPath $InnoSetupPath).Path
        }
        $explicit = Join-Path $InnoSetupPath "ISCC.exe"
        if (Test-Path -LiteralPath $explicit -PathType Leaf) {
            return (Resolve-Path -LiteralPath $explicit).Path
        }
        throw "ISCC.exe was not found at -InnoSetupPath '$InnoSetupPath'."
    }

    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA "Programs"))
    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($root in $roots) {
        if (-not $root) { continue }
        $candidates.Add((Join-Path $root "Inno Setup 7\ISCC.exe"))
        $candidates.Add((Join-Path $root "Inno Setup 6\ISCC.exe"))
        if (Test-Path -LiteralPath $root) {
            Get-ChildItem -LiteralPath $root -Directory -Filter "Inno Setup*" -ErrorAction SilentlyContinue |
                ForEach-Object { $candidates.Add((Join-Path $_.FullName "ISCC.exe")) }
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "Inno Setup was not found. Install Inno Setup 6.3+ or 7.x, or pass -InnoSetupPath <ISCC.exe or install dir>."
}

Write-Host "IDM Windows build" -ForegroundColor Green
Write-Host "Project: $Root"

# ---------------------------------------------------------------- environment
Write-Step "Preparing the Python virtual environment"
if ($RecreateVenv -and (Test-Path -LiteralPath $VenvDir)) {
    Write-Host "Removing the existing .venv..."
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    $basePython = Find-BasePython
    Write-Host "Creating .venv with $basePython"
    Invoke-Checked $basePython @("-m", "venv", $VenvDir) "Creating the virtual environment"
}
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    throw "The virtual environment was not created at $VenvPython."
}

$activateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
if (Test-Path -LiteralPath $activateScript -PathType Leaf) {
    try {
        . $activateScript
    }
    catch {
        Write-Warning "Activate.ps1 could not be loaded; using $VenvPython directly."
    }
}
$env:VIRTUAL_ENV = $VenvDir
$env:PATH = (Join-Path $VenvDir "Scripts") + ";" + $env:PATH
$PythonExe = $VenvPython

$pythonVersion = (& $PythonExe -c "import sys; print(sys.version.split()[0])").Trim()
Write-Host "Using Python $pythonVersion ($PythonExe)"

# ---------------------------------------------------------------- dependencies
Write-Step "Installing build dependencies"
Invoke-Checked $PythonExe @("-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check") "Upgrading pip"
Invoke-Checked $PythonExe @(
    "-m", "pip", "install", "--disable-pip-version-check",
    "-r", (Join-Path $Root "requirements.txt"),
    "-r", (Join-Path $Root "requirements-build.txt")
) "Installing requirements"

# ---------------------------------------------------------------- versions
Write-Step "Checking version consistency"
$versionSource = Get-Content -LiteralPath (Join-Path $Root "idm\version.py") -Raw
$versionMatch = [regex]::Match($versionSource, 'CURRENT_VERSION\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read CURRENT_VERSION from idm\version.py."
}
$AppVersion = $versionMatch.Groups[1].Value
if ($AppVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Release builds require a stable MAJOR.MINOR.PATCH version; found '$AppVersion'."
}
$versionParts = $AppVersion.Split('.')
$numericVersion = "$AppVersion.0"
$InstallerPath = Join-Path $DistInstallerDir "IDM-Setup-$AppVersion.exe"

foreach ($infoFile in @("version_info.txt", "version_info_updater.txt", "version_info_native_host.txt")) {
    $info = Get-Content -LiteralPath (Join-Path $Root $infoFile) -Raw
    $fixed = [regex]::Match($info, 'filevers=\((\d+),\s*(\d+),\s*(\d+)')
    if (-not $fixed.Success) {
        throw "$infoFile does not declare a numeric filevers tuple."
    }
    if ($fixed.Groups[1].Value -ne $versionParts[0] -or
        $fixed.Groups[2].Value -ne $versionParts[1] -or
        $fixed.Groups[3].Value -ne $versionParts[2]) {
        throw "$infoFile filevers does not match CURRENT_VERSION $AppVersion."
    }
}

foreach ($browser in @("chrome", "edge", "firefox")) {
    $manifestFile = Join-Path $Root "extensions\$browser\manifest.json"
    if (-not (Test-Path -LiteralPath $manifestFile -PathType Leaf)) {
        throw "extensions\$browser\manifest.json is missing."
    }
    $extensionVersion = (Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json).version
    if ($extensionVersion -ne $AppVersion) {
        throw "extensions\$browser\manifest.json version $extensionVersion does not match CURRENT_VERSION $AppVersion."
    }
}

$videoAssistantDir = Join-Path $Root "BrowserExtension\IDMVideoAssistant"
$videoManifestFile = Join-Path $videoAssistantDir "manifest.json"
if (-not (Test-Path -LiteralPath $videoManifestFile -PathType Leaf)) {
    throw "BrowserExtension\IDMVideoAssistant\manifest.json is missing."
}
$videoVersion = (Get-Content -LiteralPath $videoManifestFile -Raw | ConvertFrom-Json).version
if ($videoVersion -ne $AppVersion) {
    throw "BrowserExtension\IDMVideoAssistant\manifest.json version $videoVersion does not match CURRENT_VERSION $AppVersion."
}
foreach ($required in @(
    "background.js", "content.js", "media-detector.js", "native-messaging.js",
    "popup.html", "popup.css", "popup.js",
    "icons\icon16.png", "icons\icon32.png", "icons\icon48.png", "icons\icon128.png"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $videoAssistantDir $required) -PathType Leaf)) {
        throw "BrowserExtension\IDMVideoAssistant\$required is missing."
    }
}

$iss = Get-Content -LiteralPath (Join-Path $Root "installer\IDM_Setup.iss") -Raw
if (-not $iss.Contains("#define MyAppVersion `"$AppVersion`"")) {
    throw "installer\IDM_Setup.iss does not declare MyAppVersion `"$AppVersion`"."
}
if (-not $iss.Contains("VersionInfoVersion=$numericVersion")) {
    throw "installer\IDM_Setup.iss does not declare VersionInfoVersion=$numericVersion."
}
Write-Host "Application version: $AppVersion"

if ($RegenerateAssets) {
    Write-Step "Regenerating branding assets"
    Invoke-Checked $PythonExe @((Join-Path $Root "tools\generate_branding_assets.py")) "Generating branding assets"
}

# ---------------------------------------------------------------- validation
Write-Step "Validating Python syntax"
Invoke-Checked $PythonExe @("-m", "compileall", "-q", "main.py", "native_host_main.py", "updater_main.py", "idm", "integrations", "downloads", "tests", "tools", "scripts") "compileall"
$previousQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
try {
    Invoke-Checked $PythonExe @("-c", "import main; print('main.py imports successfully')") "Importing main.py"
    Invoke-Checked $PythonExe @("-c", "import updater_main, idm.updater.updater; print('updater imports successfully')") "Importing updater_main.py"
    Invoke-Checked $PythonExe @("-c", "import native_host_main, integrations.native_host; print('native host imports successfully')") "Importing native_host_main.py"
}
finally {
    if ($null -eq $previousQtPlatform) {
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    }
    else {
        $env:QT_QPA_PLATFORM = $previousQtPlatform
    }
}

# ---------------------------------------------------------------- tests
if (-not $SkipTests) {
    Write-Step "Running the automated test suite"
    $previousQtPlatform = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = "offscreen"
    try {
        Invoke-Checked $PythonExe @("-m", "pytest", "tests", "-q") "pytest"
    }
    finally {
        if ($null -eq $previousQtPlatform) {
            Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        }
        else {
            $env:QT_QPA_PLATFORM = $previousQtPlatform
        }
    }
}
else {
    Write-Warning "Tests were skipped. Do not publish this build as production-ready."
}

# ---------------------------------------------------------------- cleanup
Write-Step "Cleaning generated build output"
if ((-not $SkipInstaller) -and (Test-Path -LiteralPath $InstallerPath) -and (-not $Force)) {
    if ([Console]::IsInputRedirected) {
        throw "An existing installer exists at $InstallerPath. Rerun with -Force to replace it."
    }
    $answer = Read-Host "An existing installer will be replaced. Continue? [y/N]"
    if ($answer -notmatch '^(?i:y|yes)$') {
        throw "Build aborted; the existing installer was kept."
    }
}
Remove-GeneratedDirectory $BuildWorkDir
Remove-GeneratedDirectory $BuildUpdaterWorkDir
Remove-GeneratedDirectory $BuildNativeHostWorkDir
Remove-GeneratedDirectory $DistAppDir
Remove-GeneratedDirectory $DistExtensionsDir
if (Test-Path -LiteralPath $DistUpdaterExe -PathType Leaf) {
    Remove-Item -LiteralPath $DistUpdaterExe -Force
}
if (Test-Path -LiteralPath $DistNativeHostExe -PathType Leaf) {
    Remove-Item -LiteralPath $DistNativeHostExe -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $Root "build"), (Join-Path $Root "dist") | Out-Null
Write-Host "Removed build\IDM, build\IDM_Updater, build\IDM_NativeHost, dist\IDM, dist\IDM_Updater.exe,"
Write-Host "dist\IDM_NativeHost.exe and dist-extensions only."

# ---------------------------------------------------------------- extensions
Write-Step "Validating and packaging browser extensions"
Invoke-Checked $PythonExe @((Join-Path $Root "scripts\package_extensions.py")) "Packaging browser extensions"
Invoke-Checked $PythonExe @((Join-Path $Root "scripts\package_video_assistant.py")) "Packaging IDM Video Assistant"
foreach ($extensionPackage in @("IDM_Chrome_Extension.zip", "IDM_Edge_Extension.zip", "IDM_Firefox_Extension.zip")) {
    $packagePath = Join-Path $DistExtensionsDir $extensionPackage
    if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) {
        throw "The extension package was not created: $packagePath"
    }
}

# ---------------------------------------------------------------- PyInstaller
Write-Step "Building IDM.exe, IDM_Updater.exe and IDM_NativeHost.exe with PyInstaller"
Push-Location $Root
try {
    Invoke-Checked $PythonExe @(
        "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", (Join-Path $Root "dist"),
        "--workpath", (Join-Path $Root "build"),
        (Join-Path $Root "IDM.spec")
    ) "PyInstaller"
}
finally {
    Pop-Location
}

$exePath = Join-Path $DistAppDir "IDM.exe"
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "PyInstaller finished but $exePath does not exist."
}
$bundledLogo = Join-Path $DistAppDir "_internal\assets\logo.svg"
if (-not (Test-Path -LiteralPath $bundledLogo -PathType Leaf)) {
    throw "The application assets were not bundled (expected $bundledLogo)."
}
$platformPlugin = Get-ChildItem -LiteralPath $DistAppDir -Recurse -Filter "qwindows.dll" -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $platformPlugin) {
    throw "The Qt Windows platform plugin (qwindows.dll) is missing from the bundle."
}
if (-not (Test-Path -LiteralPath $DistUpdaterExe -PathType Leaf)) {
    throw "PyInstaller finished but $DistUpdaterExe does not exist."
}
$updaterLength = (Get-Item -LiteralPath $DistUpdaterExe).Length
if ($updaterLength -lt 1MB) {
    throw "IDM_Updater.exe is unexpectedly small ($updaterLength bytes)."
}
Copy-Item -LiteralPath $DistUpdaterExe -Destination $StagedUpdaterExe -Force
if (-not (Test-Path -LiteralPath $StagedUpdaterExe -PathType Leaf)) {
    throw "The updater was not staged into $DistAppDir."
}
if (-not (Test-Path -LiteralPath $DistNativeHostExe -PathType Leaf)) {
    throw "PyInstaller finished but $DistNativeHostExe does not exist."
}
$nativeHostLength = (Get-Item -LiteralPath $DistNativeHostExe).Length
if ($nativeHostLength -lt 1MB) {
    throw "IDM_NativeHost.exe is unexpectedly small ($nativeHostLength bytes)."
}
Copy-Item -LiteralPath $DistNativeHostExe -Destination $StagedNativeHostExe -Force
if (-not (Test-Path -LiteralPath $StagedNativeHostExe -PathType Leaf)) {
    throw "The native host was not staged into $DistAppDir."
}
if (-not (Test-Path -LiteralPath (Join-Path $DistAppDir "IDM_NativeHost.exe") -PathType Leaf)) {
    throw "The installer payload is missing IDM_NativeHost.exe."
}
Write-Host "Built: $exePath"
Write-Host "Built: $StagedUpdaterExe"
Write-Host "Built: $StagedNativeHostExe"

if ($SkipInstaller) {
    Write-Host ""
    Write-Host "Installer build skipped." -ForegroundColor Yellow
    Write-Host "Executable  : $exePath" -ForegroundColor Green
    Write-Host "Updater     : $StagedUpdaterExe" -ForegroundColor Green
    Write-Host "Native host : $StagedNativeHostExe" -ForegroundColor Green
    Write-Host "Extensions  : $DistExtensionsDir" -ForegroundColor Green
    if ($Package) {
        Write-Step "Assembling the release package (portable only)"
        Invoke-Checked $PythonExe @(
            (Join-Path $Root "scripts\package_release.py"),
            "--no-installer"
        ) "Release packaging"
    }
    exit 0
}

# ---------------------------------------------------------------- Inno Setup
Write-Step "Building IDM-Setup-$AppVersion.exe with Inno Setup"
$iscc = Find-ISCC
Write-Host "Using ISCC: $iscc"
New-Item -ItemType Directory -Force -Path $DistInstallerDir | Out-Null
Invoke-Checked $iscc @("/Qp", (Join-Path $Root "installer\IDM_Setup.iss")) "Inno Setup compilation"

if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Inno Setup finished but $InstallerPath does not exist."
}

$exeHash = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash
$updaterHash = (Get-FileHash -LiteralPath $StagedUpdaterExe -Algorithm SHA256).Hash
$nativeHostHash = (Get-FileHash -LiteralPath $StagedNativeHostExe -Algorithm SHA256).Hash
$setupHash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash
$exeSize = [math]::Round((Get-Item -LiteralPath $exePath).Length / 1MB, 2)
$updaterSize = [math]::Round((Get-Item -LiteralPath $StagedUpdaterExe).Length / 1MB, 2)
$nativeHostSize = [math]::Round((Get-Item -LiteralPath $StagedNativeHostExe).Length / 1MB, 2)
$setupSize = [math]::Round((Get-Item -LiteralPath $InstallerPath).Length / 1MB, 2)

Write-Host ""
Write-Host "Build complete" -ForegroundColor Green
Write-Host "Executable  : $exePath ($exeSize MB)"
Write-Host "  SHA256    : $exeHash"
Write-Host "Updater     : $StagedUpdaterExe ($updaterSize MB)"
Write-Host "  SHA256    : $updaterHash"
Write-Host "Native host : $StagedNativeHostExe ($nativeHostSize MB)"
Write-Host "  SHA256    : $nativeHostHash"
Write-Host "Installer   : $InstallerPath ($setupSize MB)"
Write-Host "  SHA256    : $setupHash"
Write-Host "Extensions  : $DistExtensionsDir"
Write-Host ""

if ($Package) {
    Write-Step "Assembling the release package"
    Invoke-Checked $PythonExe @((Join-Path $Root "scripts\package_release.py")) "Release packaging"
}

Write-Host "The installer is unsigned. See PACKAGING.md before distributing it."
