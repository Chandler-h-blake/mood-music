[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Play", "Pause", "Next", "Previous")]
    [string]$Action,
    [ValidateRange(3, 30)]
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"
$workerPath = Join-Path $PSScriptRoot "control-qqmusic-worker.ps1"
$windowsPowerShell = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

foreach ($requiredPath in @($windowsPowerShell, $workerPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "QQ 音乐控制所需文件不存在：$requiredPath"
    }
}

$standardOutput = Join-Path ([IO.Path]::GetTempPath()) (
    "moodmusic-control-output-" + [guid]::NewGuid().ToString("N") + ".txt"
)
$standardError = Join-Path ([IO.Path]::GetTempPath()) (
    "moodmusic-control-error-" + [guid]::NewGuid().ToString("N") + ".txt"
)

try {
    $controlProcess = Start-Process -FilePath $windowsPowerShell -WindowStyle Hidden `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $workerPath,
            "-Action",
            $Action
        ) `
        -RedirectStandardOutput $standardOutput -RedirectStandardError $standardError -PassThru
    $completed = $controlProcess.WaitForExit($TimeoutSeconds * 1000)
    if (-not $completed) {
        $controlProcess.Kill()
        $controlProcess.WaitForExit()
        [PSCustomObject]@{
            status = "timeout"
            action = $Action
            message = "QQ 音乐没有在限定时间内响应控制命令。"
        } | ConvertTo-Json
        exit 0
    }

    $output = Get-Content -LiteralPath $standardOutput -Raw -Encoding utf8 `
        -ErrorAction SilentlyContinue
    $errorOutput = Get-Content -LiteralPath $standardError -Raw -Encoding utf8 `
        -ErrorAction SilentlyContinue
    if ($controlProcess.ExitCode -eq 0 -and $output) {
        [PSCustomObject]@{
            status = "completed"
            result = $output.Trim() | ConvertFrom-Json
            message = "QQ 音乐已处理控制命令。"
        } | ConvertTo-Json -Depth 5
    } else {
        [PSCustomObject]@{
            status = "rejected"
            action = $Action
            message = $errorOutput.Trim()
        } | ConvertTo-Json -Depth 4
    }
} finally {
    Remove-Item -LiteralPath $standardOutput,$standardError -Force -ErrorAction SilentlyContinue
}
