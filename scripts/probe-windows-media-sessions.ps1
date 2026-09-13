[CmdletBinding()]
param(
    [ValidateRange(3, 30)]
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"
$workerPath = Join-Path $PSScriptRoot "probe-windows-media-sessions-worker.ps1"
$windowsPowerShell = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

foreach ($requiredPath in @($windowsPowerShell, $workerPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "媒体会话探测所需文件不存在：$requiredPath"
    }
}

$standardOutput = Join-Path ([IO.Path]::GetTempPath()) (
    "moodmusic-media-output-" + [guid]::NewGuid().ToString("N") + ".txt"
)
$standardError = Join-Path ([IO.Path]::GetTempPath()) (
    "moodmusic-media-error-" + [guid]::NewGuid().ToString("N") + ".txt"
)

try {
    $probeProcess = Start-Process -FilePath $windowsPowerShell -WindowStyle Hidden `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $workerPath) `
        -RedirectStandardOutput $standardOutput -RedirectStandardError $standardError -PassThru
    $completed = $probeProcess.WaitForExit($TimeoutSeconds * 1000)
    if (-not $completed) {
        $probeProcess.Kill()
        $probeProcess.WaitForExit()
        [PSCustomObject]@{
            status = "timeout"
            message = "Windows 媒体会话在限定时间内没有响应。"
        } | ConvertTo-Json
        exit 0
    }

    $output = Get-Content -LiteralPath $standardOutput -Raw -Encoding utf8 `
        -ErrorAction SilentlyContinue
    $errorOutput = Get-Content -LiteralPath $standardError -Raw -Encoding utf8 `
        -ErrorAction SilentlyContinue
    if ($probeProcess.ExitCode -eq 0 -and $output) {
        $result = $output.Trim() | ConvertFrom-Json
        [PSCustomObject]@{
            status = if ($result.sessionCount -gt 0) { "sessionsFound" } else { "noSessions" }
            result = $result
            message = "只读取了 Windows 媒体会话；没有执行播放控制。"
        } | ConvertTo-Json -Depth 6
    } else {
        [PSCustomObject]@{
            status = "queryFailed"
            message = $errorOutput.Trim()
        } | ConvertTo-Json -Depth 4
    }
} finally {
    Remove-Item -LiteralPath $standardOutput,$standardError -Force -ErrorAction SilentlyContinue
}
