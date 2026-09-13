[CmdletBinding()]
param(
    [ValidateRange(3, 30)]
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $projectRoot "connectors\qqmusic-pc\src\QQMusicProtocolActivationProbe.cs"
$compilerPath = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
$qqMusicProcess = Get-Process -Name "QQMusic" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path } |
    Select-Object -First 1
if (-not $qqMusicProcess) {
    throw "Start QQ Music before running this read-only probe."
}
$protocolPath = Join-Path (Split-Path -Parent $qqMusicProcess.Path) "QQMusic_Protocol.dll"
$buildDirectory = Join-Path $projectRoot "data\pc-connector"
$executablePath = Join-Path $buildDirectory "QQMusicProtocolActivationProbe.exe"

foreach ($path in @($sourcePath, $compilerPath, $protocolPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "A required protocol probe file is missing: $path"
    }
}

New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null
& $compilerPath /nologo /target:exe /platform:x86 /optimize+ `
    /out:$executablePath $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "The QQ Music protocol activation probe did not compile."
}

$standardOutput = Join-Path ([IO.Path]::GetTempPath()) (
    "moodmusic-protocol-activation-output-" + [guid]::NewGuid().ToString("N") + ".txt"
)
$standardError = Join-Path ([IO.Path]::GetTempPath()) (
    "moodmusic-protocol-activation-error-" + [guid]::NewGuid().ToString("N") + ".txt"
)
try {
    $probe = Start-Process -FilePath $executablePath -WindowStyle Hidden `
        -WorkingDirectory (Split-Path -Parent $protocolPath) `
        -ArgumentList ('"' + $protocolPath + '"') `
        -RedirectStandardOutput $standardOutput `
        -RedirectStandardError $standardError `
        -PassThru
    if (-not $probe.WaitForExit($TimeoutSeconds * 1000)) {
        $probe.Kill()
        $probe.WaitForExit()
        throw "The QQ Music protocol activation probe timed out."
    }
    $output = Get-Content -LiteralPath $standardOutput -Raw -ErrorAction SilentlyContinue
    $errorOutput = Get-Content -LiteralPath $standardError -Raw -ErrorAction SilentlyContinue
    if ($probe.ExitCode -ne 0) {
        throw $errorOutput.Trim()
    }
    [PSCustomObject]@{
        status = "activationReady"
        result = $output.Trim() | ConvertFrom-Json
        message = "Created ITencentProtocol without registering the DLL; no command was executed."
    } | ConvertTo-Json -Depth 4
} finally {
    Remove-Item -LiteralPath $standardOutput,$standardError -Force -ErrorAction SilentlyContinue
}
