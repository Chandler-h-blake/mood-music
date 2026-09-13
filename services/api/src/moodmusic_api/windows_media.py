from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .models import PCPlaybackActionResult, PCPlaybackState


class WindowsMediaError(RuntimeError):
    pass


class WindowsMediaService:
    _action_names = {
        "play": "Play",
        "pause": "Pause",
        "next": "Next",
        "previous": "Previous",
    }

    def __init__(self, *, timeout_seconds: float = 15) -> None:
        self.timeout_seconds = timeout_seconds
        self.platform = os.name
        self.root = Path(__file__).resolve().parents[4]
        self.powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / (
            r"System32\WindowsPowerShell\v1.0\powershell.exe"
        )

    async def get_state(self) -> PCPlaybackState:
        payload = await self._run_script("probe-windows-media-sessions-worker.ps1")
        if payload.get("sessionCount") == 0:
            return PCPlaybackState(status="closed", message="QQ 音乐当前没有媒体会话。")

        sessions = payload.get("sessions", [])
        qq_sessions = [
            session for session in sessions if session.get("sourceAppId") == "QQMusic.exe"
        ]
        if len(qq_sessions) != 1:
            state = "closed" if not qq_sessions else "unavailable"
            return PCPlaybackState(
                status=state,
                message="未找到唯一可控制的 QQ 音乐媒体会话。",
            )
        session = qq_sessions[0]
        return PCPlaybackState(
            status=self._normalize_status(session.get("playbackStatus")),
            title=session.get("title"),
            artist=session.get("artist"),
            album=session.get("albumTitle"),
            positionMs=self._seconds_to_ms(session.get("positionSeconds")),
            durationMs=self._seconds_to_ms(session.get("endSeconds")),
            canPlay=bool(session.get("canPlay")),
            canPause=bool(session.get("canPause")),
            canNext=bool(session.get("canNext")),
            canPrevious=bool(session.get("canPrevious")),
            message="已通过 Windows 媒体 API 读取 QQ 音乐播放状态。",
        )

    async def control(self, action: str) -> PCPlaybackActionResult:
        script_action = self._action_names[action]
        result = await self._run_script(
            "control-qqmusic-worker.ps1", "-Action", script_action
        )
        status = "completed" if result.get("observed") else "acceptedUnconfirmed"
        return PCPlaybackActionResult(
            status=status,
            action=action,
            accepted=bool(result.get("accepted")),
            observed=bool(result.get("observed")),
            playbackStatus=self._normalize_status(result.get("afterStatus")),
            title=result.get("title"),
            artist=result.get("artist"),
            message=(
                "已确认 QQ 音乐完成控制动作。"
                if result.get("observed")
                else "Windows 已接收命令，但尚未确认 QQ 音乐完成动作。"
            ),
        )

    async def _run_script(self, script_name: str, *arguments: str) -> dict[str, Any]:
        if self.platform != "nt":
            raise WindowsMediaError("QQ 音乐 PC 控制仅支持 Windows。")
        script = self.root / "scripts" / script_name
        if not self.powershell.is_file() or not script.is_file():
            raise WindowsMediaError("QQ 音乐 PC 控制组件不完整。")
        command = [
            str(self.powershell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *arguments,
        ]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise WindowsMediaError("QQ 音乐没有及时响应后端控制。") from exc
        except OSError as exc:
            raise WindowsMediaError("无法启动 Windows 媒体控制组件。") from exc
        if completed.returncode != 0:
            errors = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
            detail = errors[-1] if errors else "Windows 媒体控制组件运行失败。"
            raise WindowsMediaError(detail[:300])
        try:
            return json.loads(completed.stdout.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WindowsMediaError("Windows 媒体控制组件返回了无效结果。") from exc

    @staticmethod
    def _normalize_status(value: object) -> str:
        return {
            "Playing": "playing",
            "Paused": "paused",
            "Stopped": "stopped",
            "Closed": "closed",
        }.get(str(value), "unavailable")

    @staticmethod
    def _seconds_to_ms(value: object) -> int | None:
        if not isinstance(value, (int, float)):
            return None
        return max(0, round(value * 1000))
