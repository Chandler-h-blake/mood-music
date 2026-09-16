from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from moodmusic_api.main import create_app, get_qqmusic_pc_service, get_semantic_search_service
from moodmusic_api.models import (
    ArtistPreview,
    PCPlaybackQueueResult,
    PCPlaybackState,
    QueueSong,
    SearchIntent,
    TemporaryQueue,
)
from moodmusic_api.qqmusic_pc import QQMusicPCError, QQMusicPCService


class FakeCatalog:
    async def resolve_numeric_song_ids(self, mids: list[str]) -> dict[str, int]:
        return {mid: index + 100 for index, mid in enumerate(mids)}


class FakeMedia:
    def __init__(self) -> None:
        self.title = "第一首"

    async def get_state(self) -> PCPlaybackState:
        return PCPlaybackState(status="playing", title=self.title, message="ok")


def queue() -> TemporaryQueue:
    songs = [
        QueueSong(
            candidateId=uuid4(),
            songId=uuid4(),
            sourceTrackId=mid,
            title=title,
            artists=[ArtistPreview(name="歌手")],
            album=None,
            score=0.9,
            semanticScore=0.9,
            featureScore=0.9,
        )
        for mid, title in [("00000000000001", "第一首"), ("00000000000002", "第二首")]
    ]
    return TemporaryQueue(
        sessionId=uuid4(),
        playlistId=uuid4(),
        name="测试队列",
        description="测试",
        intent=SearchIntent(
            summary="测试",
            semanticQuery="测试",
            scenes=[],
            exclusions=[],
            excludedGenres=[],
            targetEnergy=None,
            targetValence=None,
            targetDanceability=None,
            maxSadness=None,
            maxTension=None,
            threshold=0.56,
        ),
        candidateSetHash="hash",
        evaluatedCount=2,
        matchedCount=2,
        songs=songs,
    )


