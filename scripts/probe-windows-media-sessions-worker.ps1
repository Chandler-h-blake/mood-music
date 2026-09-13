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

$sessions = @(
    $manager.GetSessions() | ForEach-Object {
        $session = $_
        $playback = $session.GetPlaybackInfo()
        $timeline = $session.GetTimelineProperties()
        $mediaError = $null
        $media = $null
        try {
            $media = Wait-WindowsRuntimeOperation `
                -Operation $session.TryGetMediaPropertiesAsync() `
                -ResultType $mediaPropertiesType
        } catch {
            $mediaError = $_.Exception.GetType().Name
        }

        [PSCustomObject]@{
            sourceAppId = $session.SourceAppUserModelId
            playbackStatus = $playback.PlaybackStatus.ToString()
            title = if ($null -ne $media) { $media.Title } else { $null }
            artist = if ($null -ne $media) { $media.Artist } else { $null }
            albumTitle = if ($null -ne $media) { $media.AlbumTitle } else { $null }
            positionSeconds = [Math]::Round($timeline.Position.TotalSeconds, 3)
            endSeconds = [Math]::Round($timeline.EndTime.TotalSeconds, 3)
            canPlay = $playback.Controls.IsPlayEnabled
            canPause = $playback.Controls.IsPauseEnabled
            canNext = $playback.Controls.IsNextEnabled
            canPrevious = $playback.Controls.IsPreviousEnabled
            mediaQueryError = $mediaError
        }
    }
)

[PSCustomObject]@{
    sessionCount = $sessions.Count
    sessions = $sessions
} | ConvertTo-Json -Depth 5 -Compress
