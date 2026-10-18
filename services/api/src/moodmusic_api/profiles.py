from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, text, update
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
from .models import JobStatus, ManualProfileUpdate, SongProfileData, SongProfileView

PROFILE_SCHEMA_VERSION = "1.0"
PROFILE_PROMPT_VERSION = "1.0"


def profile_embedding_text(profile: SongProfileData) -> str:
    fields = profile.model_dump(exclude={"sourceTrackId", "confidence", "identitySummary"})
    return json.dumps(fields, ensure_ascii=False, sort_keys=True)


class ProfileJobNotFoundError(RuntimeError):
    pass


class ProfileJobConflictError(RuntimeError):
    pass


class ProfileLeaseLostError(RuntimeError):
    pass


class SongProfileNotFoundError(RuntimeError):
    pass


class SongProfileConflictError(RuntimeError):
    pass


def profile_basis(profile: SongProfile) -> str:
    return (
        "用户人工校正"
        if profile.model_provider == "manual"
        else "模型根据歌名、歌手、专辑和时长推断，未分析歌词或音频"
    )


LEASE_SECONDS = 90
JOB_QUEUE_LOCK = 1397772882


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
        self._lease_owner: str | None = None

    async def create_job(self, mode: str) -> JobStatus:
        job_id = uuid.uuid4()
        try:
            async with self._database.session_factory() as session, session.begin():
                await session.execute(text(f"SELECT pg_advisory_xact_lock({JOB_QUEUE_LOCK})"))
                running_job = await session.scalar(
                    select(IndexJob)
                    .where(
                        IndexJob.job_type == "song-profile",
                        IndexJob.status.in_(["queued", "running"]),
                    )
                    .limit(1)
                )
                if running_job is not None:
                    raise ProfileJobConflictError("已有画像任务正在排队或运行，请等待它完成。")
                songs = await self._active_songs()
                pending = await self._pending_songs(songs, rebuild=mode == "rebuild")
                session.add(
                    IndexJob(
                        id=job_id,
                        job_type="song-profile",
                        status="queued" if pending else "succeeded",
                        total=len(pending),
                        completed=0,
                        failed=0,
                        checkpoint={
                            "mode": mode,
                            "lastSongId": None,
                            "songIds": [str(song.id) for song in pending],
                            "completedSongIds": [],
                            "skippedSongIds": [],
                        },
                        created_at=utc_now(),
                        updated_at=utc_now(),
                    )
                )
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法创建画像任务。") from exc
        return JobStatus(
            jobId=job_id,
            status="queued" if pending else "succeeded",
            total=len(pending),
            completed=0,
            failed=0,
        )

    async def claim_next_job(self, owner: str) -> uuid.UUID | None:
        now = utc_now()
        try:
            async with self._database.session_factory() as session, session.begin():
                job = await session.scalar(
                    select(IndexJob)
                    .where(
                        IndexJob.job_type == "song-profile",
                        or_(
                            IndexJob.status == "queued",
                            (IndexJob.status == "running")
                            & or_(
                                IndexJob.lease_expires_at.is_(None),
                                IndexJob.lease_expires_at <= now,
                            ),
                        ),
                    )
                    .order_by(IndexJob.created_at, IndexJob.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if job is None:
                    return None
                job.status = "running"
                job.lease_owner = owner
                job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
                job.updated_at = now
                self._lease_owner = owner
                return job.id
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法领取画像任务。") from exc

    async def renew_lease(self, job_id: uuid.UUID) -> bool:
        now = utc_now()
        async with self._database.session_factory() as session, session.begin():
            result = await session.execute(
                update(IndexJob)
                .where(
                    IndexJob.id == job_id,
                    IndexJob.status == "running",
                    IndexJob.lease_owner == self._lease_owner,
                    IndexJob.lease_expires_at > now,
                )
                .values(lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), updated_at=now)
            )
            return result.rowcount == 1

    def _check_lease(self, job: IndexJob) -> None:
        if self._lease_owner is not None and (
            job.status != "running"
            or job.lease_owner != self._lease_owner
            or job.lease_expires_at is None
            or job.lease_expires_at <= utc_now()
        ):
            raise ProfileLeaseLostError("画像任务已由其他执行器接管。")

    async def latest_job(self) -> JobStatus | None:
        try:
            async with self._database.session_factory() as session:
                job = await session.scalar(
                    select(IndexJob)
                    .where(IndexJob.job_type == "song-profile")
                    .order_by(
                        IndexJob.updated_at.desc(), IndexJob.created_at.desc(), IndexJob.id.desc()
                    )
                    .limit(1)
                )
                return self._job_status(job) if job else None
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法读取最新画像任务。") from exc

    async def run_job(self, job_id: uuid.UUID, api_key_provider: Callable[[], str]) -> None:
        try:
            job = await self._get_job_row(job_id)
            if job.status == "succeeded":
                return
            self._check_lease(job)
            songs = await self._active_songs()
            if "songIds" in job.checkpoint:
                planned = set(job.checkpoint["songIds"])
                processed = set(job.checkpoint.get("completedSongIds", [])) | set(
                    job.checkpoint.get("skippedSongIds", [])
                )
                pending = [song for song in songs if str(song.id) in planned - processed]
            else:
                rebuild = job.checkpoint.get("mode") == "rebuild"
                pending = await self._pending_songs(songs, rebuild=rebuild)
                # Old checkpoints only stored a count and cannot safely identify skipped songs.
                await self._upgrade_checkpoint(job_id, pending, rebuild=rebuild)
                job = await self._get_job_row(job_id)
            await self._set_job(
                job_id,
                status="running",
                last_error=None,
                total=job.completed + job.failed + len(pending),
            )
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
        except ProfileLeaseLostError:
            raise
        except Exception:
            await self._set_job(
                job_id,
                status="failed",
                last_error="画像任务中断，请检查模型连接和本地服务后重试；已完成歌曲已保存。",
            )

    async def _upgrade_checkpoint(
        self,
        job_id: uuid.UUID,
        pending: list[Song],
        *,
        rebuild: bool,
    ) -> None:
        async with self._database.session_factory() as session, session.begin():
            job = await session.get(IndexJob, job_id, with_for_update=True)
            if job is None:
                raise ProfileJobNotFoundError("画像任务不存在。")
            self._check_lease(job)
            if rebuild:
                job.completed = 0
            job.failed = 0
            job.total = job.completed + len(pending)
            job.checkpoint = {
                **job.checkpoint,
                "songIds": [str(song.id) for song in pending],
                "completedSongIds": [],
                "skippedSongIds": [],
            }

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
                if set(by_source_id) != expected_ids or len(result.profiles) != len(expected_ids):
                    missing = len(expected_ids - set(by_source_id))
                    unexpected = len(set(by_source_id) - expected_ids)
                    raise InvalidModelResponseError(
                        f"画像响应未恰好覆盖批次：缺少 {missing} 首，"
                        f"多出 {unexpected} 首或存在重复。"
                    )
                return by_source_id
            except ModelRequestError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    async def retry_job(self, job_id: uuid.UUID) -> JobStatus:
        try:
            async with self._database.session_factory() as session, session.begin():
                await session.execute(text(f"SELECT pg_advisory_xact_lock({JOB_QUEUE_LOCK})"))
                job = await session.get(IndexJob, job_id, with_for_update=True)
                if job is None:
                    raise ProfileJobNotFoundError("画像任务不存在。")
                if job.status != "failed" and not (job.status == "succeeded" and job.failed):
                    raise ProfileJobConflictError("只有中断或存在失败歌曲的画像任务可以重试。")
                active = await session.scalar(
                    select(IndexJob)
                    .where(
                        IndexJob.job_type == "song-profile",
                        IndexJob.status.in_(["queued", "running"]),
                        IndexJob.id != job_id,
                    )
                    .limit(1)
                )
                if active is not None:
                    raise ProfileJobConflictError("已有其他画像任务正在运行。")
                job.status = "queued"
                job.failed = 0
                job.last_error = None
                job.lease_owner = None
                job.lease_expires_at = None
                job.checkpoint = {**job.checkpoint, "skippedSongIds": []}
                job.updated_at = utc_now()
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法重试画像任务。") from exc
        return await self.get_job(job_id)

    async def get_job(self, job_id: uuid.UUID) -> JobStatus:
        job = await self._get_job_row(job_id)
        return self._job_status(job)

    @staticmethod
    def _job_status(job: IndexJob) -> JobStatus:
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
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法读取待画像歌曲。") from exc

    async def _pending_songs(self, songs: list[Song], *, rebuild: bool) -> list[Song]:
        if not songs:
            return songs
        try:
            async with self._database.session_factory() as session:
                rows = (
                    await session.execute(
                        select(
                            SongProfile.song_id,
                            SongProfile.source_fingerprint,
                            SongProfile.manual_locked,
                        ).where(
                            SongProfile.active.is_(True),
                            SongProfile.song_id.in_([song.id for song in songs]),
                        )
                    )
                ).all()
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法检查画像增量状态。") from exc
        locked = {song_id for song_id, _, manual_locked in rows if manual_locked}
        fingerprints = {song_id: fingerprint for song_id, fingerprint, _ in rows}
        return [
            song
            for song in songs
            if song.id not in locked
            and (rebuild or fingerprints.get(song.id) != self._fingerprint(song))
        ]

    async def get_profile(self, song_id: uuid.UUID) -> SongProfileView | None:
        try:
            async with self._database.session_factory() as session:
                song = await session.get(Song, song_id)
                if song is None:
                    raise SongProfileNotFoundError("歌曲不存在。")
                profile = await session.scalar(
                    select(SongProfile)
                    .where(
                        SongProfile.song_id == song_id,
                        SongProfile.active.is_(True),
                    )
                    .order_by(SongProfile.profile_version.desc())
                    .limit(1)
                )
                return self._profile_view(profile) if profile else None
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法读取歌曲画像。") from exc

    @staticmethod
    def _profile_view(profile: SongProfile) -> SongProfileView:
        return SongProfileView(
            songId=profile.song_id,
            profileVersion=profile.profile_version,
            profile=SongProfileData.model_validate(profile.profile),
            locked=profile.manual_locked,
            basis=profile_basis(profile),
            model=profile.model_id,
            createdAt=profile.created_at,
        )

    async def update_profile(
        self,
        song_id: uuid.UUID,
        update_data: ManualProfileUpdate,
    ) -> SongProfileView:
        current = await self.get_profile(song_id)
        if current is None:
            raise SongProfileNotFoundError("请先建立歌曲画像，再进行人工校正。")
        if current.profileVersion != update_data.expectedVersion:
            raise SongProfileConflictError("画像已更新，请重新打开后再保存。")
        if update_data.profile.sourceTrackId != current.profile.sourceTrackId:
            raise SongProfileConflictError("不能修改画像对应的歌曲身份。")
        description = update_data.profile.semanticDescription
        embedding_text = profile_embedding_text(update_data.profile)
        vector = (await self._embedding_client.embeddings([embedding_text]))[0]
        try:
            async with self._database.session_factory() as session, session.begin():
                song = await session.get(Song, song_id, with_for_update=True)
                if song is None:
                    raise SongProfileNotFoundError("歌曲不存在。")
                previous = await session.scalar(
                    select(SongProfile)
                    .where(
                        SongProfile.song_id == song_id,
                        SongProfile.active.is_(True),
                    )
                    .order_by(SongProfile.profile_version.desc())
                    .limit(1)
                )
                if previous is None or previous.profile_version != update_data.expectedVersion:
                    raise SongProfileConflictError(
                        "画像已更新，请重新打开后再保存，避免覆盖其他修改。"
                    )
                previous.active = False
                now = utc_now()
                profile = SongProfile(
                    song_id=song_id,
                    profile_version=previous.profile_version + 1,
                    schema_version=PROFILE_SCHEMA_VERSION,
                    model_provider="manual",
                    model_id="user",
                    prompt_version=PROFILE_PROMPT_VERSION,
                    source_fingerprint=self._fingerprint(song),
                    status="ready",
                    active=True,
                    profile=update_data.profile.model_dump(mode="json"),
                    semantic_description=description,
                    confidence=update_data.profile.confidence,
                    manual_locked=update_data.locked,
                    created_at=now,
                )
                session.add(profile)
                await session.flush()
                session.add(
                    SongEmbedding(
                        profile_id=profile.id,
                        model_provider="local",
                        model_id=self._embedding_client.embedding_model,
                        dimensions=self._embedding_client.embedding_dimensions,
                        source_hash=hashlib.sha256(embedding_text.encode("utf-8")).hexdigest(),
                        vector=vector,
                        created_at=now,
                    )
                )
                result = self._profile_view(profile)
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("保存人工画像失败，原画像已保留。") from exc
        return result

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
                job = await session.get(IndexJob, job_id, with_for_update=True)
                if job is None:
                    raise ProfileJobNotFoundError("画像任务不存在。")
                self._check_lease(job)
                for song, vector in zip(songs, vectors, strict=True):
                    await session.get(Song, song.id, with_for_update=True)
                    active = await session.scalar(
                        select(SongProfile)
                        .where(
                            SongProfile.song_id == song.id,
                            SongProfile.active.is_(True),
                        )
                        .order_by(SongProfile.profile_version.desc())
                        .limit(1)
                    )
                    if active is not None and active.manual_locked:
                        continue
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
                job.completed += len(songs)
                job.checkpoint = {
                    **job.checkpoint,
                    "lastSongId": str(songs[-1].id),
                    "completedSongIds": [
                        *job.checkpoint.get("completedSongIds", []),
                        *(str(song.id) for song in songs),
                    ],
                }
                job.updated_at = now
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("保存歌曲画像失败。") from exc

    async def _get_job_row(self, job_id: uuid.UUID) -> IndexJob:
        try:
            async with self._database.session_factory() as session:
                job = await session.get(IndexJob, job_id)
        except (SQLAlchemyError, OSError) as exc:
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
        total: int | None = None,
    ) -> None:
        try:
            async with self._database.session_factory() as session, session.begin():
                job = await session.get(IndexJob, job_id, with_for_update=True)
                if job is None:
                    return
                self._check_lease(job)
                job.status = status
                job.last_error = last_error
                if total is not None:
                    job.total = total
                job.updated_at = utc_now()
                if status in {"failed", "succeeded"}:
                    job.lease_owner = None
                    job.lease_expires_at = None
        except (SQLAlchemyError, OSError):
            return

    async def _record_song_failure(self, job_id: uuid.UUID, song: Song, error: str) -> None:
        try:
            async with self._database.session_factory() as session, session.begin():
                job = await session.get(IndexJob, job_id, with_for_update=True)
                if job is None:
                    return
                self._check_lease(job)
                job.failed += 1
                job.checkpoint = {
                    **job.checkpoint,
                    "lastSkippedSongId": str(song.id),
                    "skippedSongIds": [*job.checkpoint.get("skippedSongIds", []), str(song.id)],
                }
                job.last_error = f"{song.title}：{error}"[:512]
                job.updated_at = utc_now()
        except (SQLAlchemyError, OSError) as exc:
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
