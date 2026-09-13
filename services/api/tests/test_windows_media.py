from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from moodmusic_api.windows_media import WindowsMediaService


def prepare_service(tmp_path: Path, script_name: str) -> WindowsMediaService:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / script_name).touch()
    powershell = tmp_path / "powershell.exe"
    powershell.touch()
    service = WindowsMediaService()
    service.platform = "nt"
    service.root = tmp_path
    service.powershell = powershell
    return service


def completed(payload: dict[str, object]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps(payload, ensure_ascii=False).encode(),
        stderr=b"",
    )


@pytest.mark.asyncio
async def test_get_state_normalizes_qqmusic_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = prepare_service(tmp_path, "probe-windows-media-sessions-worker.ps1")
    monkeypatch.setattr(
        "moodmusic_api.windows_media.subprocess.run",
        lambda *args, **kwargs: completed(
            {
                "sessionCount": 1,
                "sessions": [
                    {
                            "sourceAppId": "QQMusic.exe",
                            "playbackStatus": "Playing",
                            "title": "夜空中最亮的星",
                            "artist": "逃跑计划",
                            "albumTitle": "世界",
                            "positionSeconds": 12.345,
                            "endSeconds": 252.5,
                            "canPlay": False,
                            "canPause": True,
                            "canNext": True,
                            "canPrevious": True,
                    }
                ],
            }
        ),
    )

    state = await service.get_state()

    assert state.status == "playing"
    assert state.title == "夜空中最亮的星"
    assert state.positionMs == 12345
    assert state.durationMs == 252500
    assert state.canPause is True


@pytest.mark.asyncio
async def test_control_preserves_unconfirmed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = prepare_service(tmp_path, "control-qqmusic-worker.ps1")
    captured: list[str] | None = None

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal captured
        captured = args
        assert "shell" not in kwargs
        return completed(
            {
                "accepted": True,
                "observed": False,
                "afterStatus": "Stopped",
                "title": "示例歌曲",
                "artist": "示例歌手",
            }
        )

    monkeypatch.setattr("moodmusic_api.windows_media.subprocess.run", fake_run)

    result = await service.control("next")

    assert result.status == "acceptedUnconfirmed"
    assert result.observed is False
    assert result.playbackStatus == "stopped"
    assert captured is not None
    assert captured[-2:] == ["-Action", "Next"]
