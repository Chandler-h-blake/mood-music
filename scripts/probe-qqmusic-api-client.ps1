[CmdletBinding()]
param(
    [ValidateRange(3, 30)]
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $projectRoot "connectors\qqmusic-pc\src\QQMusicApiClientProbe.cs"
$compilerPath = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
$qqMusicProcess = Get-Process -Name "QQMusic" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path } |
    Select-Object -First 1
if (-not $qqMusicProcess) {
    throw "Start QQ Music before running this read-only probe."
}
$apiPath = Join-Path (Split-Path -Parent $qqMusicProcess.Path) "QQMusicApi.dll"
$buildDirectory = Join-Path $projectRoot "data\pc-connector"
$executablePath = Join-Path $buildDirectory "QQMusicApiClientProbe.exe"
foreach ($path in @($sourcePath, $compilerPath, $apiPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "A required QQ Music API client probe file is missing: $path"
    }
}

New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null
& $compilerPath /nologo /target:exe /platform:x86 /optimize+ `
    /reference:Microsoft.CSharp.dll /out:$executablePath $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "The QQ Music API client probe did not compile."
}

$outputPath = Join-Path ([IO.Path]::GetTempPath()) ("moodmusic-api-client-" + [guid]::NewGuid().ToString("N") + ".txt")
$errorPath = Join-Path ([IO.Path]::GetTempPath()) ("moodmusic-api-client-error-" + [guid]::NewGuid().ToString("N") + ".txt")
try {
    $probe = Start-Process -FilePath $executablePath -WindowStyle Hidden `
        -WorkingDirectory (Split-Path -Parent $apiPath) `
        -ArgumentList ('"' + $apiPath + '"') `
        -RedirectStandardOutput $outputPath -RedirectStandardError $errorPath -PassThru
    if (-not $probe.WaitForExit($TimeoutSeconds * 1000)) {
        $probe.Kill()
        $probe.WaitForExit()
        throw "The QQ Music API client probe timed out."
    }
    $output = Get-Content -LiteralPath $outputPath -Raw -ErrorAction SilentlyContinue
    $errorOutput = Get-Content -LiteralPath $errorPath -Raw -ErrorAction SilentlyContinue
    if ($probe.ExitCode -ne 0) {
        throw $(if ($errorOutput) { $errorOutput.Trim() } else { "Probe exited with code $($probe.ExitCode)." })
    }
    [PSCustomObject]@{
        status = "clientReady"
        result = $output.Trim() | ConvertFrom-Json
        message = "Created QMApiCli and read its version; no playback command was sent."
    } | ConvertTo-Json -Depth 4
} finally {
    Remove-Item -LiteralPath $outputPath,$errorPath -Force -ErrorAction SilentlyContinue
}
