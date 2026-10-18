# fetch_repo_paths.ps1
# Download only selected folders from a GitHub repo (avoids multi-GB asset dirs).
# Lists each folder with ONE contents-API call, then pulls files from raw.githubusercontent.com.

param(
  [Parameter(Mandatory=$true)][string]$Repo,
  [Parameter(Mandatory=$true)][string]$Branch,
  [Parameter(Mandatory=$true)][string]$Dest,
  [Parameter(Mandatory=$true)][string[]]$Paths
)

$ErrorActionPreference = 'Stop'
$headers = @{ 'User-Agent' = 'opencode' }

function Fetch-Dir($repo, $branch, $path, $destRoot) {
  $url = "https://api.github.com/repos/$repo/contents/$path"
  $items = Invoke-RestMethod -Uri $url -Headers $headers
  foreach ($it in $items) {
    $rel = if ($path) { "$path/$($it.name)" } else { $it.name }
    if ($it.type -eq 'dir') {
      Fetch-Dir $repo $branch $rel $destRoot
    } elseif ($it.type -eq 'file') {
      $local = Join-Path $destRoot ($rel -replace '/', '\')
      $dir = Split-Path $local -Parent
      if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
      try {
        Invoke-WebRequest -Uri $it.download_url -OutFile $local -UseBasicParsing
      } catch {
        Write-Warning "failed: $rel"
      }
    }
  }
}

foreach ($p in $Paths) {
  Fetch-Dir $Repo $Branch $p $Dest
}

$n = (Get-ChildItem $Dest -Recurse -File | Measure-Object).Count
Write-Host "[+] $Repo -> $n files under $Dest"
