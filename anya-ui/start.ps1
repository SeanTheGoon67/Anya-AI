# start.ps1 — desktop launcher for Anya's own UI.
#
# Why this exists: the old "llama-ui" shortcut was a bare Brave web link, so it
# opened http://127.0.0.1:8090 even when nothing was listening -> "server
# unavailable". This one waits until the UI actually answers before showing a
# window, and reuses a UI that is already running instead of starting a second.
#
# It does NOT start the model itself — anya_ui.py owns that, and remembers the
# power profile you picked last time.
#
#   Run hidden: powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File start.ps1

param(
    [switch]$Headless,          # start the UI but open no window / show no dialogs
    [int]$TimeoutSec = 180
)

$ErrorActionPreference = 'Stop'

$uiPort = 8091
$url    = "http://127.0.0.1:$uiPort"
$brave  = 'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe'
$python = 'S:\envs\ai\Scripts\python.exe'
$app    = Join-Path $PSScriptRoot 'anya_ui.py'
$logDir = 'S:\tools\logs'

function Test-UiUp {
    # Raw TCP probe: an order of magnitude faster than Invoke-WebRequest, which
    # has to load a lot of assemblies on first use.
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async  = $client.BeginConnect('127.0.0.1', $uiPort, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(600)) { $client.Close(); return $false }
        $ok = $client.Connected
        $client.Close()
        return $ok
    } catch { return $false }
}

function Open-Anya {
    if ($Headless) { return }
    # App window (no tabs / address bar) when Brave is available, else the default browser.
    if (Test-Path $brave) {
        Start-Process -FilePath $brave -ArgumentList "--app=$url"
    } else {
        Start-Process $url
    }
}

try {
    # 1. Already up? Just show it. Instant.
    if (Test-UiUp) { Open-Anya; exit 0 }

    if (-not (Test-Path $python)) { throw "Python not found at $python" }
    if (-not (Test-Path $app))    { throw "anya_ui.py not found at $app" }
    New-Item -ItemType Directory -Force $logDir | Out-Null

    # 2. Start the UI detached (it keeps running after this script exits).
    Start-Process -FilePath $python `
        -ArgumentList "`"$app`"", '--no-open' `
        -WorkingDirectory $PSScriptRoot `
        -WindowStyle Hidden

    # 3. Wait for the UI to answer, then open the window.
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-UiUp) { Open-Anya; exit 0 }
        Start-Sleep -Milliseconds 700
    }
    throw "Anya's UI did not come up within $TimeoutSec seconds"

} catch {
    # Only ever reached on real failure — the happy path opens the window and exits.
    $msg = "Anya could not start.`n`n$($_.Exception.Message)`n`nCheck $logDir"
    if ($Headless) {
        Write-Host "Anya failed: $($_.Exception.Message)"
    } else {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [void][System.Windows.Forms.MessageBox]::Show($msg, 'Anya', 'OK', 'Error')
        } catch {
            Write-Host "Anya failed: $($_.Exception.Message)"
        }
    }
    exit 1
}
