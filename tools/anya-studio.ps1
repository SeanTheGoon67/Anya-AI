<#
  anya-studio.ps1 -- get Anya ready for Android Studio's built-in AI Assistant.

  Android Studio's AI Assistant (Settings > Tools > AI > Model Providers ->
  Local Provider) only asks for a PORT; it discovers the model itself. Anya can
  be reached on two of them:

    8090   Anya's own app (anya-ui). ONE copy of the model in memory, and the
           Power panel decides how much VRAM/RAM she may use. Preferred.
    11434  Ollama ("anya"). Always available because Ollama autostarts, but if
           Anya's app is also running this loads a SECOND copy of the model.

  This script checks (and optionally starts) both, proves she actually answers,
  and prints the exact values to type into Studio.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File anya-studio.ps1
    .\anya-studio.ps1 -Start      # start Anya's app first if 8090 is down
    .\anya-studio.ps1 -NoChat     # skip the "does she answer" probe (faster)
#>

param(
    [switch]$Start,     # start Anya's app if port 8090 is not listening yet
    [switch]$NoChat     # skip the small chat probe
)

$ErrorActionPreference = 'Continue'

$targets = @(
    @{ Port = 8090;  Label = "Anya's app"; Model = 'anya-f16.gguf';
       Note  = 'ONE copy of the model. Power panel governs VRAM/RAM.' },
    @{ Port = 11434; Label = 'Ollama';     Model = 'anya';
       Note  = 'Always up (autostarts), but a 2nd copy if the app is running.' }
)

function Test-LocalPort([int]$Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async  = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) { $client.Close(); return $false }
        $ok = $client.Connected
        $client.Close()
        return $ok
    } catch { return $false }
}

function Get-ModelNames([int]$Port) {
    try {
        if ($Port -eq 11434) {
            $t = Invoke-RestMethod "http://127.0.0.1:$Port/api/tags" -TimeoutSec 10
            return @($t.models | ForEach-Object { $_.name })
        }
        $m = Invoke-RestMethod "http://127.0.0.1:$Port/v1/models" -TimeoutSec 10
        if ($m.data)   { return @($m.data   | ForEach-Object { $_.id   }) }
        if ($m.models) { return @($m.models | ForEach-Object { $_.name }) }
        return @()
    } catch { return @() }
}

function Test-AnyaChat([int]$Port, [string]$Model) {
    $body = @{
        model      = $Model
        messages   = @(@{ role = 'user'; content = 'Reply with exactly: online' })
        stream     = $false
        max_tokens = 12
    } | ConvertTo-Json -Depth 6
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" `
                               -Method Post -ContentType 'application/json' `
                               -Body $body -TimeoutSec 240
        return ($r.choices[0].message.content).Trim()
    } catch { return $null }
}

Write-Host ''
Write-Host '  Anya  ->  Android Studio AI Assistant' -ForegroundColor Cyan
Write-Host '  ====================================' -ForegroundColor Cyan

# --- optionally bring up the preferred endpoint (8090) -----------------------
if ($Start -and -not (Test-LocalPort 8090)) {
    $starter = Join-Path (Split-Path $PSScriptRoot -Parent) 'anya-ui\start.ps1'
    if (Test-Path $starter) {
        Write-Host ''
        Write-Host '  Starting Anya''s app (port 8090) ...' -ForegroundColor DarkGray
        Start-Process -FilePath 'powershell' -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
            '-File', "`"$starter`"", '-Headless'
        ) -WindowStyle Hidden
        $deadline = (Get-Date).AddSeconds(180)
        while ((Get-Date) -lt $deadline -and -not (Test-LocalPort 8090)) {
            Start-Sleep -Milliseconds 700
        }
    } else {
        Write-Host "  (!) could not find $starter" -ForegroundColor Yellow
    }
}

# --- probe both endpoints ----------------------------------------------------
$results = @()
foreach ($t in $targets) {
    $up     = Test-LocalPort $t.Port
    $models = @()
    if ($up) { $models = @(Get-ModelNames $t.Port) }
    $reply  = $null
    if ($up -and -not $NoChat -and $models.Count -gt 0) {
        $reply = Test-AnyaChat $t.Port $t.Model
    }
    $results += [pscustomobject]@{
        Port   = $t.Port
        Label  = $t.Label
        Up     = $up
        Models = $models
        Reply  = $reply
        Note   = $t.Note
    }
}

Write-Host ''
foreach ($r in $results) {
    $state = if ($r.Up) { 'LISTENING' } else { 'not running' }
    $color = if ($r.Up) { 'Green' } else { 'DarkGray' }
    Write-Host ("  port {0,-5} {1,-12} {2}" -f $r.Port, $r.Label, $state) -ForegroundColor $color
    Write-Host ("        $state  -  $($r.Label)   [$($r.Note)]") -ForegroundColor $color
    if ($r.Up) {
        if ($r.Models.Count -gt 0) {
            foreach ($mn in $r.Models) { Write-Host "          model: $mn" }
        } else {
            Write-Host '          (no models listed)' -ForegroundColor Yellow
        }
        if (-not $NoChat) {
            if ($r.Reply) { Write-Host "          she says: $($r.Reply)" -ForegroundColor Green }
            elseif ($r.Up -and $r.Models.Count -gt 0) { Write-Host '          (no answer - is the model loaded?)' -ForegroundColor Yellow }
        }
    }
}

# --- what to type in Studio --------------------------------------------------
$best = $results | Where-Object { $_.Up -and $_.Models.Count -gt 0 } |
        Sort-Object Port | Select-Object -First 1     # 8090 sorts first

Write-Host ''
Write-Host '  In Android Studio:' -ForegroundColor Cyan
Write-Host '    File > Settings > Tools > AI > Model Providers'
Write-Host '      click  +   ->   Local Provider'
Write-Host '        Description    : Anya (local)'
if ($best) {
    Write-Host ("        Port           : {0}" -f $best.Port) -ForegroundColor Green
    Write-Host ("        Enable a model : {0}" -f $best.Models[0]) -ForegroundColor Green
} else {
    Write-Host '        Port           : 8090   (or 11434)'
    Write-Host '        Enable a model : anya'
}
Write-Host '    Then open the Gemini chat window and switch the model picker to Anya.'
Write-Host ''
Write-Host '  Use CHAT only. Agent Mode needs a tool-trained model:' -ForegroundColor Yellow
Write-Host '  give Anya a tools array and she prints a fake tool call as text.' -ForegroundColor Yellow
Write-Host ''
