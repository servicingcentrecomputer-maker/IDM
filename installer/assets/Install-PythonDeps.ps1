<#
  IDM Python runtime bootstrap.

  Ensures a Python 3.11 or newer interpreter that can already import the
  packages listed in requirements.txt is available for the current user.
  Detection order:

    1. an existing interpreter that can already import those packages
    2. an existing 3.11+ interpreter, into which requirements.txt is installed
    3. a silent per-user download and install of the python.org amd64
       installer, followed by step 2

  Exit codes (read by installer\IDM_Setup.iss):
     0  installed what was missing
    10  nothing to do, the runtime was already complete
    11  -CheckOnly: a required part is missing
    20  the download failed
    21  the downloaded installer was not signed by the Python Software Foundation
    22  the Python installer failed
    23  pip failed
    24  the runtime is still unusable after the bootstrap
    25  the script was called incorrectly
#>
[CmdletBinding()]
param(
    [string]$InstallerUrl = 'https://www.python.org/ftp/python/3.13.12/python-3.13.12-amd64.exe',
    [string]$ExpectedSha256 = '',
    [string]$RequirementsFile = '',
    [string]$LogPath = '',
    [string]$PyExe = '',
    [switch]$CheckOnly,
    [switch]$Force,
    [switch]$PrependPath
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

if (-not $LogPath) {
    $LogPath = Join-Path $env:TEMP 'IDM-PythonDeps.log'
}
$script:LogFile = $LogPath

function Write-Log {
    param([string]$Message)
    $line = ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
    Write-Host $line
    try {
        Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8
    } catch {
        # A missing log must never break the bootstrap.
    }
}

# Full check: 3.11+ interpreter that can already import everything listed in
# requirements.txt.
$ProbeRuntime = 'import sys,PySide6,requests,cryptography;sys.exit(0 if sys.version_info[:2]>=(3,11) else 41)'
# Version check only, used when the packages still have to be installed.
$ProbeVersion = 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,11) else 41)'

