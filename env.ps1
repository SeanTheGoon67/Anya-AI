# Dot-source this to activate the AI env with all paths on S:
#   . .\env.ps1

$Venv = 'S:\envs\ai'

$env:HF_HOME             = 'S:\.cache\huggingface'
$env:HF_HUB_CACHE        = 'S:\.cache\huggingface\hub'
$env:TRANSFORMERS_CACHE  = 'S:\.cache\huggingface'
$env:HF_DATASETS_CACHE   = 'S:\.cache\datasets'
$env:OLLAMA_MODELS       = 'S:\ollama\models'

# keep CUDA allocations from being fragmented across the 8 GB card
$env:PYTORCH_CUDA_ALLOC_CONF = 'expandable_segments:True'

# avoid tokenizer fork warnings
$env:TOKENIZERS_PARALLELISM = 'false'

$py = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Error "venv python not found at $py"
    return
}

# prepend venv + Scripts so `python`, `llamafactory-cli` resolve to the venv
$env:Path = "$Venv\Scripts;$env:Path"
$env:VIRTUAL_ENV = $Venv

Write-Host "AI env active  (python: $py)" -ForegroundColor Green
Write-Host "  HF_HOME     = $env:HF_HOME"
Write-Host "  OLLAMA_MODELS = $env:OLLAMA_MODELS"
