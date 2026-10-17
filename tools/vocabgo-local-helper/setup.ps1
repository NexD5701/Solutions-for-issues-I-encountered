[CmdletBinding()]
param([switch]$PrepareOnly)

$ErrorActionPreference = 'Stop'
$packageRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$setupRoot = Join-Path $packageRoot '.setup'
$downloadsRoot = Join-Path $setupRoot 'downloads'
$applicationRoot = Join-Path $packageRoot 'Easy_Cidaren'
$manifest = Get-Content -LiteralPath (Join-Path $packageRoot 'UPSTREAM.json') -Raw | ConvertFrom-Json
$gitCommand = Get-Command git.exe -ErrorAction Stop
if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required.' }

function Assert-PackagePath([string]$Candidate) {
    $absolute = [IO.Path]::GetFullPath($Candidate)
    if (-not $absolute.StartsWith($packageRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing to write outside this package directory.'
    }
}

function Get-CheckedDownload([string]$Uri, [string]$Destination, [string]$ExpectedHash) {
    Assert-PackagePath $Destination
    if (Test-Path -LiteralPath $Destination) {
        if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ieq $ExpectedHash) { return }
    }
    $partial = $Destination + '.download'
    Assert-PackagePath $partial
    Write-Host ('Downloading ' + [IO.Path]::GetFileName($Destination))
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $partial
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ine $ExpectedHash) {
        throw ('SHA-256 verification failed: ' + [IO.Path]::GetFileName($Destination))
    }
    Move-Item -LiteralPath $partial -Destination $Destination -Force
}

New-Item -ItemType Directory -Path $downloadsRoot -Force | Out-Null
$sourceArchive = Join-Path $downloadsRoot 'Easy_Cidaren-source.zip'
Get-CheckedDownload $manifest.archive_url $sourceArchive $manifest.archive_sha256
$sourceMarker = Join-Path $setupRoot 'source-commit.txt'
if (Test-Path -LiteralPath $applicationRoot) {
    if (-not (Test-Path -LiteralPath $sourceMarker) -or
        (Get-Content -LiteralPath $sourceMarker -Raw).Trim() -ne $manifest.commit) {
        throw 'An unrecognized application directory exists. Use a fresh package directory.'
    }
} else {
    $extractRoot = Join-Path $setupRoot 'source'
    Expand-Archive -LiteralPath $sourceArchive -DestinationPath $extractRoot -Force
    $extractedSource = Join-Path $extractRoot ('Easy_Cidaren-' + $manifest.commit)
    Assert-PackagePath $extractedSource
    Assert-PackagePath $applicationRoot
    Move-Item -LiteralPath $extractedSource -Destination $applicationRoot
    [IO.File]::WriteAllText($sourceMarker, $manifest.commit, [Text.Encoding]::ASCII)
}

$patchFile = Join-Path $packageRoot 'upstream.patch'
Push-Location $applicationRoot
try {
    & $gitCommand.Source apply --check --ignore-space-change --whitespace=nowarn -- $patchFile 2>$null
    if ($LASTEXITCODE -eq 0) {
        & $gitCommand.Source apply --ignore-space-change --whitespace=nowarn -- $patchFile
        if ($LASTEXITCODE -ne 0) { throw 'Applying the upstream patch failed.' }
    } else {
        & $gitCommand.Source apply --reverse --check --ignore-space-change --whitespace=nowarn -- $patchFile 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'The source does not match the pinned upstream or applied patch.' }
    }
} finally { Pop-Location }

$additionsRoot = Join-Path $packageRoot 'files'
Get-ChildItem -LiteralPath $additionsRoot -Recurse -File | ForEach-Object {
    $relative = $_.FullName.Substring($additionsRoot.Length).TrimStart('\')
    $destination = Join-Path $applicationRoot $relative
    Assert-PackagePath $destination
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
}

$pythonArchive = Join-Path $downloadsRoot 'python-3.12.10.zip'
$pythonRoot = Join-Path $setupRoot 'python'
Get-CheckedDownload $manifest.python.url $pythonArchive $manifest.python.sha256
if (-not (Test-Path -LiteralPath (Join-Path $pythonRoot 'python.exe'))) {
    Expand-Archive -LiteralPath $pythonArchive -DestinationPath $pythonRoot -Force
}
$pythonPathFile = Join-Path $pythonRoot 'python312._pth'
[IO.File]::WriteAllText($pythonPathFile,
    "python312.zip`r`n.`r`nLib/site-packages`r`n../../Easy_Cidaren`r`nimport site`r`n", [Text.Encoding]::ASCII)

if ($PrepareOnly) {
    Write-Host 'Source, patch and private Python runtime prepared; dependency installation skipped.'
    return
}
$uvArchive = Join-Path $downloadsRoot 'uv-windows.zip'
$uvRoot = Join-Path $setupRoot 'uv'
Get-CheckedDownload $manifest.uv.url $uvArchive $manifest.uv.sha256
if (-not (Test-Path -LiteralPath (Join-Path $uvRoot 'uv.exe'))) {
    Expand-Archive -LiteralPath $uvArchive -DestinationPath $uvRoot -Force
}
$pythonExe = Join-Path $pythonRoot 'python.exe'
$uvExe = Join-Path $uvRoot 'uv.exe'
$cacheRoot = Join-Path $setupRoot 'cache'
& $uvExe --no-config pip install --python $pythonExe --prefix $pythonRoot --cache-dir $cacheRoot --no-progress -r (Join-Path $packageRoot 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $uvExe --no-config pip check --python $pythonExe --cache-dir $cacheRoot
if ($LASTEXITCODE -ne 0) { throw 'Dependency compatibility check failed.' }
& $pythonExe (Join-Path $packageRoot 'tests\verify_local_setup.py')
if ($LASTEXITCODE -ne 0) { throw 'Offline verification failed.' }
Write-Host 'Setup complete. Open the launcher next to this setup script.'
