param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Play", "Pause", "Next", "Previous")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$managerType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$mediaPropertiesType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties, Windows.Media.Control, ContentType = WindowsRuntime]

function Wait-WindowsRuntimeOperation {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Operation,
        [Parameter(Mandatory = $true)]
        [Type]$ResultType
    )

    $asTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and
            $_.IsGenericMethod -and
            $_.GetParameters().Count -eq 1
        } |
        Select-Object -First 1
    $task = $asTaskMethod.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    try {
        $task.Wait()
    } catch {
        $rootError = $_.Exception.GetBaseException()
        $errorCode = "0x{0:X8}" -f ($rootError.HResult -band 0xffffffffL)
        throw "$($rootError.GetType().FullName) $errorCode`: $($rootError.Message)"
    }
    return $task.Result
}

function Get-MediaSessionManager {
    $lastError = $null
    foreach ($attempt in 1..3) {
        try {
            return Wait-WindowsRuntimeOperation `
                -Operation $managerType::RequestAsync() `
                -ResultType $managerType
        } catch {
            $lastError = $_
            if ($attempt -lt 3) {
                Start-Sleep -Milliseconds 250
            }
        }
    }
    throw $lastError
}

$manager = Get-MediaSessionManager
$qqMusicSessions = @(
    $manager.GetSessions() |
        Where-Object { $_.SourceAppUserModelId -ieq "QQMusic.exe" }
)
if ($qqMusicSessions.Count -ne 1) {
    throw "Expected exactly one QQMusic.exe media session; found $($qqMusicSessions.Count)."
}

$session = $qqMusicSessions[0]
$before = $session.GetPlaybackInfo()
$beforeMedia = Wait-WindowsRuntimeOperation `
    -Operation $session.TryGetMediaPropertiesAsync() `
    -ResultType $mediaPropertiesType
$controls = $before.Controls
$noOp = $false
$operation = $null

switch ($Action) {
    "Play" {
        if ($before.PlaybackStatus.ToString() -eq "Playing") {
            $noOp = $true
        } elseif ($controls.IsPlayEnabled) {
            $operation = $session.TryPlayAsync()
        } else {
            throw "The QQMusic session does not advertise play capability."
        }
    }
    "Pause" {
        if ($before.PlaybackStatus.ToString() -eq "Paused") {
            $noOp = $true
        } elseif ($controls.IsPauseEnabled) {
            $operation = $session.TryPauseAsync()
        } else {
            throw "The QQMusic session does not advertise pause capability."
        }
    }
    "Next" {
        if (-not $controls.IsNextEnabled) {
            throw "The QQMusic session does not advertise next capability."
        }
        $operation = $session.TrySkipNextAsync()
    }
    "Previous" {
        if (-not $controls.IsPreviousEnabled) {
            throw "The QQMusic session does not advertise previous capability."
        }
        $operation = $session.TrySkipPreviousAsync()
    }
}

$accepted = if ($noOp) {
    $true
} else {
    Wait-WindowsRuntimeOperation -Operation $operation -ResultType ([bool])
}
if (-not $accepted) {
    throw "Windows rejected the QQMusic $Action command."
}

$expectedStatus = switch ($Action) {
    "Play" { "Playing" }
    "Pause" { "Paused" }
    default { $null }
}
$observed = $noOp
$after = $before
$media = $beforeMedia
$deadline = [DateTime]::UtcNow.AddSeconds(2)
while (-not $observed -and [DateTime]::UtcNow -lt $deadline) {
    Start-Sleep -Milliseconds 150
    $after = $session.GetPlaybackInfo()
    $media = Wait-WindowsRuntimeOperation `
        -Operation $session.TryGetMediaPropertiesAsync() `
        -ResultType $mediaPropertiesType

    if ($expectedStatus) {
        $observed = $after.PlaybackStatus.ToString() -eq $expectedStatus
    } else {
        $observed =
            $media.Title -ne $beforeMedia.Title -or
            $media.Artist -ne $beforeMedia.Artist
    }
}

[PSCustomObject]@{
    action = $Action
    sourceAppId = $session.SourceAppUserModelId
    accepted = $accepted
    observed = $observed
    noOp = $noOp
    beforeStatus = $before.PlaybackStatus.ToString()
    afterStatus = $after.PlaybackStatus.ToString()
    beforeTitle = $beforeMedia.Title
    beforeArtist = $beforeMedia.Artist
    title = $media.Title
    artist = $media.Artist
} | ConvertTo-Json -Depth 4 -Compress