function Test-PythonExe {
    param([string]$Exe, [string]$Probe)
    if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
        return $false
    }
    try {
        & $Exe -c $Probe 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-PythonExeCandidates {
    $paths = New-Object System.Collections.Generic.List[string]

    foreach ($hive in @('HKLM:\SOFTWARE\Python\PythonCore',
                        'HKCU:\SOFTWARE\Python\PythonCore',
                        'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore',
                        'HKCU:\SOFTWARE\WOW6432Node\Python\PythonCore')) {
        if (-not (Test-Path -LiteralPath $hive)) { continue }
        foreach ($verName in (Get-ChildItem -LiteralPath $hive -ErrorAction SilentlyContinue | ForEach-Object { $_.PSChildName })) {
            $installKey = Join-Path $hive ($verName + '\InstallPath')
            if (-not (Test-Path -LiteralPath $installKey)) { continue }
            $item = Get-ItemProperty -LiteralPath $installKey -ErrorAction SilentlyContinue
            if (-not $item) { continue }
            foreach ($name in @('(default)', 'Path')) {
                $prop = $item.PSObject.Properties[$name]
                if ($prop -and ($prop.Value -is [string]) -and $prop.Value.Trim()) {
                    $paths.Add((Join-Path $prop.Value.TrimEnd('\') 'python.exe'))
                }
            }
        }
    }

    $roots = New-Object System.Collections.Generic.List[string]
    foreach ($value in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:SystemDrive)) {
        if ($value -and (Test-Path -LiteralPath $value)) { $roots.Add($value.TrimEnd('\')) }
    }
    $layouts = @(
        (Join-Path 'Programs\Python' 'Python*'),
        (Join-Path 'Python' 'Python*'),
        'Python*'
    )
    foreach ($root in $roots) {
        foreach ($layout in $layouts) {
            $leaf = Split-Path $layout -Leaf
            $parent = if (Split-Path $layout -Parent) {
                Join-Path $root (Split-Path $layout -Parent)
            } else {
                $root
            }
            foreach ($dir in (Get-ChildItem -LiteralPath $parent -Directory -Filter $leaf -ErrorAction SilentlyContinue)) {
                $paths.Add((Join-Path $dir.FullName 'python.exe'))
            }
        }
    }
    # The Python install manager exposes a bare bin\python.exe alias.
    $paths.Add((Join-Path $env:LOCALAPPDATA 'Python\bin\python.exe'))

    # The py launcher knows about every registered interpreter, including the
    # ones installed by the newer Python install manager.
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            foreach ($line in (& $launcher.Source -0p 2>$null)) {
                $tail = ($line -split '\s+') | Where-Object { $_ } | Select-Object -Last 1
                if ($tail -and ($tail -match '(?i)python\.exe$')) { $paths.Add($tail) }
            }
        } catch {
            Write-Log 'The py launcher could not be queried.'
        }
    }

    $clean = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    foreach ($p in $paths) {
        if (-not $p) { continue }
        if ($p -match '(?i)\\WindowsApps\\') { continue }
        try {
            $resolved = (Resolve-Path -LiteralPath $p -ErrorAction Stop).Path
        } catch {
            continue
        }
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { continue }
        $key = $resolved.ToLowerInvariant()
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            $clean.Add($resolved)
        }
    }
    return $clean.ToArray()
}

function Find-Python {
    param([string]$Probe)
    foreach ($candidate in (Get-PythonExeCandidates)) {
        if (Test-PythonExe -Exe $candidate -Probe $Probe) {
            Write-Log ("Using interpreter: $candidate")
            return $candidate
        }
    }
    return $null
}

function Invoke-Download {
    param([string]$Url, [string]$Destination)

    # Windows PowerShell 5.1 does not enable TLS 1.2 by default.
    $protocol = [Net.ServicePointManager]::SecurityProtocol
    $tls12 = [Net.SecurityProtocolType]::Tls12
    $tls13 = 12288  # [Net.SecurityProtocolType]::Tls13 on recent Windows
    $enabled = $protocol
    if (([int]$enabled -band [int]$tls12) -eq 0) { $enabled = $enabled -bor $tls12 }
    try {
        [Net.ServicePointManager]::SecurityProtocol = $enabled
    } catch {
        Write-Log 'Could not adjust the TLS protocol list; using the system default.'
    }

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Write-Log ("Download attempt $attempt of 3 from $Url")
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -TimeoutSec 600
            if ((Get-Item -LiteralPath $Destination).Length -gt 0) { return $true }
        } catch {
            Write-Log ("Download failed: $($_.Exception.Message)")
            Start-Sleep -Seconds (2 * $attempt)
        }
    }
    return $false
}

function Test-DownloadedInstaller {
    param([string]$Path)

    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    Write-Log ("Authenticode status: $($signature.Status)")
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        Write-Log 'The downloaded installer is not a valid Authenticode signature.'
        return 21
    }
    $certificate = $signature.SignerCertificate
    $subject = if ($certificate) { $certificate.Subject } else { '' }
    if (-not $subject -or ($subject -notmatch 'Python Software Foundation')) {
        Write-Log "The installer is not signed by the Python Software Foundation: $subject"
        return 21
    }
    if ($ExpectedSha256) {
        $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
        if ($actual -ne $ExpectedSha256.ToUpperInvariant().Trim()) {
            Write-Log "SHA-256 mismatch. Expected $ExpectedSha256 but got $actual"
            return 21
        }
        Write-Log 'SHA-256 matches the pinned value.'
    }
    Write-Log "Signature verified for: $subject"
    return 0
}

