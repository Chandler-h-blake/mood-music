[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$webDir = Join-Path $projectRoot "apps\web"
$runDir = Join-Path $projectRoot ".run"
$pidFile = Join-Path $runDir "web.pid"
$demoUrl = "http://127.0.0.1:5173/?demo=1"

function Wait-LocalUrl([string]$Url, [int]$TimeoutSeconds = 120) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $Url
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "MoodMusic did not become ready within $TimeoutSeconds seconds."
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    Start-Process "https://nodejs.org/en/download"
    throw "Node.js is required. Install the LTS version from the page that just opened, then double-click Start-MoodMusic-Demo.cmd again."
}

$nodeVersion = [version]((& $nodeCommand.Source --version).Trim().TrimStart("v"))
if ($nodeVersion -lt [version]"22.13.0") {
    Start-Process "https://nodejs.org/en/download"
    throw "Node.js 22.13 or newer is required. Update Node.js, then try again."
}

if (Test-Path -LiteralPath $pidFile) {
    $existingId = [int](Get-Content -LiteralPath $pidFile -Raw)
    if (Get-Process -Id $existingId -ErrorAction SilentlyContinue) {
        Wait-LocalUrl $demoUrl 15
        Start-Process $demoUrl
        Write-Host "MoodMusic is already running. The demo has been opened in your browser." -ForegroundColor Green
        exit 0
    }
    Remove-Item -LiteralPath $pidFile -Force
}

if (-not (Test-Path -LiteralPath (Join-Path $webDir "node_modules"))) {
    Write-Host "First run: installing the demo components. This can take a few minutes..."
    Push-Location $webDir
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw "The demo components could not be installed. Check your network connection and try again." }
    } finally {
        Pop-Location
    }
}

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$demoScript = '"' + (Join-Path $webDir "scripts\demo.mjs") + '"'
$web = Start-Process -FilePath $nodeCommand.Source -ArgumentList $demoScript -WorkingDirectory $webDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runDir "web.out.log") -RedirectStandardError (Join-Path $runDir "web.err.log") -PassThru
Set-Content -LiteralPath $pidFile -Value $web.Id

try {
    Wait-LocalUrl $demoUrl
} catch {
    & (Join-Path $PSScriptRoot "stop.ps1")
    throw
}

Start-Process $demoUrl
Write-Host "MoodMusic is ready and has been opened in your browser." -ForegroundColor Green
Write-Host "Double-click Stop-MoodMusic.cmd when you are finished."
