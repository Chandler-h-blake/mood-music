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
        throw "A required QQ Music control file is missing: $requiredPath"
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
            message = "QQ Music did not respond before the control timeout."
        } | ConvertTo-Json
        exit 0
    }

    $output = Get-Content -LiteralPath $standardOutput -Raw -Encoding utf8 `
        -ErrorAction SilentlyContinue
    $errorOutput = Get-Content -LiteralPath $standardError -Raw -Encoding utf8 `
        -ErrorAction SilentlyContinue
    if ($controlProcess.ExitCode -eq 0 -and $output) {
        $result = $output.Trim() | ConvertFrom-Json
        $status = if ($result.observed) { "completed" } else { "acceptedUnconfirmed" }
        $message = if ($result.observed) {
            "Confirmed that QQ Music completed the control action."
        } else {
            "Windows accepted the command, but QQ Music did not confirm the action."
        }
        [PSCustomObject]@{
            status = $status
            result = $result
            message = $message
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
