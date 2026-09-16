from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from .models import (
    PCPlaybackActionResult,
    PCPlaybackQueueResult,
    PCPlaybackState,
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

    def __init__(
        self,
        catalog: QQMusicClient,
        media: WindowsMediaService,
        *,
        auto_monitor: bool = True,
        monitor_interval_seconds: float = 0.35,
    ) -> None:
        self._catalog = catalog
        self._media = media
        self._lock = asyncio.Lock()
        self._playlist_id: UUID | None = None
        self._songs: list[ResolvedQueueSong] = []
        self._current_index = 0
        self._current_observed = False
        self._queue_active = False
        self._playback_generation = 0
        self._transitioning = False
        self._ignore_mismatch_until = 0.0
        self._natural_transition_armed = False
        self._unexpected_title: str | None = None
        self._unexpected_observations = 0
        self._auto_monitor = auto_monitor
        self._monitor_interval_seconds = monitor_interval_seconds
        self._monitor_task: asyncio.Task[None] | None = None
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
            self._queue_active = True
            self._playback_generation += 1
            self._natural_transition_armed = False
            self._reset_transition_detection()
            observed = await self._run_play_command()
            self._current_observed = observed
            current = self._songs[0]
            result = PCPlaybackQueueResult(
                status="completed" if observed else "acceptedUnconfirmed",
                playlistId=queue.playlistId,
                acceptedCount=len(resolved),
                currentIndex=0,
                sourceTrackId=current.source_track_id,
                title=current.title,
                artist=current.artist,
                observed=observed,
                message=(
                    f"已在 QQ 音乐中开始播放；MoodMusic 将逐首接管这 {len(resolved)} 首歌的顺序。"
                    if observed
                    else (
                        "已向 QQ 音乐提交第一首；MoodMusic 已保存并将逐首接管"
                        f"这 {len(resolved)} 首歌。"
                    )
                ),
            )
        self._ensure_monitor()
        return result

    async def control(self, action: str) -> PCPlaybackActionResult:
        if action not in {"next", "previous"}:
            async with self._lock:
                self._playback_generation += 1
                self._transitioning = True
                if action == "pause":
                    self._natural_transition_armed = False
                try:
                    return await self._media.control(action)
                finally:
                    self._transitioning = False
                    self._ignore_mismatch_until = time.monotonic() + 1.25
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
            self._queue_active = True
            self._playback_generation += 1
            self._natural_transition_armed = False
            self._reset_transition_detection()
            observed = await self._run_play_command()
            self._current_observed = observed
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

    def _ensure_monitor(self) -> None:
        if not self._auto_monitor:
            return
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(), name="qqmusic-managed-queue"
            )

    async def _monitor_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._monitor_interval_seconds)
                try:
                    if self._transitioning:
                        continue
                    observed_generation = self._playback_generation
                    state = await self._media.get_state()
                    if self._transitioning:
                        continue
                    await self._reconcile_player_state(state, observed_generation)
                except (QQMusicPCError, WindowsMediaError, OSError):
                    # A transient media-session or client error must not discard the queue.
                    continue
        except asyncio.CancelledError:
            raise

    async def _reconcile_player_state(
        self,
        state: PCPlaybackState,
        observed_generation: int | None = None,
    ) -> None:
        async with self._lock:
            if self._transitioning:
                return
            if (
                observed_generation is not None
                and observed_generation != self._playback_generation
            ):
                return
            if not self._queue_active or not self._songs or self._playlist_id is None:
                return

            current = self._songs[self._current_index]
            status = state.status
            title = state.title
            if title and self._same_title(title, current.title):
                self._current_observed = True
                self._reset_transition_detection()
                remaining = (
                    state.durationMs - state.positionMs
                    if state.positionMs is not None and state.durationMs is not None
                    else None
                )
                self._natural_transition_armed = bool(
                    status == "playing"
                    and remaining is not None
                    and state.durationMs is not None
                    and state.durationMs > 10_000
                    and 0 <= remaining <= 3_000
                )
                if (
                    self._natural_transition_armed
                    and remaining is not None
                    and remaining <= 500
                ):
                    await self._advance_or_finish(status)
                return

            # Pausing or temporarily losing the Windows media session is not a skip.
            if status in {"paused", "closed", "unavailable"}:
                self._natural_transition_armed = False
                self._reset_transition_detection()
                return

            if time.monotonic() < self._ignore_mismatch_until:
                return

            if status == "stopped":
                position = state.positionMs
                duration = state.durationMs
                if not (
                    self._current_observed
                    and position is not None
                    and duration is not None
                    and duration > 0
                    and duration - position <= 3_000
                ):
                    return
                transition_key = "__finished__"
            elif (
                status == "playing"
                and title
                and self._current_observed
                and self._natural_transition_armed
            ):
                transition_key = title
            elif status == "playing" and title and self._current_observed:
                # An unrelated song outside the natural-end window is interference,
                # not permission to mutate the managed queue position.
                self._playback_generation += 1
                self._current_observed = False
                self._reset_transition_detection()
                self._natural_transition_armed = False
                self._current_observed = await self._run_play_command()
                return
            else:
                return

            if transition_key == self._unexpected_title:
                self._unexpected_observations += 1
            else:
                self._unexpected_title = transition_key
                self._unexpected_observations = 1

            # If QQ Music happened to start the correct later song itself, adopt it
            # without restarting playback. Otherwise issue one exact-song command.
            if title:
                for index in range(self._current_index + 1, len(self._songs)):
                    if self._same_title(title, self._songs[index].title):
                        self._current_index = index
                        self._playback_generation += 1
                        self._current_observed = True
                        self._natural_transition_armed = False
                        self._reset_transition_detection()
                        return

            await self._advance_or_finish(status)

    async def _advance_or_finish(self, status: str) -> None:
        if self._current_index >= len(self._songs) - 1:
            if status == "playing":
                await self._media.control("pause")
            self._queue_active = False
            self._natural_transition_armed = False
            self._reset_transition_detection()
            return

        self._current_index += 1
        self._playback_generation += 1
        self._current_observed = False
        self._natural_transition_armed = False
        self._reset_transition_detection()
        self._current_observed = await self._run_play_command()

    async def _run_play_command(self) -> bool:
        self._transitioning = True
        try:
            return await self._play_current()
        finally:
            self._transitioning = False
            self._ignore_mismatch_until = time.monotonic() + 1.25

    def _reset_transition_detection(self) -> None:
        self._unexpected_title = None
        self._unexpected_observations = 0

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
