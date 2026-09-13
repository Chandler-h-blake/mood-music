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
    $task.Wait()
    return $task.Result
}

$manager = Wait-WindowsRuntimeOperation `
    -Operation $managerType::RequestAsync() `
    -ResultType $managerType
$qqMusicSessions = @(
    $manager.GetSessions() |
        Where-Object { $_.SourceAppUserModelId -ieq "QQMusic.exe" }
)
if ($qqMusicSessions.Count -ne 1) {
    throw "Expected exactly one QQMusic.exe media session; found $($qqMusicSessions.Count)."
}

$session = $qqMusicSessions[0]
$before = $session.GetPlaybackInfo()
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
Start-Sleep -Milliseconds 350

$after = $session.GetPlaybackInfo()
$media = Wait-WindowsRuntimeOperation `
    -Operation $session.TryGetMediaPropertiesAsync() `
    -ResultType $mediaPropertiesType

[PSCustomObject]@{
    action = $Action
    sourceAppId = $session.SourceAppUserModelId
    accepted = $accepted
    noOp = $noOp
    beforeStatus = $before.PlaybackStatus.ToString()
    afterStatus = $after.PlaybackStatus.ToString()
    title = $media.Title
    artist = $media.Artist
} | ConvertTo-Json -Depth 4 -Compress
