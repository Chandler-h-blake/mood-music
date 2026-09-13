from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from .models import (
    PCPlaybackActionResult,
    PCPlaybackQueueResult,
    QueueSong,
    TemporaryQueue,
)
from .qqmusic import QQMusicClient, QQMusicRequestError
from .windows_media import WindowsMediaError, WindowsMediaService


class QQMusicPCError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedQueueSong:
    source_track_id: str
    numeric_id: int
    title: str
    artist: str | None


class QQMusicPCService:
    """Control the installed QQ Music client through its own command entrypoint."""

    def __init__(self, catalog: QQMusicClient, media: WindowsMediaService) -> None:
        self._catalog = catalog
        self._media = media
        self._lock = asyncio.Lock()
        self._playlist_id: UUID | None = None
        self._songs: list[ResolvedQueueSong] = []
        self._current_index = 0
        self.platform = os.name

    async def start_queue(self, queue: TemporaryQueue) -> PCPlaybackQueueResult:
        if not queue.songs:
            raise QQMusicPCError("临时队列为空，无法开始播放。")
        try:
            ids = await self._catalog.resolve_numeric_song_ids(
                [song.sourceTrackId for song in queue.songs]
            )
        except QQMusicRequestError as exc:
            raise QQMusicPCError(str(exc)) from exc

        resolved = [self._resolve_song(song, ids[song.sourceTrackId]) for song in queue.songs]
        async with self._lock:
            self._playlist_id = queue.playlistId
            self._songs = resolved
            self._current_index = 0
            observed = await self._play_current()
            current = self._songs[0]
            return PCPlaybackQueueResult(
                status="completed" if observed else "acceptedUnconfirmed",
                playlistId=queue.playlistId,
                acceptedCount=len(resolved),
                currentIndex=0,
                sourceTrackId=current.source_track_id,
                title=current.title,
                artist=current.artist,
                observed=observed,
                message=(
                    f"已在 QQ 音乐中开始播放，并由后端接管这 {len(resolved)} 首歌的顺序。"
                    if observed
                    else f"已向 QQ 音乐提交第一首；后端已保存这 {len(resolved)} 首歌的顺序。"
                ),
            )

    async def control(self, action: str) -> PCPlaybackActionResult:
        if action not in {"next", "previous"}:
            return await self._media.control(action)
        async with self._lock:
            if not self._songs or self._playlist_id is None:
                return await self._media.control(action)
            target = self._current_index + (1 if action == "next" else -1)
            target = min(max(target, 0), len(self._songs) - 1)
            if target == self._current_index:
                current = self._songs[self._current_index]
                state = await self._media.get_state()
                return PCPlaybackActionResult(
                    status="completed",
                    action=action,
                    accepted=False,
                    observed=True,
                    playbackStatus=state.status,
                    title=current.title,
                    artist=current.artist,
                    message="已经到达 MoodMusic 临时队列的边界。",
                )
            self._current_index = target
            observed = await self._play_current()
            current = self._songs[self._current_index]
            return PCPlaybackActionResult(
                status="completed" if observed else "acceptedUnconfirmed",
                action=action,
                accepted=True,
                observed=observed,
                playbackStatus="playing" if observed else "unavailable",
                title=current.title,
                artist=current.artist,
                message=(
                    "已按 MoodMusic 临时队列切换歌曲。"
                    if observed
                    else "已提交队列切歌命令，但尚未从媒体状态确认。"
                ),
            )

    async def _play_current(self) -> bool:
        song = self._songs[self._current_index]
        executable = await asyncio.to_thread(self._find_executable)
        argument = f"cmd_count==1&&id_0=={song.numeric_id}&&songtype_0==0"
        try:
            await asyncio.to_thread(
                subprocess.Popen,
                [str(executable), "/playbysongid", argument],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise QQMusicPCError("无法调用本机 QQ 音乐播放入口。") from exc

        for _ in range(10):
            await asyncio.sleep(0.4)
            try:
                state = await self._media.get_state()
            except WindowsMediaError:
                continue
            if state.status == "playing" and self._same_title(state.title, song.title):
                return True
        return False

    def _find_executable(self) -> Path:
        if self.platform != "nt":
            raise QQMusicPCError("QQ 音乐 PC 连接器仅支持 Windows。")
        override = os.environ.get("QQMUSIC_EXE")
        if override:
            candidate = Path(override).resolve()
            if candidate.is_file() and candidate.name.lower() == "qqmusic.exe":
                return candidate
            raise QQMusicPCError("QQMUSIC_EXE 指向的不是有效 QQMusic.exe。")

        running = self._running_process_path("QQMusic.exe")
        if running is not None:
            return running
        candidates = [
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Tencent" / "QQMusic" / "QQMusic.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Tencent" / "QQMusic" / "QQMusic.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "QQMusic" / "QQMusic.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        raise QQMusicPCError("没有找到 QQMusic.exe；请先启动 QQ 音乐或设置 QQMUSIC_EXE。")

    @staticmethod
    def _running_process_path(process_name: str) -> Path | None:
        # Toolhelp and QueryFullProcessImageName only inspect process metadata.
        if os.name != "nt":
            return None
        from ctypes import wintypes

        class ProcessEntry32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            return None
        entry = ProcessEntry32(dwSize=ctypes.sizeof(ProcessEntry32))
        try:
            has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while has_entry:
                if entry.szExeFile.lower() == process_name.lower():
                    handle = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)
                    if handle:
                        try:
                            buffer = ctypes.create_unicode_buffer(32768)
                            size = wintypes.DWORD(len(buffer))
                            if kernel32.QueryFullProcessImageNameW(
                                handle, 0, buffer, ctypes.byref(size)
                            ):
                                path = Path(buffer.value)
                                if path.is_file():
                                    return path.resolve()
                        finally:
                            kernel32.CloseHandle(handle)
                has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return None

    @staticmethod
    def _resolve_song(song: QueueSong, numeric_id: int) -> ResolvedQueueSong:
        return ResolvedQueueSong(
            source_track_id=song.sourceTrackId,
            numeric_id=numeric_id,
            title=song.title,
            artist=" / ".join(artist.name for artist in song.artists) or None,
        )

    @staticmethod
    def _same_title(actual: str | None, expected: str) -> bool:
        if actual is None:
            return False
        def normalize(value: str) -> str:
            return "".join(value.casefold().split())

        return normalize(actual) == normalize(expected)
