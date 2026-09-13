from __future__ import annotations

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
    service = QQMusicPCService(FakeCatalog(), media)  # type: ignore[arg-type]
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
    service = QQMusicPCService(FakeCatalog(), media)  # type: ignore[arg-type]
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
    service = QQMusicPCService(FakeCatalog(), FakeMedia())  # type: ignore[arg-type]
    service.platform = "nt"
    monkeypatch.setenv("QQMUSIC_EXE", str(tmp_path / "not-qqmusic.exe"))

    with pytest.raises(QQMusicPCError, match="QQMUSIC_EXE"):
        service._find_executable()


async def _done() -> None:
    return None


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
