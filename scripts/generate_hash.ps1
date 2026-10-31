#Requires -Version 5.1
<#
.SYNOPSIS
    Calculates the SHA-256 of an IDM installer.

.DESCRIPTION
    Prints the lowercase hexadecimal SHA-256 used by latest.json.  This script
    never edits the manifest; copy the value into latest.json and then run
    scripts\validate_manifest.py --installer to cross-check both.

.PARAMETER Path
    Installer file, normally dist-installer\IDM_Setup.exe.

.PARAMETER OutFile
    Optional path for a small text file containing "<hash>  <file name>".

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\generate_hash.ps1 -Path .\dist-installer\IDM_Setup.exe
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"

$resolved = [System.IO.Path]::GetFullPath($Path)
if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    throw "Installer not found: $resolved"
}

$file = Get-Item -LiteralPath $resolved
$hash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host "File  : $($file.FullName)"
Write-Host "Size  : $($file.Length) bytes"
Write-Host "SHA256: $hash"

if ($OutFile) {
    $outPath = [System.IO.Path]::GetFullPath($OutFile)
    "$hash  $($file.Name)" | Set-Content -LiteralPath $outPath -Encoding ASCII
    Write-Host "Written: $outPath"
}