function Install-PythonFromPythonOrg {
    param([string]$DownloadTarget)

    if (-not (Invoke-Download -Url $InstallerUrl -Destination $DownloadTarget)) {
        Write-Log "Could not download the Python installer from $InstallerUrl"
        return 20
    }
    $status = Test-DownloadedInstaller -Path $DownloadTarget
    if ($status -ne 0) {
        Remove-Item -LiteralPath $DownloadTarget -Force -ErrorAction SilentlyContinue
        return $status
    }

    $arguments = @(
        '/quiet',
        'InstallAllUsers=0',
        'Include_pip=1',
        'Include_launcher=1',
        'Include_test=0',
        'AssociateFiles=0',
        'Shortcuts=0',
        "PrependPath=$(if ($PrependPath) { '1' } else { '0' })"
    )
    Write-Log ("Running the Python installer: " + ($arguments -join ' '))
    try {
        $process = Start-Process -FilePath $DownloadTarget -ArgumentList $arguments -Wait -PassThru
    } catch {
        Write-Log "The Python installer could not be started: $($_.Exception.Message)"
        return 22
    }
    Write-Log "The Python installer exited with code $($process.ExitCode)"
    # 0 = installed, 101 = installed but a restart is needed for some parts.
    if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 101) {
        return 22
    }
    Remove-Item -LiteralPath $DownloadTarget -Force -ErrorAction SilentlyContinue
    return 0
}

function Install-Requirements {
    param([string]$PyExe)

    if (-not $RequirementsFile -or -not (Test-Path -LiteralPath $RequirementsFile -PathType Leaf)) {
        Write-Log "The requirements file was not provided or does not exist: $RequirementsFile"
        return 25
    }
    & $PyExe -m pip --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Log 'pip is unavailable; running ensurepip first.'
        & $PyExe -m ensurepip --upgrade 2>&1 | ForEach-Object { Write-Log "ensurepip: $_" }
    }
    Write-Log "Installing the packages listed in $RequirementsFile"
    & $PyExe -m pip install --disable-pip-version-check --no-input --no-warn-script-location `
        -r $RequirementsFile 2>&1 |
        ForEach-Object { Write-Log "pip: $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "pip exited with code $LASTEXITCODE."
        return 23
    }
    return 0
}

try {
    if ($CheckOnly -and $Force) {
        Write-Log '-CheckOnly and -Force cannot be combined.'
        exit 25
    }

    Write-Log '--- IDM Python runtime bootstrap ---'
    Write-Log "Log: $script:LogFile"

    if ($PyExe) {
        if (-not (Test-Path -LiteralPath $PyExe -PathType Leaf)) {
            Write-Log "-PyExe does not point at a file: $PyExe"
            exit 25
        }
        $interpreter = (Resolve-Path -LiteralPath $PyExe).Path
        Write-Log "Targeting the supplied interpreter: $interpreter"
    } else {
        $complete = Find-Python -Probe $ProbeRuntime
        if ($complete) {
            Write-Log 'Python 3.11+ already provides the packages from requirements.txt.'
            if ($CheckOnly) { exit 10 }
            if (-not $Force) { exit 10 }
            Write-Log '-Force was given; reinstalling the packages anyway.'
        } elseif ($CheckOnly) {
            Write-Log 'Missing: Python 3.11+ that can import the packages from requirements.txt.'
            exit 11
        } else {
            Write-Log 'Runtime not found; bootstrapping Python 3.11+ and requirements.txt.'
        }

        $interpreter = Find-Python -Probe $ProbeVersion
        if (-not $interpreter) {
            Write-Log 'No usable Python 3.11+ interpreter; downloading one.'
            $download = Join-Path $env:TEMP ('python-installer-' + [System.IO.Path]::GetRandomFileName() + '.exe')
            $result = Install-PythonFromPythonOrg -DownloadTarget $download
            if ($result -ne 0) { exit $result }
            $interpreter = Find-Python -Probe $ProbeVersion
            if (-not $interpreter) {
                Write-Log 'The Python installer finished but no interpreter could be located afterwards.'
                exit 24
            }
        }
    }

    $result = Install-Requirements -PyExe $interpreter
    if ($result -ne 0) { exit $result }

    if (-not (Test-PythonExe -Exe $interpreter -Probe $ProbeRuntime)) {
        Write-Log 'The packages were installed but the runtime check still fails.'
        exit 24
    }

    Write-Log 'Python runtime and the required packages are ready.'
    exit 0
} catch {
    Write-Log "Unexpected failure: $($_.Exception.Message)"
    exit 25
}
