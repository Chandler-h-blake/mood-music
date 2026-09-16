[CmdletBinding()]
param()

$runDir = Join-Path (Split-Path -Parent $PSScriptRoot) ".run"
foreach ($name in "api", "web") {
    $pidFile = Join-Path $runDir "$name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $processId = [int](Get-Content -LiteralPath $pidFile -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $processId
        Write-Host "已停止 $name（PID $processId）"
    }
    Remove-Item -LiteralPath $pidFile -Force
}
Write-Host "PostgreSQL 容器保持运行，以保留本地数据。" -ForegroundColor Yellow
