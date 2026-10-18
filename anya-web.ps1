# anya-web.ps1 — run Anya in a web browser (llama.cpp chat UI).
#
#   Right-click -> Run with PowerShell, or double-click "Start Anya (browser).cmd"
#
# Starts llama-server with the Anya GGUF on the GPU (Vulkan) and opens the chat
# UI at http://127.0.0.1:8090 . Leave this window open while you chat.

$ErrorActionPreference = 'Stop'

$exe  = 'S:\tools\llama-vulkan\llama-server.exe'
$gguf = 'C:\Users\Administrator\Documents\Default Project\models\anya-f16.gguf'
$port = 8090
$logDir = 'S:\tools\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null

if (-not (Test-Path $exe))  { Write-Error "llama-server not found at $exe"; exit 1 }
if (-not (Test-Path $gguf)) { Write-Error "Model not found at $gguf"; exit 1 }

# Stop any previous instance so the port is free.
Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

# Free VRAM from Ollama so both tools don't fight over the GPU (optional).
$ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (Test-Path $ollama) { & $ollama stop anya 2>$null | Out-Null }

Write-Host "Starting Anya's web server (GPU) ..." -ForegroundColor Cyan
Start-Process -FilePath $exe `
  -ArgumentList "-m `"$gguf`" --host 127.0.0.1 --port $port -c 8192 -ngl 99" `
  -RedirectStandardOutput (Join-Path $logDir 'llama-server.out.log') `
  -RedirectStandardError  (Join-Path $logDir 'llama-server.err.log') `
  -WindowStyle Hidden

for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Milliseconds 1000
    try { Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 3 | Out-Null; break } catch {}
}

Write-Host "Opening http://127.0.0.1:$port ..." -ForegroundColor Green
Start-Process "http://127.0.0.1:$port"

Write-Host ""
Write-Host "Anya is live in your browser. The server keeps running in the background." -ForegroundColor Yellow
Write-Host "To stop it later:  Get-Process llama-server | Stop-Process" -ForegroundColor Yellow
