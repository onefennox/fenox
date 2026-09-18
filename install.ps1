# Fenox Mobile installer for Windows
#
#   irm https://raw.githubusercontent.com/onefennox/fenox-mobile/main/install.ps1 | iex
#
# Downloads the prebuilt release binary, verifies its SHA-256 against the
# published checksum, and installs it to %LOCALAPPDATA%\Programs\fenox.
# Nothing is installed if the checksum cannot be found or does not match.
[CmdletBinding()]
param(
    [string]$Version,   # skip the "latest" lookup and install a specific tag, e.g. v1.0.0
    [switch]$NoPath     # do not touch the user PATH
)

$ErrorActionPreference = 'Stop'
$Repo       = 'onefennox/fenox-mobile'
$Asset      = 'fenox-mobile-windows-x86_64.exe'
$InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\fenox'
$ExeName    = 'fenox-mobile.exe'

function Get-LatestTag {
    $api = "https://api.github.com/repos/$Repo/releases/latest"
    try {
        $resp = Invoke-RestMethod -Uri $api -Headers @{ 'User-Agent' = 'fenox-installer' } -TimeoutSec 30
        return $resp.tag_name
    } catch {
        throw "Could not determine the latest release for $Repo. $($_.Exception.Message)"
    }
}

function Get-ExpectedHash {
    param([string]$Base, [string]$Name)
    # Prefer the aggregate SHA256SUMS; fall back to the per-asset .sha256 file.
    try {
        $text = (Invoke-WebRequest -Uri "$Base/SHA256SUMS" -UseBasicParsing -TimeoutSec 30).Content
        foreach ($line in ($text -split "`n")) {
            $parts = @($line -split '\s+' | Where-Object { $_ })
            if ($parts.Count -ge 2 -and $parts[1].TrimStart('*') -eq $Name) { return $parts[0].ToLower() }
        }
    } catch { }
    try {
        $text = (Invoke-WebRequest -Uri "$Base/$Name.sha256" -UseBasicParsing -TimeoutSec 30).Content
        $first = @($text -split '\s+' | Where-Object { $_ })[0]
        if ($first -and $first.Length -eq 64) { return $first.ToLower() }
    } catch { }
    return $null
}

Write-Host ''
Write-Host 'Fenox Mobile installer' -ForegroundColor Cyan

$tag = if ($Version) { $Version } else { Get-LatestTag }
if (-not $tag) { throw "No release found for $Repo." }
$tag = $tag.Trim()
$version = $tag.TrimStart('v')
$base = "https://github.com/$Repo/releases/download/$tag"
Write-Host "Latest release: $tag" -ForegroundColor Cyan

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('fenox-' + [guid]::NewGuid().ToString('N') + '.exe')
try {
    Write-Host "Downloading $Asset ..."
    Invoke-WebRequest -Uri "$base/$Asset" -OutFile $tmp -UseBasicParsing -TimeoutSec 300

    $expected = Get-ExpectedHash -Base $base -Name $Asset
    if (-not $expected) { throw "No checksum published for $Asset - refusing to install." }

    $actual = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) {
        throw "Checksum mismatch - refusing to install.`n  expected: $expected`n  actual:   $actual"
    }
    Write-Host 'Checksum verified (SHA-256).' -ForegroundColor Green

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $dest = Join-Path $InstallDir $ExeName
    if (Test-Path $dest) {
        $backup = "$dest.bak-" + (Get-Date -Format 'yyyyMMddHHmmss')
        Copy-Item $dest $backup -Force
        Write-Host "Backed up the previous install to $backup"
    }
    Move-Item -Force $tmp $dest

    if (-not $NoPath) {
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        if (-not $userPath) { $userPath = '' }
        if ($userPath -notlike "*$InstallDir*") {
            $sep = if ($userPath -and -not $userPath.EndsWith(';')) { ';' } else { '' }
            [Environment]::SetEnvironmentVariable('Path', "$userPath$sep$InstallDir", 'User')
            Write-Host "Added $InstallDir to your user PATH - open a new terminal to pick it up." -ForegroundColor Green
        }
        $env:Path = "$env:Path;$InstallDir"
    }

    Write-Host ''
    Write-Host "fenox-mobile v$version installed -> $dest" -ForegroundColor Green
    Write-Host "Next: 'fenox-mobile init' for one-time setup, then 'fenox-mobile doctor'."
} finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}
