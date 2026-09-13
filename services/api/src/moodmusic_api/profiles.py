from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from .ai_client import (
    DeepSeekModelClient,
    InvalidModelResponseError,
    LocalEmbeddingClient,
    ModelRequestError,
)
from .database import Database
from .db_models import IndexJob, LibraryMembership, Song, SongEmbedding, SongProfile, utc_now
from .library import LIKED_LIBRARY, LibraryDatabaseError
from .models import JobStatus, SongProfileData

PROFILE_SCHEMA_VERSION = "1.0"
PROFILE_PROMPT_VERSION = "1.0"


class ProfileJobNotFoundError(RuntimeError):
    pass


class ProfileJobConflictError(RuntimeError):
    pass


class ProfileService:
    def __init__(
        self,
        database: Database,
        model_client: DeepSeekModelClient,
        embedding_client: LocalEmbeddingClient,
    ) -> None:
        self._database = database
        self._model_client = model_client
        self._embedding_client = embedding_client
        self._batch_size = max(1, min(20, int(os.environ.get("PROFILE_BATCH_SIZE", "8"))))

    async def create_job(self, mode: str) -> JobStatus:
        job_id = uuid.uuid4()
        try:
            async with self._database.session_factory() as session:
                running_job = await session.scalar(
                    select(IndexJob).where(IndexJob.status.in_(["queued", "running"]))
                )
            if running_job is not None:
                raise ProfileJobConflictError("已有画像任务正在运行，请等待它完成。")
            songs = await self._active_songs()
            pending = await self._pending_songs(songs, rebuild=mode == "rebuild")
            async with self._database.session_factory() as session, session.begin():
                session.add(
                    IndexJob(
                        id=job_id,
                        job_type="song-profile",
                        status="queued" if pending else "succeeded",
                        total=len(pending),
                        completed=0,
                        failed=0,
                        checkpoint={"mode": mode, "lastSongId": None},
                        created_at=utc_now(),
                        updated_at=utc_now(),
                    )
                )
        except SQLAlchemyError as exc:
            raise LibraryDatabaseError("无法创建画像任务。") from exc
        return JobStatus(
            jobId=job_id,
            status="queued" if pending else "succeeded",
            total=len(pending),
            completed=0,
            failed=0,
        )

    async def run_job(self, job_id: uuid.UUID, api_key_provider: Callable[[], str]) -> None:
        try:
            job = await self._get_job_row(job_id)
            if job.status == "succeeded":
                return
            await self._set_job(job_id, status="running", last_error=None)
            songs = await self._active_songs()
            pending = await self._pending_songs(
                songs, rebuild=job.checkpoint.get("mode") == "rebuild"
            )
            if job.checkpoint.get("mode") == "rebuild" and job.completed:
                pending = pending[job.completed :]
            for offset in range(0, len(pending), self._batch_size):
                batch = pending[offset : offset + self._batch_size]
                api_key = api_key_provider()
                await self._process_batch_resilient(job_id, batch, api_key)
            finished = await self._get_job_row(job_id)
            summary = (
                f"主体画像已完成，另有 {finished.failed} 首因模型响应格式异常暂时跳过；"
                "可稍后点击重试。"
                if finished.failed
                else None
            )
            await self._set_job(job_id, status="succeeded", last_error=summary)
        except Exception as exc:
            await self._set_job(
                job_id,
                status="failed",
                last_error=str(exc)[:512],
                increment_failed=True,
            )

    async def _process_batch_resilient(
        self,
        job_id: uuid.UUID,
        songs: list[Song],
        api_key: str,
    ) -> None:
        try:
            profiles = await self._request_complete_profiles(songs, api_key)
        except InvalidModelResponseError as exc:
            if len(songs) == 1:
                await self._record_song_failure(job_id, songs[0], str(exc))
                return
            middle = len(songs) // 2
            await self._process_batch_resilient(job_id, songs[:middle], api_key)
            await self._process_batch_resilient(job_id, songs[middle:], api_key)
            return

        descriptions = [profiles[song.source_track_id].semanticDescription for song in songs]
        vectors = await self._embedding_client.embeddings(descriptions)
        await self._persist_batch(job_id, songs, profiles, vectors)

    async def _request_complete_profiles(
        self,
        songs: list[Song],
        api_key: str,
    ) -> dict[str, SongProfileData]:
        expected_ids = {song.source_track_id for song in songs}
        last_error: ModelRequestError | None = None
        for _ in range(2):
            try:
                result = await self._model_client.profile_songs(
                    api_key,
                    [self._song_input(song) for song in songs],
                )
                by_source_id = {profile.sourceTrackId: profile for profile in result.profiles}
                if set(by_source_id) != expected_ids:
                    missing = len(expected_ids - set(by_source_id))
                    unexpected = len(set(by_source_id) - expected_ids)
                    raise InvalidModelResponseError(
                        f"画像响应未完整覆盖批次：缺少 {missing} 首，多出 {unexpected} 首。"
                    )
                return by_source_id
            except ModelRequestError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    async def retry_job(self, job_id: uuid.UUID) -> JobStatus:
        job = await self._get_job_row(job_id)
        if job.status not in {"failed", "queued"}:
            raise ProfileJobConflictError("只有失败或等待中的画像任务可以重试。")
        await self._set_job(job_id, status="queued", last_error=None, reset_failed=True)
        return await self.get_job(job_id)

    async def get_job(self, job_id: uuid.UUID) -> JobStatus:
        job = await self._get_job_row(job_id)
        return JobStatus(
            jobId=job.id,
            status=job.status,
            total=job.total,
            completed=job.completed,
            failed=job.failed,
            lastError=job.last_error,
        )

    async def _active_songs(self) -> list[Song]:
        try:
            async with self._database.session_factory() as session:
                return list(
                    await session.scalars(
                        select(Song)
                        .join(LibraryMembership, LibraryMembership.song_id == Song.id)
                        .where(
                            LibraryMembership.library == LIKED_LIBRARY,
                            LibraryMembership.active.is_(True),
                        )
                        .order_by(Song.id)
                    )
                )
        except SQLAlchemyError as exc:
            raise LibraryDatabaseError("无法读取待画像歌曲。") from exc

    async def _pending_songs(self, songs: list[Song], *, rebuild: bool) -> list[Song]:
        if rebuild or not songs:
            return songs
        try:
            async with self._database.session_factory() as session:
                rows = (
                    await session.execute(
                        select(SongProfile.song_id, SongProfile.source_fingerprint).where(
                            SongProfile.active.is_(True),
                            SongProfile.song_id.in_([song.id for song in songs]),
                        )
                    )
                ).all()
        except SQLAlchemyError as exc:
            raise LibraryDatabaseError("无法检查画像增量状态。") from exc
        fingerprints = {song_id: fingerprint for song_id, fingerprint in rows}
        return [song for song in songs if fingerprints.get(song.id) != self._fingerprint(song)]

    async def _persist_batch(
        self,
        job_id: uuid.UUID,
        songs: list[Song],
        profiles: dict[str, SongProfileData],
        vectors: list[list[float]],
    ) -> None:
        now = utc_now()
        try:
            async with self._database.session_factory() as session, session.begin():
                for song, vector in zip(songs, vectors, strict=True):
                    data = profiles[song.source_track_id]
                    await session.execute(
                        update(SongProfile)
                        .where(SongProfile.song_id == song.id, SongProfile.active.is_(True))
                        .values(active=False)
                    )
                    latest_version = await session.scalar(
                        select(SongProfile.profile_version)
                        .where(SongProfile.song_id == song.id)
                        .order_by(SongProfile.profile_version.desc())
                        .limit(1)
                    )
                    profile = SongProfile(
                        song_id=song.id,
                        profile_version=(latest_version or 0) + 1,
                        schema_version=PROFILE_SCHEMA_VERSION,
                        model_provider="deepseek",
                        model_id=self._model_client.chat_model,
                        prompt_version=PROFILE_PROMPT_VERSION,
                        source_fingerprint=self._fingerprint(song),
                        status="ready",
                        active=True,
                        profile=data.model_dump(mode="json"),
                        semantic_description=data.semanticDescription,
                        confidence=data.confidence,
                        created_at=now,
                    )
                    session.add(profile)
                    await session.flush()
                    description_hash = hashlib.sha256(
                        data.semanticDescription.encode("utf-8")
                    ).hexdigest()
                    session.add(
                        SongEmbedding(
                            profile_id=profile.id,
                            model_provider="local",
                            model_id=self._embedding_client.embedding_model,
                            dimensions=self._embedding_client.embedding_dimensions,
                            source_hash=description_hash,
                            vector=vector,
                            created_at=now,
                        )
                    )
                job = await session.get(IndexJob, job_id, with_for_update=True)
                if job is None:
                    raise ProfileJobNotFoundError("画像任务不存在。")
                job.completed += len(songs)
                job.checkpoint = {**job.checkpoint, "lastSongId": str(songs[-1].id)}
                job.updated_at = now
        except SQLAlchemyError as exc:
            raise LibraryDatabaseError("保存歌曲画像失败。") from exc

    async def _get_job_row(self, job_id: uuid.UUID) -> IndexJob:
        try:
            async with self._database.session_factory() as session:
                job = await session.get(IndexJob, job_id)
        except SQLAlchemyError as exc:
            raise LibraryDatabaseError("无法读取画像任务。") from exc
        if job is None:
            raise ProfileJobNotFoundError("画像任务不存在。")
        return job

    async def _set_job(
        self,
        job_id: uuid.UUID,
        *,
        status: str,
        last_error: str | None,
        increment_failed: bool = False,
        reset_failed: bool = False,
    ) -> None:
        try:
            async with self._database.session_factory() as session, session.begin():
                job = await session.get(IndexJob, job_id, with_for_update=True)
                if job is None:
                    return
                job.status = status
                job.last_error = last_error
                if reset_failed:
                    job.failed = 0
                elif increment_failed:
                    job.failed += 1
                job.updated_at = utc_now()
        except SQLAlchemyError:
            return

    async def _record_song_failure(self, job_id: uuid.UUID, song: Song, error: str) -> None:
        try:
            async with self._database.session_factory() as session, session.begin():
                job = await session.get(IndexJob, job_id, with_for_update=True)
                if job is None:
                    return
                job.failed += 1
                job.checkpoint = {
                    **job.checkpoint,
                    "lastSkippedSongId": str(song.id),
                }
                job.last_error = f"{song.title}：{error}"[:512]
                job.updated_at = utc_now()
        except SQLAlchemyError as exc:
            raise LibraryDatabaseError("记录画像跳过项失败。") from exc

    def _fingerprint(self, song: Song) -> str:
        payload = {
            "title": song.title,
            "artists": song.artists,
            "album": song.album,
            "durationMs": song.duration_ms,
            "schema": PROFILE_SCHEMA_VERSION,
            "prompt": PROFILE_PROMPT_VERSION,
            "chatModel": self._model_client.chat_model,
            "embeddingModel": self._embedding_client.embedding_model,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _song_input(song: Song) -> dict[str, Any]:
        return {
            "sourceTrackId": song.source_track_id,
            "title": song.title,
            "artists": song.artists,
            "album": song.album,
            "durationMs": song.duration_ms,
        }
