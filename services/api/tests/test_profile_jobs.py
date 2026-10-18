from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from moodmusic_api.db_models import IndexJob, Song, SongProfile, utc_now
from moodmusic_api.profiles import ProfileJobConflictError, ProfileService


class SessionContext(AbstractAsyncContextManager):
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        return False


def service_with_job(job):
    session = SimpleNamespace(scalar=AsyncMock(return_value=job))
    session.begin = lambda: SessionContext(session)
    database = SimpleNamespace(session_factory=lambda: SessionContext(session))
    return ProfileService(database, None, None), session


@pytest.mark.asyncio
async def test_worker_can_claim_abandoned_running_job_without_losing_progress():
    job = IndexJob(
        id=uuid4(),
        job_type="song-profile",
        status="running",
        total=3,
        completed=1,
        failed=0,
        checkpoint={"completedSongIds": [str(uuid4())]},
        lease_owner=None,
        lease_expires_at=None,
        updated_at=utc_now(),
    )
    service, _ = service_with_job(job)
    assert await service.claim_next_job("new-worker") == job.id
    assert job.lease_owner == "new-worker"
    assert job.lease_expires_at > utc_now()
    assert job.completed == 1
    assert len(job.checkpoint["completedSongIds"]) == 1


@pytest.mark.asyncio
async def test_rebuild_resume_uses_song_ids_even_when_library_changes():
    songs = [Song(id=uuid4(), source_track_id=str(i)) for i in range(3)]
    removed_id = str(uuid4())
    job = IndexJob(
        id=uuid4(),
        status="running",
        total=4,
        completed=2,
        failed=0,
        checkpoint={
            "mode": "rebuild",
            "songIds": [str(song.id) for song in songs] + [removed_id],
            "completedSongIds": [str(songs[0].id), removed_id],
            "skippedSongIds": [],
        },
    )
    service = ProfileService(None, None, None)
    service._get_job_row = AsyncMock(return_value=job)
    service._active_songs = AsyncMock(return_value=songs[1:])
    service._set_job = AsyncMock()
    service._process_batch_resilient = AsyncMock()
    await service.run_job(job.id, lambda: "fake-key")
    processed = service._process_batch_resilient.call_args.args[1]
    assert processed == songs[1:]


@pytest.mark.asyncio
async def test_completed_job_with_skipped_songs_can_be_retried():
    job = IndexJob(
        id=uuid4(),
        status="succeeded",
        completed=2,
        failed=1,
        total=3,
        checkpoint={"skippedSongIds": [str(uuid4())]},
    )
    service, session = service_with_job(job)
    session.get = AsyncMock(return_value=job)
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    service.get_job = AsyncMock(return_value="retried")
    assert await service.retry_job(job.id) == "retried"
    assert job.status == "queued"
    assert job.failed == 0
    assert job.checkpoint["skippedSongIds"] == []


@pytest.mark.asyncio
async def test_old_worker_cannot_persist_after_lease_is_taken_over():
    from moodmusic_api.profiles import ProfileLeaseLostError

    job = IndexJob(
        id=uuid4(),
        status="running",
        lease_owner="new-worker",
        lease_expires_at=utc_now(),
    )
    service, session = service_with_job(job)
    service._lease_owner = "old-worker"
    session.get = AsyncMock(return_value=job)
    session.execute = AsyncMock()
    with pytest.raises(ProfileLeaseLostError):
        await service._persist_batch(job.id, [Song(id=uuid4())], {}, [])
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_retry_rejects_another_active_job_without_resetting_progress():
    job = IndexJob(id=uuid4(), status="failed", completed=2, failed=1, checkpoint={})
    service, session = service_with_job(IndexJob(id=uuid4(), status="running"))
    session.get = AsyncMock(return_value=job)
    session.execute = AsyncMock()
    with pytest.raises(ProfileJobConflictError):
        await service.retry_job(job.id)
    assert job.status == "failed"
    assert job.completed == 2
    assert job.failed == 1


@pytest.mark.asyncio
async def test_inflight_model_response_preserves_new_manual_lock():
    song = Song(id=uuid4())
    job = IndexJob(id=uuid4(), completed=0, checkpoint={})
    service, session = service_with_job(SongProfile(manual_locked=True))
    session.get = AsyncMock(side_effect=[job, song])
    session.execute = AsyncMock()
    session.add = Mock()
    await service._persist_batch(job.id, [song], {}, [[0.0]])
    session.execute.assert_not_called()
    session.add.assert_not_called()
    assert job.completed == 1
    assert job.checkpoint["completedSongIds"] == [str(song.id)]


@pytest.mark.asyncio
@pytest.mark.parametrize("rebuild", [True, False])
async def test_locked_profile_is_excluded_from_both_incremental_and_rebuild(rebuild):
    song = Song(id=uuid4())
    service, session = service_with_job(None)
    session.execute = AsyncMock(return_value=Mock(all=Mock(return_value=[(song.id, "old", True)])))
    service._fingerprint = Mock(return_value="changed")
    assert await service._pending_songs([song], rebuild=rebuild) == []


@pytest.mark.asyncio
async def test_worker_cancels_inflight_runner_when_it_loses_lease(monkeypatch):
    import asyncio

    from moodmusic_api import worker
    from moodmusic_api.profiles import ProfileLeaseLostError

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def run(*args):
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def heartbeat_tick(tasks, timeout):
        await started.wait()
        return set(), tasks

    profiles = SimpleNamespace(run_job=run, renew_lease=AsyncMock(return_value=False))
    monkeypatch.setattr(worker.asyncio, "wait", heartbeat_tick)
    with pytest.raises(ProfileLeaseLostError):
        await worker.execute_claimed_job(profiles, uuid4(), None)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_duplicate_model_profiles_are_rejected_instead_of_silently_overwritten():
    from test_profile_integration import profile_data

    from moodmusic_api.ai_client import InvalidModelResponseError
    from moodmusic_api.models import SongProfileBatch

    class DuplicateModel:
        async def profile_songs(self, api_key, songs):
            value = profile_data("test-track")
            return SongProfileBatch(profiles=[value, value])

    profiles = ProfileService(None, DuplicateModel(), None)
    song = Song(source_track_id="test-track", title="虚构歌曲", artists=[])
    with pytest.raises(InvalidModelResponseError):
        await profiles._request_complete_profiles([song], "fake-key")
