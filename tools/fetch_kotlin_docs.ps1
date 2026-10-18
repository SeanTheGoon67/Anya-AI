# fetch_kotlin_docs.ps1
# Downloads only the markdown topics of the official Kotlin documentation
# (JetBrains/kotlin-web-site, docs/topics — ~120 files, ~1.2 MB).
# The full repo is ~1.2 GB, so we pull just the docs via the contents API.
#
#   powershell -ExecutionPolicy Bypass -File .\tools\fetch_kotlin_docs.ps1

param(
    [string]$Dest = 'S:\repos-teach\kotlin-web-site-docs\docs\topics'
)

$ErrorActionPreference = 'Stop'
$headers = @{ 'User-Agent' = 'anya-dataset-builder' }
New-Item -ItemType Directory -Force $Dest | Out-Null

$list = Invoke-RestMethod `
    'https://api.github.com/repos/JetBrains/kotlin-web-site/contents/docs/topics?ref=master' `
    -Headers $headers -TimeoutSec 30

$md = $list | Where-Object { $_.name -like '*.md' }
$ok = 0; $fail = 0
foreach ($f in $md) {
    $out = Join-Path $Dest $f.name
    if (Test-Path $out) { $ok++; continue }
    try {
        Invoke-WebRequest -Uri $f.download_url -OutFile $out -UseBasicParsing -TimeoutSec 60
        $ok++
    } catch {
        $fail++
        Write-Warning "failed: $($f.name)"
    }
}
Write-Host "[+] Kotlin docs: $ok downloaded, $fail failed -> $Dest"