@pytest.mark.asyncio
async def test_start_queue_uses_exact_client_command_without_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "QQMusic.exe"
    executable.touch()
    media = FakeMedia()
    service = QQMusicPCService(FakeCatalog(), media, auto_monitor=False)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_find_executable", lambda: executable)
    monkeypatch.setattr("moodmusic_api.qqmusic_pc.asyncio.sleep", lambda _: _done())
    captured: list[object] = []

    def fake_popen(command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        captured.extend([command, kwargs])
        return object()  # type: ignore[return-value]

    monkeypatch.setattr("moodmusic_api.qqmusic_pc.subprocess.Popen", fake_popen)

    result = await service.start_queue(queue())

    assert result.status == "completed"
    assert result.acceptedCount == 2
    command = captured[0]
    kwargs = captured[1]
    assert command == [
        str(executable),
        "/playbysongid",
        "cmd_count==1&&id_0==100&&songtype_0==0",
    ]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False


@pytest.mark.asyncio
async def test_next_uses_backend_queue_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "QQMusic.exe"
    executable.touch()
    media = FakeMedia()
    service = QQMusicPCService(FakeCatalog(), media, auto_monitor=False)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_find_executable", lambda: executable)
    monkeypatch.setattr("moodmusic_api.qqmusic_pc.asyncio.sleep", lambda _: _done())
    commands: list[list[str]] = []

    def fake_popen(command: list[str], **_: object) -> subprocess.Popen[bytes]:
        commands.append(command)
        if "id_0==101" in command[-1]:
            media.title = "第二首"
        return object()  # type: ignore[return-value]

    monkeypatch.setattr("moodmusic_api.qqmusic_pc.subprocess.Popen", fake_popen)
    await service.start_queue(queue())

    result = await service.control("next")

    assert result.status == "completed"
    assert result.title == "第二首"
    assert commands[-1][-1] == "cmd_count==1&&id_0==101&&songtype_0==0"


def test_invalid_executable_override_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = QQMusicPCService(FakeCatalog(), FakeMedia(), auto_monitor=False)  # type: ignore[arg-type]
    service.platform = "nt"
    monkeypatch.setenv("QQMUSIC_EXE", str(tmp_path / "not-qqmusic.exe"))

    with pytest.raises(QQMusicPCError, match="QQMUSIC_EXE"):
        service._find_executable()


async def _done() -> None:
    return None


@pytest.mark.asyncio
async def test_unexpected_native_song_restores_current_managed_song(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QQMusicPCService(FakeCatalog(), FakeMedia(), auto_monitor=False)  # type: ignore[arg-type]
    selected = queue()
    service._playlist_id = selected.playlistId
    service._songs = [
        service._resolve_song(song, index + 100)
        for index, song in enumerate(selected.songs)
    ]
    service._queue_active = True
    service._current_observed = True
    played: list[str] = []

    async def fake_play_current() -> bool:
        played.append(service._songs[service._current_index].title)
        return True

    monkeypatch.setattr(service, "_play_current", fake_play_current)
    changed = PCPlaybackState(status="playing", title="QQ 音乐原队列中的歌", message="ok")

    await service._reconcile_player_state(changed)

    assert service._current_index == 0
    assert played == ["第一首"]


@pytest.mark.asyncio
async def test_pause_does_not_advance_managed_queue() -> None:
    service = QQMusicPCService(FakeCatalog(), FakeMedia(), auto_monitor=False)  # type: ignore[arg-type]
    selected = queue()
    service._playlist_id = selected.playlistId
    service._songs = [
        service._resolve_song(song, index + 100)
        for index, song in enumerate(selected.songs)
    ]
    service._queue_active = True
    service._current_observed = True
    service._natural_transition_armed = True

    paused = PCPlaybackState(status="paused", title="第一首", message="ok")
    await service._reconcile_player_state(paused)
    await service._reconcile_player_state(paused)

    assert service._current_index == 0


@pytest.mark.asyncio
async def test_native_autoplay_is_paused_after_last_managed_song() -> None:
    media = FakeMedia()
    actions: list[str] = []

    async def fake_control(action: str) -> object:
        actions.append(action)
        return object()

    media.control = fake_control  # type: ignore[method-assign]
    service = QQMusicPCService(FakeCatalog(), media, auto_monitor=False)  # type: ignore[arg-type]
    selected = queue()
    service._playlist_id = selected.playlistId
    service._songs = [service._resolve_song(selected.songs[-1], 101)]
    service._queue_active = True
    service._current_observed = True
    service._natural_transition_armed = True

    changed = PCPlaybackState(status="playing", title="QQ 音乐自动推荐", message="ok")
    await service._reconcile_player_state(changed)

    assert actions == ["pause"]
    assert service._queue_active is False


@pytest.mark.asyncio
async def test_near_end_advances_before_native_queue_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QQMusicPCService(FakeCatalog(), FakeMedia(), auto_monitor=False)  # type: ignore[arg-type]
    selected = queue()
    service._playlist_id = selected.playlistId
    service._songs = [
        service._resolve_song(song, index + 100)
        for index, song in enumerate(selected.songs)
    ]
    service._queue_active = True
    service._current_observed = True
    played: list[str] = []

    async def fake_play_current() -> bool:
        played.append(service._songs[service._current_index].title)
        return True

    monkeypatch.setattr(service, "_play_current", fake_play_current)
    near_end = PCPlaybackState(
        status="playing",
        title="第一首",
        positionMs=199_700,
        durationMs=200_000,
        message="ok",
    )

    await service._reconcile_player_state(near_end)

    assert service._current_index == 1
    assert played == ["第二首"]


@pytest.mark.asyncio
async def test_stale_monitor_state_does_not_skip_after_explicit_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QQMusicPCService(FakeCatalog(), FakeMedia(), auto_monitor=False)  # type: ignore[arg-type]
    selected = queue()
    service._playlist_id = selected.playlistId
    service._songs = [
        service._resolve_song(song, index + 100)
        for index, song in enumerate(selected.songs)
    ]
    service._queue_active = True
    service._current_observed = True
    service._playback_generation = 1
    played: list[str] = []

    async def fake_play_current() -> bool:
        played.append(service._songs[service._current_index].title)
        return True

    monkeypatch.setattr(service, "_play_current", fake_play_current)
    stale_generation = service._playback_generation
    service._current_index = 1
    service._playback_generation += 1
    stale_state = PCPlaybackState(
        status="playing",
        title="第一首",
        message="切歌前取得的旧状态",
    )

    await service._reconcile_player_state(stale_state, stale_generation)

    assert service._current_index == 1
    assert played == []


@pytest.mark.asyncio
async def test_observation_taken_during_explicit_next_cannot_stop_or_skip_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QQMusicPCService(FakeCatalog(), FakeMedia(), auto_monitor=False)  # type: ignore[arg-type]
    selected = queue()
    service._playlist_id = selected.playlistId
    service._songs = [
        service._resolve_song(song, index + 100)
        for index, song in enumerate(selected.songs)
    ]
    service._queue_active = True
    service._current_observed = True
    command_started = asyncio.Event()
    release_command = asyncio.Event()

    async def slow_play_current() -> bool:
        command_started.set()
        await release_command.wait()
        return True

    monkeypatch.setattr(service, "_play_current", slow_play_current)
    control_task = asyncio.create_task(service.control("next"))
    await command_started.wait()
    captured_generation = service._playback_generation
    stale_state = PCPlaybackState(status="playing", title="第一首", message="旧状态")
    reconcile_task = asyncio.create_task(
        service._reconcile_player_state(stale_state, captured_generation)
    )
    release_command.set()

    result, _ = await asyncio.gather(control_task, reconcile_task)

    assert result.title == "第二首"
    assert service._current_index == 1
    assert service._queue_active is True


@pytest.mark.asyncio
async def test_playback_queue_http_endpoint_uses_persisted_snapshot() -> None:
    selected_queue = queue()

    class FakeSearch:
        async def get_playlist(self, playlist_id: object) -> TemporaryQueue | None:
            assert playlist_id == selected_queue.playlistId
            return selected_queue

    class FakePC:
        async def start_queue(self, value: TemporaryQueue) -> PCPlaybackQueueResult:
            assert value is selected_queue
            first = value.songs[0]
            return PCPlaybackQueueResult(
                status="completed",
                playlistId=value.playlistId,
                acceptedCount=len(value.songs),
                currentIndex=0,
                sourceTrackId=first.sourceTrackId,
                title=first.title,
                artist=first.artists[0].name,
                observed=True,
                message="ok",
            )

    app = create_app()
    app.dependency_overrides[get_semantic_search_service] = FakeSearch
    app.dependency_overrides[get_qqmusic_pc_service] = FakePC
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/playback/queues",
            json={"playlistId": str(selected_queue.playlistId)},
        )

    assert response.status_code == 200
    assert response.json()["title"] == "第一首"
    assert response.json()["acceptedCount"] == 2
