[CmdletBinding()]
param([switch]$Demo)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $projectRoot ".run"
$webDir = Join-Path $projectRoot "apps\web"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$node = (Get-Command node -ErrorAction SilentlyContinue).Source
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

function Wait-LocalUrl([string]$Url, [int]$TimeoutSeconds = 120) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $Url
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "服务未能在 $TimeoutSeconds 秒内就绪：$Url"
}

if (-not (Test-Path -LiteralPath (Join-Path $webDir "node_modules"))) {
    throw "依赖尚未安装，请先运行 .\scripts\setup.ps1。"
}
if (-not $node) { throw "未找到 Node.js，请先运行 .\scripts\setup.ps1。" }

if ($Demo) {
    $demoScript = '"' + (Join-Path $webDir "scripts\demo.mjs") + '"'
    $web = Start-Process -FilePath $node -ArgumentList $demoScript -WorkingDirectory $webDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runDir "web.out.log") -RedirectStandardError (Join-Path $runDir "web.err.log") -PassThru
    Set-Content -LiteralPath (Join-Path $runDir "web.pid") -Value $web.Id
    try { Wait-LocalUrl "http://127.0.0.1:5173/" }
    catch { & (Join-Path $PSScriptRoot "stop.ps1"); throw }
    Write-Host "演示模式已就绪：http://127.0.0.1:5173（PID $($web.Id)）" -ForegroundColor Green
    exit 0
}

if (-not (Test-Path -LiteralPath $python)) { throw "Python 虚拟环境不存在，请先运行 .\scripts\setup.ps1。" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "完整模式需要 Docker Desktop。" }

& docker compose -f (Join-Path $projectRoot "infra\docker\compose.yml") up -d
if ($LASTEXITCODE -ne 0) { throw "数据库启动失败。" }
$deadline = (Get-Date).AddSeconds(90)
do {
    $health = (& docker inspect --format "{{.State.Health.Status}}" moodmusic-postgres 2>$null) -join ""
    if ($health -eq "healthy") { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
if ($health -ne "healthy") { throw "数据库未能在 90 秒内就绪。" }

$env:DATABASE_URL = "postgresql+asyncpg://moodmusic:moodmusic@127.0.0.1:5432/moodmusic"
$env:MOODMUSIC_DATA_DIR = Join-Path $projectRoot "data"
Push-Location (Join-Path $projectRoot "services\api")
try { & $python -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw "数据库迁移失败。" } }
finally { Pop-Location }

$api = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "moodmusic_api.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory (Join-Path $projectRoot "services\api") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runDir "api.out.log") -RedirectStandardError (Join-Path $runDir "api.err.log") -PassThru
$frameworkScript = '"' + (Join-Path $webDir "scripts\run-framework.mjs") + '"'
$web = Start-Process -FilePath $node -ArgumentList $frameworkScript, "dev" -WorkingDirectory $webDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runDir "web.out.log") -RedirectStandardError (Join-Path $runDir "web.err.log") -PassThru
Set-Content -LiteralPath (Join-Path $runDir "api.pid") -Value $api.Id
Set-Content -LiteralPath (Join-Path $runDir "web.pid") -Value $web.Id
try {
    Wait-LocalUrl "http://127.0.0.1:8000/api/v1/health/ready"
    Wait-LocalUrl "http://127.0.0.1:5173/"
} catch {
    & (Join-Path $PSScriptRoot "stop.ps1")
    throw
}
Write-Host "MoodMusic 已就绪：Web http://127.0.0.1:5173 · API http://127.0.0.1:8000/docs" -ForegroundColor Green
