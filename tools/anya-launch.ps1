# anya-launch.ps1 — desktop launcher for Anya's browser UI.
#
#   The point of this script: never open the page until the server is actually
#   ready. The old "llama-ui" desktop shortcut was just a Brave web-app link, so
#   it opened http://127.0.0.1:8090 even when nothing was listening -> "server
#   unavailable". This waits on /health first, and reuses a server that is
#   already up instead of restarting it.
#
#   Run hidden:  powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File anya-launch.ps1

param(
    [switch]$Headless,    # bring the server up but open no window and show no
                          # dialogs (for testing / scheduled tasks)
    [int]$TimeoutSec = 180
)

$ErrorActionPreference = 'Stop'

$root    = Split-Path $PSScriptRoot -Parent        # project folder
$exe     = 'S:\tools\llama-vulkan\llama-server.exe'
$gguf    = Join-Path $root 'models\anya-f16.gguf'
$logDir  = 'S:\tools\logs'
$port    = 8090
$url     = "http://127.0.0.1:$port"
$health  = "$url/health"
$brave   = 'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe'

function Test-AnyaUp {
    try {
        $r = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Open-Anya {
    if ($Headless) { return }
    # App window (no tabs/address bar) if Brave is there, else the default browser.
    if (Test-Path $brave) {
        Start-Process -FilePath $brave -ArgumentList "--app=$url"
    } else {
        Start-Process $url
    }
}

try {
    # 1. Already running and healthy -> just open it. Instant.
    if (Test-AnyaUp) { Open-Anya; exit 0 }

    # 2. Free VRAM that Ollama may be holding for Anya (8 GB is shared).
    $ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $ollama) { try { & $ollama stop anya 2>$null | Out-Null } catch {} }

    # 3. Start (or restart) llama-server on the Anya GGUF.
    if (-not (Test-Path $exe))  { throw "llama-server.exe not found at $exe" }
    if (-not (Test-Path $gguf)) { throw "model not found at $gguf" }
    New-Item -ItemType Directory -Force $logDir | Out-Null

    Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 1

    Start-Process -FilePath $exe `
        -ArgumentList "-m `"$gguf`" --host 127.0.0.1 --port $port -c 8192 -ngl 99" `
        -RedirectStandardOutput (Join-Path $logDir 'llama-server.out.log') `
        -RedirectStandardError  (Join-Path $logDir 'llama-server.err.log') `
        -WindowStyle Hidden

    # 4. Wait for /health to return 200 (503 while the model loads).
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-AnyaUp) { Open-Anya; exit 0 }
        Start-Sleep -Milliseconds 1500
    }
    throw "server did not become ready within $TimeoutSec seconds"

} catch {
    # Only ever shown on real failure - the happy path opens the browser and exits.
    if ($Headless) {
        Write-Host "Anya failed: $($_.Exception.Message)"
    } else {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [void][System.Windows.Forms.MessageBox]::Show(
                "Anya could not start.`n`n$($_.Exception.Message)`n`nCheck $logDir\llama-server.err.log",
                "Anya", 'OK', 'Error')
        } catch {
            Write-Host "Anya failed: $($_.Exception.Message)"
        }
    }
    exit 1
}
