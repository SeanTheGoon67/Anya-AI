# fetch_teaching_repos.ps1
# Downloads Android/Kotlin *teaching* repos (official samples, codelabs, docs)
# to S:\repos-teach so build_teaching_dataset.py can turn them into training data.
#
# No git needed: uses the GitHub API for the default branch, then codeload zips.
#
#   powershell -ExecutionPolicy Bypass -File .\tools\fetch_teaching_repos.ps1

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

$dest = 'S:\repos-teach'
$zipd = Join-Path $dest '_zips'
New-Item -ItemType Directory -Force $dest | Out-Null
New-Item -ItemType Directory -Force $zipd | Out-Null

# owner/repo  — official Google samples, codelabs, and course/roadmap repos.
$repos = @(
    'android/compose-samples',                     # official Compose samples
    'android/nowinandroid',                        # modern Android app, best practices
    'android/sunflower',                           # classic Jetpack sample
    'android/architecture-samples',                # MVVM / architecture teaching
    'android/codelab-android-compose',             # codelab exercises
    'googlecodelabs/android-compose-codelabs',     # compose codelabs
    'googlecodelabs/android-basics-kotlin-codelabs',
    'googlecodelabs/android-kotlin-codelabs',
    'skydoves/android-developer-roadmap',          # learning roadmap + docs
    'Kotlin/kotlinx.coroutines',                   # coroutine guides (docs/)
    'Kotlin/kotlin-by-example',                    # Kotlin by Example
    'JetBrains/kotlin-workshop',                   # JetBrains Kotlin workshop
    'insert-koin/koin',                            # KDoc-heavy DI library
    'philipplackner/CleanArchitectureNoteApp',     # popular Android course author
    'philipplackner/CryptoApp',
    'philipplackner/MvvmBasics'
)

$headers = @{ 'User-Agent' = 'anya-dataset-builder' }
$maxKB = 600000  # skip anything > ~600 MB

foreach ($slug in $repos) {
    $name = $slug -replace '/', '__'
    $target = Join-Path $dest ($slug.Split('/')[-1])
    if (Test-Path $target) { Write-Host ("[=] {0,-45} already present" -f $slug); continue }

    try {
        $info = Invoke-RestMethod -Uri "https://api.github.com/repos/$slug" -Headers $headers -TimeoutSec 25
    } catch {
        Write-Host ("[x] {0,-45} not found" -f $slug); continue
    }
    if ($info.size -gt $maxKB) {
        Write-Host ("[x] {0,-45} too big ({1} MB)" -f $slug, [int]($info.size / 1024)); continue
    }

    $branch = $info.default_branch
    $zip = Join-Path $zipd "$name.zip"
    Write-Host ("[>] {0,-45} {1,6} MB  ({2})" -f $slug, [int]($info.size / 1024), $branch)
    try {
        Invoke-WebRequest -Uri "https://codeload.github.com/$slug/zip/refs/heads/$branch" `
            -OutFile $zip -Headers $headers -TimeoutSec 600 -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $dest -Force
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        Write-Host ("[+] {0,-45} extracted" -f $slug)
    } catch {
        Write-Host ("[!] {0,-45} download failed: {1}" -f $slug, $_.Exception.Message)
    }
}

Write-Host ""
Write-Host "Repos now at ${dest}:"
Get-ChildItem $dest -Directory | Where-Object { $_.Name -ne '_zips' } |
    ForEach-Object {
        $kt = @(Get-ChildItem $_.FullName -Recurse -Filter *.kt -File -ErrorAction SilentlyContinue).Count
        $md = @(Get-ChildItem $_.FullName -Recurse -Filter *.md -File -ErrorAction SilentlyContinue).Count
        Write-Host ("   {0,-38} {1,6} .kt  {2,4} .md" -f $_.Name, $kt, $md)
    }
