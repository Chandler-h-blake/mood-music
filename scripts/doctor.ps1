[CmdletBinding()]
param([switch]$Json)

$projectRoot = Split-Path -Parent $PSScriptRoot
$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check([string]$Name, [bool]$Ok, [string]$Detail, [bool]$Required = $true) {
    $checks.Add([pscustomobject]@{ name = $Name; ok = $Ok; required = $Required; detail = $Detail })
}

$node = Get-Command node -ErrorAction SilentlyContinue
$nodeVersion = if ($node) { (& node --version) -join "" } else { "未安装" }
$nodeOk = $false
if ($node) { $nodeOk = [version]$nodeVersion.TrimStart("v") -ge [version]"22.13.0" }
Add-Check "Node.js >= 22" $nodeOk $nodeVersion

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $pythonVersion = (& $venvPython --version) -join ""
    Add-Check "Python 虚拟环境" ($pythonVersion -match "Python 3\.(12|13)") $pythonVersion
} else {
    Add-Check "Python 虚拟环境" $false "未找到 .venv；请运行 scripts\setup.ps1"
}

$docker = Get-Command docker -ErrorAction SilentlyContinue
Add-Check "Docker CLI" ([bool]$docker) $(if ($docker) { (& docker --version) -join "" } else { "未安装；演示模式不需要" }) $false
$dockerReady = $false
if ($docker) { & docker info *> $null; $dockerReady = $LASTEXITCODE -eq 0 }
Add-Check "Docker Engine" $dockerReady $(if ($dockerReady) { "可用" } else { "未运行；演示模式不需要" }) $false

$runningQQMusic = Get-Process QQMusic -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Path
$qqCandidates = @(
    $env:QQMUSIC_EXE,
    $runningQQMusic,
    "$env:ProgramFiles\Tencent\QQMusic\QQMusic.exe",
    "${env:ProgramFiles(x86)}\Tencent\QQMusic\QQMusic.exe",
    "$env:LOCALAPPDATA\Programs\QQMusic\QQMusic.exe"
)
$qqPath = $qqCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
Add-Check "QQ 音乐客户端" ([bool]$qqPath) $(if ($qqPath) { $qqPath } else { "未在常见位置找到；演示模式不需要" }) $false

foreach ($port in 5432, 8000, 5173) {
    $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    Add-Check "端口 $port" (-not [bool]$owner) $(if ($owner) { "已被进程 $($owner.OwningProcess) 使用" } else { "可用" }) $false
}

if ($Json) {
    $checks | ConvertTo-Json -Depth 3
} else {
    $checks | ForEach-Object {
        $symbol = if ($_.ok) { "✓" } elseif ($_.required) { "✗" } else { "!" }
        $color = if ($_.ok) { "Green" } elseif ($_.required) { "Red" } else { "Yellow" }
        Write-Host "$symbol $($_.name): $($_.detail)" -ForegroundColor $color
    }
}

if ($checks.Where({ $_.required -and -not $_.ok }).Count) { exit 1 }
