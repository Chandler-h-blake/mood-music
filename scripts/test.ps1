[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Run .\scripts\setup.ps1 first." }
$runDir = Join-Path $projectRoot ".run"
$pytestTemp = Join-Path $runDir "pytest"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

Write-Host "Running Python lint and tests"
& $python -m ruff check --no-cache $projectRoot
if ($LASTEXITCODE -ne 0) { throw "Ruff failed." }
Push-Location (Join-Path $projectRoot "services\api")
try { & $python -B -m pytest -p no:cacheprovider --basetemp $pytestTemp; if ($LASTEXITCODE -ne 0) { throw "pytest failed." } }
finally { Pop-Location }
if (Test-Path -LiteralPath $pytestTemp) { Remove-Item -LiteralPath $pytestTemp -Recurse -Force }
if ((Get-ChildItem -LiteralPath $runDir -Force -ErrorAction SilentlyContinue).Count -eq 0) { Remove-Item -LiteralPath $runDir -Force }

Write-Host "Running web checks"
Push-Location (Join-Path $projectRoot "apps\web")
try {
    & npm.cmd run lint; if ($LASTEXITCODE -ne 0) { throw "ESLint failed." }
    & npm.cmd run typecheck; if ($LASTEXITCODE -ne 0) { throw "TypeScript check failed." }
    if (-not $SkipBuild) { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw "Web build failed." } }
    & npm.cmd audit --omit=dev --audit-level=high --registry=https://registry.npmjs.org; if ($LASTEXITCODE -ne 0) { throw "Production dependency audit failed." }
} finally { Pop-Location }
Write-Host "All checks passed." -ForegroundColor Green
