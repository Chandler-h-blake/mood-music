[CmdletBinding()]
param(
    [ValidateRange(3, 30)]
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $projectRoot "connectors\qqmusic-pc\src\QQMusicComProbe.cs"
$serverRegistryPath = "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Classes\WOW6432Node\CLSID\{D4C131B2-5B11-47FF-ABC5-081AB498EA5D}\LocalServer32"
$compilerPath = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
$buildDirectory = Join-Path $projectRoot "data\pc-connector"
$executablePath = Join-Path $buildDirectory "QQMusicComProbe.exe"

if (-not (Test-Path -LiteralPath $serverRegistryPath)) {
    throw "QQ 音乐没有注册 QQMusicSvr.QQMusicPlayer 自动化服务。"
}
$serverPath = (Get-Item -LiteralPath $serverRegistryPath).GetValue("").Trim('"')
if (-not (Test-Path -LiteralPath $serverPath)) {
    throw "QQ 音乐注册的 COM 服务文件不存在：$serverPath"
}
if (-not (Test-Path -LiteralPath $compilerPath)) {
    throw "未找到 Windows 32 位 C# 编译器：$compilerPath"
}

New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null
& $compilerPath /nologo /target:exe /platform:x86 /optimize+ `
    /reference:Microsoft.CSharp.dll /out:$executablePath $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "PC 连接器只读探测器编译失败。"
}

$existingServerIds = @(
    Get-Process -Name QQMusicSvr -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }
)
$serverWasRunning = $existingServerIds.Count -gt 0
$serverProcess = $null
if (-not $serverWasRunning) {
    $serverProcess = Start-Process -FilePath $serverPath -ArgumentList "-Embedding" `
        -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
}

$standardOutput = Join-Path ([IO.Path]::GetTempPath()) (
    "moodmusic-pc-com-output-" + [guid]::NewGuid().ToString("N") + ".txt"
)
$standardError = Join-Path ([IO.Path]::GetTempPath()) (
    "moodmusic-pc-com-error-" + [guid]::NewGuid().ToString("N") + ".txt"
)

try {
    $probeProcess = Start-Process -FilePath $executablePath -WindowStyle Hidden `
        -RedirectStandardOutput $standardOutput -RedirectStandardError $standardError -PassThru
    $completed = $probeProcess.WaitForExit($TimeoutSeconds * 1000)
    if (-not $completed) {
        $probeProcess.Kill()
        $probeProcess.WaitForExit()
        [PSCustomObject]@{
            status = "timeout"
            message = "QQ 音乐 COM 服务在限定时间内没有响应。"
        } | ConvertTo-Json
        exit 0
    }

    $output = Get-Content -LiteralPath $standardOutput -Raw -ErrorAction SilentlyContinue
    $errorOutput = Get-Content -LiteralPath $standardError -Raw -ErrorAction SilentlyContinue
    if ($output) {
        $queriesReady = $probeProcess.ExitCode -eq 0
        $integrated = $queriesReady -and $serverWasRunning
        [PSCustomObject]@{
            status = if ($integrated) {
                "readOnlyReady"
            } elseif ($queriesReady) {
                "standaloneReadOnly"
            } else {
                "partialReadOnly"
            }
            protocol = "QQMusicSvr 1.0"
            serverWasRunning = $serverWasRunning
            result = $output.Trim() | ConvertFrom-Json
            message = if ($integrated) {
                "QQ 音乐 COM 只读查询成功；没有执行播放或队列修改。"
            } elseif ($queriesReady) {
                "只读查询成功，但 COM 服务由探测器临时启动，不能证明它与当前 QQ 音乐客户端联动。"
            } else {
                "QQ 音乐 COM 已激活，但部分只读查询的参数签名仍需校准。"
            }
        } | ConvertTo-Json -Depth 5
    } else {
        [PSCustomObject]@{
            status = "queryFailed"
            protocol = "QQMusicSvr 1.0"
            message = $errorOutput.Trim()
        } | ConvertTo-Json -Depth 5
    }
} finally {
    Remove-Item -LiteralPath $standardOutput,$standardError -Force -ErrorAction SilentlyContinue
    if ($null -ne $serverProcess -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force
    }
}
