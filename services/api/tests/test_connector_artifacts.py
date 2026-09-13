from __future__ import annotations

import json
from pathlib import Path

from moodmusic_api.connector_protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_CAPABILITIES,
    SUPPORTED_CONNECTOR_TYPES,
)

ROOT = Path(__file__).resolve().parents[3]
EXTENSION = ROOT / "extensions" / "qqmusic-web-connector"
PC_CONNECTOR = ROOT / "connectors" / "qqmusic-pc"


def test_extension_manifest_has_minimum_permissions() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {"activeTab", "storage"}
    assert set(manifest["host_permissions"]) == {
        "http://127.0.0.1:8000/*",
        "https://y.qq.com/*",
    }
    assert manifest["content_scripts"][0]["matches"] == ["https://y.qq.com/*"]


def test_probe_iteration_cannot_read_credentials_or_click_page() -> None:
    source = "\n".join(
        (EXTENSION / name).read_text(encoding="utf-8")
        for name in ["service-worker.js", "content-adapter.js", "popup.js"]
    )

    forbidden = [
        "document.cookie",
        "chrome.cookies",
        "chrome.webRequest",
        "nativeMessaging",
        ".click(",
        "eval(",
        "new Function(",
    ]
    assert all(value not in source for value in forbidden)
    assert '[class*="playlist"]' not in source
    assert '[class*="queue"]' not in source


def test_extension_contract_bundle_matches_protocol_constants() -> None:
    source = (EXTENSION / "connector-contract.js").read_text(encoding="utf-8")

    assert f'PROTOCOL_VERSION = "{PROTOCOL_VERSION}"' in source
    for connector_type in SUPPORTED_CONNECTOR_TYPES:
        assert f'"{connector_type}"' in source
    for capability in SUPPORTED_CAPABILITIES:
        assert f'"{capability}"' in source


def test_pc_com_probe_is_read_only_and_fail_closed() -> None:
    source = (PC_CONNECTOR / "src" / "QQMusicComProbe.cs").read_text(
        encoding="utf-8"
    )
    runner = (ROOT / "scripts" / "probe-qqmusic-com.ps1").read_text(
        encoding="utf-8-sig"
    )

    for query in ["GetCurrentPlaySongID", "GetPlayItemCount", "EnumPlayItemIDs"]:
        assert query in source
    for mutation in ["AddSong", "DeleteSong", "DeleteAll", "SetPlaySequence", ".Play("]:
        assert mutation not in source

    assert "WaitForExit($TimeoutSeconds * 1000)" in runner
    assert "$serverProcess = $null" in runner
    assert '"standaloneReadOnly"' in runner
    assert "serverWasRunning = $serverWasRunning" in runner
    assert "Stop-Process -Id $serverProcess.Id" in runner
    assert "Registry::HKEY_LOCAL_MACHINE\\SOFTWARE\\Classes\\WOW6432Node" in runner


def test_windows_media_session_probe_is_read_only() -> None:
    runner = (ROOT / "scripts" / "probe-windows-media-sessions.ps1").read_text(
        encoding="utf-8-sig"
    )
    worker = (
        ROOT / "scripts" / "probe-windows-media-sessions-worker.ps1"
    ).read_text(encoding="utf-8-sig")

    for query in [
        "GetSessions",
        "GetPlaybackInfo",
        "GetTimelineProperties",
        "TryGetMediaPropertiesAsync",
    ]:
        assert query in worker
    for control in ["TryPlayAsync", "TryPauseAsync", "TrySkipNextAsync"]:
        assert control not in worker

    assert "WaitForExit($TimeoutSeconds * 1000)" in runner
    assert "-WindowStyle Hidden" in runner
    assert 'status = "queryFailed"' in runner


def test_qqmusic_control_has_explicit_action_and_session_allowlists() -> None:
    runner = (ROOT / "scripts" / "control-qqmusic.ps1").read_text(
        encoding="utf-8-sig"
    )
    worker = (ROOT / "scripts" / "control-qqmusic-worker.ps1").read_text(
        encoding="utf-8-sig"
    )

    action_allowlist = 'ValidateSet("Play", "Pause", "Next", "Previous")'
    assert action_allowlist in runner
    assert action_allowlist in worker
    assert 'SourceAppUserModelId -ieq "QQMusic.exe"' in worker
    assert "$qqMusicSessions.Count -ne 1" in worker
    for method in [
        "TryPlayAsync",
        "TryPauseAsync",
        "TrySkipNextAsync",
        "TrySkipPreviousAsync",
    ]:
        assert worker.count(method) == 1
    for forbidden in ["TryStopAsync", "TryChangePlaybackPositionAsync"]:
        assert forbidden not in worker

    assert "WaitForExit($TimeoutSeconds * 1000)" in runner
    assert "-WindowStyle Hidden" in runner
