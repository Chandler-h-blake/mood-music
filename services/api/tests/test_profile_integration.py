"""Optional PostgreSQL regressions; use an explicitly disposable moodmusic_test database."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from moodmusic_api.ai_client import ModelRequestError
from moodmusic_api.database import Base
from moodmusic_api.db_models import (
    GeneratedPlaylist,
    ImportBatch,
    IndexJob,
    LibraryMembership,
    Song,
    SongEmbedding,
    SongProfile,
    utc_now,
)
from moodmusic_api.library import LibraryDatabaseError
from moodmusic_api.models import (
    EmotionValues,
    ManualProfileUpdate,
    QueueSortCreate,
    SearchIntent,
    SongProfileBatch,
    SongProfileData,
)
from moodmusic_api.profiles import (
    ProfileJobConflictError,
    ProfileLeaseLostError,
    ProfileService,
    SongProfileConflictError,
)
from moodmusic_api.semantic_search import CandidateSetMismatchError, SemanticSearchService

TEST_URL = os.environ.get("MOODMUSIC_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="需要显式配置独立测试数据库")


def profile_data(track_id: str) -> SongProfileData:
    return SongProfileData(
        sourceTrackId=track_id,
        identitySummary="虚构歌曲",
        language="zh",
        vocalType="女声独唱",
        genres=["流行"],
        energy=0.3,
        valence=0.6,
        danceability=0.2,
        acousticness=None,
        emotions=EmotionValues(
            joy=0.5, sadness=0.2, loneliness=0.2, warmth=0.6, hope=0.6, tension=0.1, calm=0.7
        ),
        scenes=["夜晚"],
        themes=[],
        arrangement=[],
        semanticDescription="安静温暖的虚构歌曲",
        confidence=0.4,
    )


class FakeModel:
    chat_model = "test-model"

    async def profile_songs(self, api_key, songs):
        return SongProfileBatch(profiles=[profile_data(song["sourceTrackId"]) for song in songs])

    async def understand_feeling(self, api_key, description):
        return SearchIntent(
            summary="安静温暖",
            semanticQuery="安静温暖的音乐",
            scenes=["夜晚"],
            exclusions=[],
            excludedGenres=[],
            targetEnergy=0.3,
            targetValence=0.6,
            targetDanceability=None,
            maxSadness=None,
            maxTension=None,
            threshold=0.75,
        )


class FakeEmbedding:
    embedding_model = "test-embedding"
    embedding_dimensions = 1024

    async def embeddings(self, texts):
        return [[1.0] + [0.0] * 1023 for _ in texts]


@pytest_asyncio.fixture
async def database():
    assert TEST_URL and TEST_URL.endswith("/moodmusic_test"), "必须使用 moodmusic_test 测试数据库"
    schema_name = "qa_" + uuid4().hex
    admin = create_async_engine(TEST_URL)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    engine = create_async_engine(
        TEST_URL,
        connect_args={
            "server_settings": {"search_path": f"{schema_name},public"},
        },
        execution_options={"schema_translate_map": {None: schema_name}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield SimpleNamespace(session_factory=async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        await admin.dispose()


async def seed(database, count=3):
    async with database.session_factory() as session, session.begin():
        batch = ImportBatch(source="test", status="succeeded")
        session.add(batch)
        await session.flush()
        songs = [
            Song(
                id=uuid4(),
                provider="qqmusic",
                source_track_id=f"fictional-{index}",
                title=f"测试歌曲 {index}",
                artists=[{"name": "测试歌手"}],
                album="测试专辑",
                duration_ms=180000,
            )
            for index in range(count)
        ]
        session.add_all(songs)
        await session.flush()
        session.add_all(
            [
                LibraryMembership(
                    song_id=song.id, library="liked", active=True, import_batch_id=batch.id
                )
                for song in songs
            ]
        )
    return sorted(songs, key=lambda song: song.id)


def service(database):
    return ProfileService(database, FakeModel(), FakeEmbedding())


@pytest.mark.asyncio
async def test_concurrent_job_creation_only_accepts_one_active_job(database):
    await seed(database)
    results = await asyncio.gather(
        service(database).create_job("incremental"),
        service(database).create_job("incremental"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ProfileJobConflictError) for result in results) == 1
    assert sum(not isinstance(result, Exception) for result in results) == 1


@pytest.mark.asyncio
async def test_expired_worker_is_fenced_and_new_worker_resumes_exact_songs(database):
    songs = await seed(database)
    old, new = service(database), service(database)
    job = await old.create_job("rebuild")
    assert await old.claim_next_job("old") == job.jobId
    assert await new.claim_next_job("new") is None
    await old._process_batch_resilient(job.jobId, songs[:1], "fake-key")
    async with database.session_factory() as session, session.begin():
        await session.execute(
            update(IndexJob)
            .where(IndexJob.id == job.jobId)
            .values(
                lease_expires_at=utc_now() - timedelta(seconds=1),
            )
        )
    assert await new.claim_next_job("new") == job.jobId
    assert not await old.renew_lease(job.jobId)
    with pytest.raises(ProfileLeaseLostError):
        await old._process_batch_resilient(job.jobId, songs[1:2], "fake-key")
    await new.run_job(job.jobId, lambda: "fake-key")
    assert (await new.get_job(job.jobId)).completed == 3
    async with database.session_factory() as session:
        profiles = list(await session.scalars(select(SongProfile)))
    assert len(profiles) == 3
    assert {profile.song_id for profile in profiles} == {song.id for song in songs}


@pytest.mark.asyncio
async def test_manual_edit_rebuild_lock_optimistic_conflict_and_history_evidence(database):
    songs = await seed(database, count=1)
    profiles = service(database)
    job = await profiles.create_job("incremental")
    await profiles.claim_next_job("worker")
    await profiles.run_job(job.jobId, lambda: "fake-key")
    # API and worker have separate service instances; API writes do not reuse a worker lease.
    api_profiles = service(database)
    search = SemanticSearchService(database, FakeModel(), FakeEmbedding())
    queue = await search.create_queue("fake-key", "安静温暖")
    assert queue.matchedCount == 1
    assert queue.songs[0].explanation.confidence == 0.4
    current = await api_profiles.get_profile(songs[0].id)
    edited = current.profile.model_copy(update={"energy": 0.1, "confidence": 0.9})
    request = ManualProfileUpdate(profile=edited, expectedVersion=1, locked=True)
    saved = await api_profiles.update_profile(songs[0].id, request)
    assert saved.profileVersion == 2 and saved.locked
    with pytest.raises(SongProfileConflictError):
        await api_profiles.update_profile(songs[0].id, request)
    rebuild = await api_profiles.create_job("rebuild")
    assert rebuild.total == 0
    assert (await search.get_playlist(queue.playlistId)).songs[0].explanation.confidence == 0.4
    new_queue = await search.create_queue("fake-key", "安静温暖")
    assert new_queue.songs[0].explanation.profileVersion == 2
    async with database.session_factory() as session:
        versions = list(
            await session.scalars(select(SongProfile).order_by(SongProfile.profile_version))
        )
        vectors = list(await session.scalars(select(SongEmbedding)))
    assert len(versions) == len(vectors) == 2
    assert not versions[0].active and versions[1].active


@pytest.mark.asyncio
async def test_embedding_failure_keeps_original_manual_profile_and_vector(database):
    songs = await seed(database, count=1)
    profiles = service(database)
    job = await profiles.create_job("incremental")
    await profiles.claim_next_job("worker")
    await profiles.run_job(job.jobId, lambda: "fake-key")
    api_profiles = service(database)
    before = await api_profiles.get_profile(songs[0].id)

    class BrokenEmbedding(FakeEmbedding):
        async def embeddings(self, texts):
            raise ModelRequestError("模拟本地向量失败")

    api_profiles._embedding_client = BrokenEmbedding()
    with pytest.raises(ModelRequestError):
        await api_profiles.update_profile(
            songs[0].id,
            ManualProfileUpdate(
                profile=before.profile.model_copy(update={"energy": 0.1}),
                expectedVersion=before.profileVersion,
                locked=True,
            ),
        )
    assert await api_profiles.get_profile(songs[0].id) == before
    async with database.session_factory() as session:
        assert len(list(await session.scalars(select(SongEmbedding)))) == 1


@pytest.mark.asyncio
async def test_zero_result_explains_missing_profiles_and_hard_exclusion(database):
    songs = await seed(database, count=2)
    profiles = service(database)
    job = await profiles.create_job("incremental")
    await profiles.claim_next_job("worker")
    await profiles._process_batch_resilient(job.jobId, songs[:1], "fake-key")

    class StrictModel(FakeModel):
        async def understand_feeling(self, api_key, description):
            value = await super().understand_feeling(api_key, description)
            return value.model_copy(update={"maxEnergy": 0.1})

    search = SemanticSearchService(database, StrictModel(), FakeEmbedding())
    result = await search.create_queue("fake-key", "能量不要太高")
    assert result.matchedCount == 0
    assert result.diagnostics.libraryCount == 2
    assert result.diagnostics.profiledCount == 1
    assert result.diagnostics.missingProfileCount == 1
    assert result.diagnostics.rejections[0].count == 1
    assert "能量超过" in result.diagnostics.rejections[0].reason


async def searchable_queue(database):
    songs = await seed(database, count=2)
    profiles = service(database)
    job = await profiles.create_job("incremental")
    await profiles.claim_next_job("worker")
    await profiles.run_job(job.jobId, lambda: "fake-key")
    search = SemanticSearchService(database, FakeModel(), FakeEmbedding())
    return songs, search, await search.create_queue("fake-key", "夜晚听歌")


@pytest.mark.asyncio
async def test_failed_delete_does_not_change_candidates_or_current_snapshot(database, monkeypatch):
    _, search, queue = await searchable_queue(database)
    from sqlalchemy import event

    def reject_new_snapshot(mapper, connection, target):
        raise RuntimeError("模拟快照写入失败")

    event.listen(GeneratedPlaylist, "before_insert", reject_new_snapshot)
    try:
        with pytest.raises((LibraryDatabaseError, RuntimeError)):
            await search.remove_candidate(queue.sessionId, queue.songs[0].candidateId)
    finally:
        event.remove(GeneratedPlaylist, "before_insert", reject_new_snapshot)
    sorted_queue = await search.sort_queue(queue.sessionId, QueueSortCreate(mode="match"))
    assert {song.songId for song in sorted_queue.songs} == {song.songId for song in queue.songs}


@pytest.mark.asyncio
async def test_failed_restore_keeps_current_candidate_set(database):
    _, search, original = await searchable_queue(database)
    current = await search.remove_candidate(original.sessionId, original.songs[0].candidateId)
    from sqlalchemy import event

    def reject_new_snapshot(mapper, connection, target):
        raise RuntimeError("模拟快照写入失败")

    event.listen(GeneratedPlaylist, "before_insert", reject_new_snapshot)
    try:
        with pytest.raises((LibraryDatabaseError, RuntimeError)):
            await search.restore_playlist(original.playlistId)
    finally:
        event.remove(GeneratedPlaylist, "before_insert", reject_new_snapshot)
    result = await search.sort_queue(original.sessionId, QueueSortCreate(mode="match"))
    assert {song.songId for song in result.songs} == {song.songId for song in current.songs}


@pytest.mark.asyncio
async def test_sort_rejects_stale_candidate_rows_instead_of_readding_deleted_song(database):
    _, search, original = await searchable_queue(database)
    stale_search, stale_rows = await search._active_candidate_rows(original.sessionId)
    await search.remove_candidate(original.sessionId, original.songs[0].candidateId)
    with pytest.raises(CandidateSetMismatchError):
        await search._persist_playlist(stale_search, stale_rows, sort_mode="manual")


@pytest.mark.asyncio
async def test_successive_refinements_send_each_requirement_once(database):
    _, search, original = await searchable_queue(database)
    descriptions = []

    class RecordingModel(FakeModel):
        async def understand_feeling(self, api_key, description):
            descriptions.append(description)
            return await super().understand_feeling(api_key, description)

    search._model_client = RecordingModel()
    first = await search.refine_queue("fake-key", original.sessionId, "再温暖一点")
    await search.refine_queue("fake-key", first.sessionId, "少一点人声")
    assert descriptions[-1].count("再温暖一点") == 1
    assert descriptions[-1].count("少一点人声") == 1


@pytest.mark.asyncio
async def test_playback_rejects_historical_songs_removed_from_current_likes(database):
    songs, search, queue = await searchable_queue(database)
    async with database.session_factory() as session, session.begin():
        await session.execute(
            update(LibraryMembership)
            .where(
                LibraryMembership.song_id == songs[0].id,
            )
            .values(active=False)
        )
    with pytest.raises(CandidateSetMismatchError):
        await search.validate_playback_queue(queue)
    assert (await search.get_playlist(queue.playlistId)).matchedCount == 2
