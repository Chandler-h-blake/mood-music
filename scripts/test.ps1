[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "请先运行 .\scripts\setup.ps1。" }
$runDir = Join-Path $projectRoot ".run"
$pytestTemp = Join-Path $runDir "pytest"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

Write-Host "运行 Python 静态检查与测试"
& $python -m ruff check --no-cache $projectRoot
if ($LASTEXITCODE -ne 0) { throw "Ruff 检查失败。" }
Push-Location (Join-Path $projectRoot "services\api")
try { & $python -B -m pytest -p no:cacheprovider --basetemp $pytestTemp; if ($LASTEXITCODE -ne 0) { throw "pytest 失败。" } }
finally { Pop-Location }
if (Test-Path -LiteralPath $pytestTemp) { Remove-Item -LiteralPath $pytestTemp -Recurse -Force }
if ((Get-ChildItem -LiteralPath $runDir -Force -ErrorAction SilentlyContinue).Count -eq 0) { Remove-Item -LiteralPath $runDir -Force }

Write-Host "运行 Web 检查"
Push-Location (Join-Path $projectRoot "apps\web")
try {
    & npm.cmd run lint; if ($LASTEXITCODE -ne 0) { throw "ESLint 失败。" }
    & npm.cmd run typecheck; if ($LASTEXITCODE -ne 0) { throw "TypeScript 检查失败。" }
    if (-not $SkipBuild) { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw "Web 构建失败。" } }
    & npm.cmd audit --omit=dev --audit-level=high --registry=https://registry.npmjs.org; if ($LASTEXITCODE -ne 0) { throw "生产依赖审计失败。" }
} finally { Pop-Location }
Write-Host "全部检查通过。" -ForegroundColor Green
