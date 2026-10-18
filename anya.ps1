# anya.ps1 — start the local "Anya" assistant in a terminal.
#
#   Right-click -> Run with PowerShell
#   or:  powershell -ExecutionPolicy Bypass -File .\anya.ps1
#
# It makes sure the Ollama server is running (models live on S:\) and then
# drops you into a chat with the fine-tuned model `anya`.

$ErrorActionPreference = 'Stop'
$env:OLLAMA_MODELS = 'S:\ollama\models'          # model store is on the S: drive

$exe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not (Test-Path $exe)) {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $cmd) { Write-Error "Ollama not found. Reinstall from https://ollama.com/download"; exit 1 }
    $exe = $cmd.Source
}

function Test-Server {
    try {
        Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch { return $false }
}

if (-not (Test-Server)) {
    Write-Host "Starting the Ollama server (models: S:\ollama\models) ..." -ForegroundColor Cyan
    Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Server) { break }
    }
}

if (-not (Test-Server)) { Write-Error "Ollama server did not start. Try: & '$exe' serve"; exit 1 }

Write-Host "Anya is ready. Type your message. (/bye to exit, /? for help)" -ForegroundColor Green
& $exe run anya
