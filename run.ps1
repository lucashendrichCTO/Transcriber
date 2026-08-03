<#
  Windows equivalent of run.sh — starts Transcriber in browser mode.

  Usage:
      powershell -ExecutionPolicy Bypass -File .\run.ps1
      powershell -ExecutionPolicy Bypass -File .\run.ps1 -Verbose

  If double-clicking or "Run with PowerShell" refuses to run this file, it's
  Windows' default script execution policy blocking unsigned scripts — use
  the -ExecutionPolicy Bypass form above, which only affects this one run.
#>

param(
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

# Set TRANSCRIBER_PORT to run a second instance (e.g. a beta test build)
# without colliding with one already running on 8765.
$Port = if ($env:TRANSCRIBER_PORT) { $env:TRANSCRIBER_PORT } else { "8765" }
$Url = "http://127.0.0.1:$Port"

# Find Python 3.9+
$PythonCmd = $null
foreach ($candidate in @("python", "python3", "py")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        $PythonCmd = $candidate
        break
    }
}

if (-not $PythonCmd) {
    Write-Host "Python 3 not found. Install it from https://www.python.org/downloads/ (check 'Add python.exe to PATH' during install)."
    exit 1
}

# Create venv if missing
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    & $PythonCmd -m venv .venv
}

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# Install / upgrade deps quietly
Write-Host "Checking dependencies..."
& $VenvPython -m pip install -q -r requirements.txt

# Free the port if a stale server is still holding it
$stale = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
if ($stale) {
    Write-Host "Port $Port was in use by PID(s): $($stale -join ', ') - stopping them..."
    foreach ($processId in $stale) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

Write-Host ""
Write-Host "------------------------------------------------------------"
Write-Host "  Transcriber is starting."
Write-Host ""
Write-Host "  Open this URL in your browser (note the port :$Port):"
Write-Host ""
Write-Host "      $Url"
Write-Host ""
if ($Verbose) {
    Write-Host "  Verbose logging is ON."
    Write-Host ""
}
Write-Host "  Press Ctrl+C to stop the server."
Write-Host "  First transcription downloads the Whisper model (~142 MB)."
Write-Host "------------------------------------------------------------"
Write-Host ""

# Auto-open the browser to the correct URL (5s delay so the server is up)
Start-Job -ScriptBlock {
    param($Url)
    Start-Sleep -Seconds 5
    Start-Process $Url
} -ArgumentList $Url | Out-Null

if ($Verbose) {
    $env:VERBOSE = "1"
    & $VenvPython -m uvicorn app:app --host 127.0.0.1 --port $Port --log-level info
} else {
    & $VenvPython -m uvicorn app:app --host 127.0.0.1 --port $Port --log-level warning
}
