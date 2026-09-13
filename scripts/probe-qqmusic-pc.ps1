[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$result = [ordered]@{
    connectorType = "pc"
    probeVersion = "1.0"
    status = "notRunning"
    processFound = $false
    processCount = 0
    mainWindowAvailable = $false
    targetAppVersion = $null
    uiAutomationAvailable = $false
    capabilities = @()
    diagnostics = [ordered]@{
        totalControls = 0
        searchControlMatches = 0
        playbackControlMatches = 0
        queueControlMatches = 0
    }
    message = "未检测到正在运行的 QQ 音乐 PC 客户端。"
}

try {
    $processes = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -match "^(QQMusic|QQMusicHelper|QQMusicExternal)$"
    })
    $result.processCount = $processes.Count
    $result.processFound = $processes.Count -gt 0
    if (-not $result.processFound) {
        $result | ConvertTo-Json -Depth 5
        exit 0
    }

    $target = $processes | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($null -eq $target) {
        $result.status = "degraded"
        $result.message = "检测到 QQ 音乐进程，但没有可访问的主窗口。"
        $result | ConvertTo-Json -Depth 5
        exit 0
    }

    $result.mainWindowAvailable = $true
    try {
        $result.targetAppVersion = $target.MainModule.FileVersionInfo.FileVersion
    } catch {
        $result.targetAppVersion = "unknown"
    }

    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $root = [System.Windows.Automation.AutomationElement]::FromHandle(
        [IntPtr]$target.MainWindowHandle
    )
    if ($null -eq $root) {
        throw "UI Automation 无法读取 QQ 音乐主窗口。"
    }

    $elements = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition
    )
    $result.uiAutomationAvailable = $true
    $result.diagnostics.totalControls = $elements.Count

    $searchMatches = 0
    $playbackMatches = 0
    $queueMatches = 0
    foreach ($element in $elements) {
        try {
            $metadata = "$($element.Current.Name) $($element.Current.AutomationId) $($element.Current.ClassName)".ToLowerInvariant()
            $controlType = $element.Current.ControlType
            if (
                $controlType -eq [System.Windows.Automation.ControlType]::Edit -and
                $metadata -match "搜索|search"
            ) {
                $searchMatches++
            }
            if (
                $controlType -eq [System.Windows.Automation.ControlType]::Button -and
                $metadata -match "播放|暂停|上一首|下一首|play|pause|previous|next"
            ) {
                $playbackMatches++
            }
            if ($metadata -match "播放列表|队列|playlist|queue") {
                $queueMatches++
            }
        } catch {
            continue
        }
    }

    $result.diagnostics.searchControlMatches = $searchMatches
    $result.diagnostics.playbackControlMatches = $playbackMatches
    $result.diagnostics.queueControlMatches = $queueMatches
    $capabilities = @()
    if ($searchMatches -eq 1) { $capabilities += "catalog.search" }
    if ($playbackMatches -gt 0) { $capabilities += "playback.control" }
    if ($searchMatches -eq 1 -and $queueMatches -gt 0) { $capabilities += "queue.play" }
    $result.capabilities = $capabilities
    $result.status = if ($capabilities.Count -gt 0) { "probeReady" } else { "degraded" }
    $result.message = if ($capabilities.Count -gt 0) {
        "发现可进一步验证的 PC 控件能力；尚未执行点击或播放。"
    } else {
        "窗口可访问，但没有发现足够稳定的语义化控件。"
    }
} catch {
    $result.status = "probeFailed"
    $result.message = $_.Exception.Message
}

$result | ConvertTo-Json -Depth 5
