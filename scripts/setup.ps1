[CmdletBinding()]
param([switch]$DemoOnly)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$bootstrapPython = $null
$bootstrapPrefix = @()

$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
    foreach ($selector in "-3.13", "-3.12") {
        & $launcher.Source $selector -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $bootstrapPython = $launcher.Source
            $bootstrapPrefix = @($selector)
            break
        }
    }
}
if (-not $bootstrapPython) {
    $pathPython = Get-Command python -ErrorAction SilentlyContinue
    if ($pathPython) {
        & $pathPython.Source -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $bootstrapPython = $pathPython.Source }
    }
}

function Invoke-BootstrapPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if (-not $bootstrapPython) { throw "未找到受支持的 Python。请安装 Python 3.12 或 3.13。" }
    & $bootstrapPython @bootstrapPrefix @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python 命令执行失败。" }
}

Write-Host $(if ($DemoOnly) { "[1/2] 检查 Node.js" } else { "[1/4] 检查 Node.js" })
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "未找到 Node.js，请安装 22.13 或更高版本。" }
$nodeVersion = [version]((& node --version).Trim().TrimStart("v"))
if ($nodeVersion -lt [version]"22.13.0") { throw "Node.js 版本过低，需要 22.13 或更高版本。" }

if ($DemoOnly) {
    Write-Host "[2/2] 安装 Web 依赖"
    Push-Location (Join-Path $projectRoot "apps\web")
    try { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw "Web 依赖安装失败。" } }
    finally { Pop-Location }
    Write-Host "演示环境准备完成。运行 .\scripts\start.ps1 -Demo。" -ForegroundColor Green
    exit 0
}

Write-Host "[2/4] 创建 Python 虚拟环境"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Invoke-BootstrapPython -m venv (Join-Path $projectRoot ".venv")
}
$pythonVersion = [version]((& $venvPython -c "import platform; print(platform.python_version())").Trim())
if ($pythonVersion -lt [version]"3.12.0" -or $pythonVersion -ge [version]"3.14.0") {
    throw "Python 版本不受支持，需要 3.12 或 3.13。"
}

Write-Host "[3/4] 安装 API 与开发依赖"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e (Join-Path $projectRoot "services\api[dev]")
if ($LASTEXITCODE -ne 0) { throw "API 依赖安装失败。" }

Write-Host "[4/4] 安装 Web 依赖"
Push-Location (Join-Path $projectRoot "apps\web")
try { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw "Web 依赖安装失败。" } }
finally { Pop-Location }

Write-Host "准备完成。运行 .\scripts\start.ps1 启动完整模式，或加 -Demo 启动零配置演示。" -ForegroundColor Green
