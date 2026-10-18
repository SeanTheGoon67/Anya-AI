# redeploy_anya.ps1
# After training finishes: merge the LoRA adapter -> convert to GGUF -> load into
# Ollama as `anya`, and restart the browser chat UI on the new weights.
#
#   powershell -ExecutionPolicy Bypass -File .\tools\redeploy_anya.ps1
#
# Safe to re-run. If any step fails, the previously installed `anya` model is
# left untouched until step 3 succeeds.

$ErrorActionPreference = 'Stop'

$proj = 'C:\Users\Administrator\Documents\Default Project'
$py   = 'S:\envs\ai\Scripts\python.exe'
$lf   = 'S:\envs\ai\Scripts\llamafactory-cli.exe'
$conv = 'S:\repos\llama.cpp-master\convert_hf_to_gguf.py'
$ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'

Set-Location $proj
$env:HF_HOME      = 'S:\.cache\huggingface'
$env:HF_HUB_CACHE = 'S:\.cache\huggingface\hub'
$env:OLLAMA_MODELS = 'S:\ollama\models'

Write-Host '[1/4] Merging the LoRA adapter into a full model ...' -ForegroundColor Cyan
& $lf export .\train\export.yaml
if ($LASTEXITCODE -ne 0) { throw "export failed ($LASTEXITCODE)" }
if (-not (Test-Path .\models\qwen2.5-coder-1.5b-merged\config.json)) {
    throw 'merged model not found after export'
}

Write-Host '[2/4] Converting to GGUF (f16) ...' -ForegroundColor Cyan
& $py $conv .\models\qwen2.5-coder-1.5b-merged --outfile .\models\anya-f16.gguf --outtype f16
if ($LASTEXITCODE -ne 0) { throw "gguf conversion failed ($LASTEXITCODE)" }
Write-Host ("      gguf: {0:N0} MB" -f ((Get-Item .\models\anya-f16.gguf).Length / 1MB))

Write-Host '[3/4] Importing into Ollama as `anya` ...' -ForegroundColor Cyan
if (-not (Test-Path $ollama)) { throw "ollama.exe not found at $ollama" }
& $ollama create anya -f .\Modelfile
if ($LASTEXITCODE -ne 0) { throw "ollama create failed ($LASTEXITCODE)" }

Write-Host '[4/4] Restarting the browser chat UI on the new weights ...' -ForegroundColor Cyan
Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
if (Test-Path 'S:\tools\llama-vulkan\llama-server.exe') {
    $gguf = (Resolve-Path .\models\anya-f16.gguf).Path
    Start-Process -FilePath 'S:\tools\llama-vulkan\llama-server.exe' `
        -ArgumentList "-m `"$gguf`" --host 127.0.0.1 --port 8090 -c 8192 -ngl 99" `
        -RedirectStandardOutput 'S:\tools\logs\llama-server.out.log' `
        -RedirectStandardError  'S:\tools\logs\llama-server.err.log' `
        -WindowStyle Hidden
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Milliseconds 1000
        try { Invoke-RestMethod 'http://127.0.0.1:8090/health' -TimeoutSec 3 | Out-Null; break } catch {}
    }
    Write-Host '      browser UI: http://127.0.0.1:8090' -ForegroundColor Green
}

Write-Host ''
Write-Host 'Done. Anya is redeployed. Test her with:' -ForegroundColor Green
Write-Host "    & '$py' .\tools\test_anya.py            # Ollama" -ForegroundColor Gray
Write-Host "    & '$py' .\tools\test_anya.py --port 8090 --openai   # browser server" -ForegroundColor Gray
