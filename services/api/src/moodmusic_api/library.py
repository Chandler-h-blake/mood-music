from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from .database import Database
from .db_models import ImportBatch, LibraryMembership, Song, utc_now
from .models import ArtistPreview, LibrarySong, LibrarySongPage, LibrarySyncResult
from .qqmusic import LikedLibrarySnapshot, QQMusicClient

QQMUSIC_PROVIDER = "qqmusic"
LIKED_LIBRARY = "liked"
IMPORT_SOURCE = "qqmusic-cookie"


class LibraryDatabaseError(RuntimeError):
    """Database work failed without exposing connection details."""


class LibrarySyncInProgressError(RuntimeError):
    """Only one full sync may run in this API process at a time."""


@dataclass(frozen=True)
class PersistCounts:
    inserted: int
    updated: int
    deactivated: int


class LibraryService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._sync_lock = asyncio.Lock()

    async def sync_liked(self, raw_cookie: str, client: QQMusicClient) -> LibrarySyncResult:
        if self._sync_lock.locked():
            raise LibrarySyncInProgressError("已有一次完整同步正在进行，请等待它完成。")

        async with self._sync_lock:
            batch_id = uuid.uuid4()
            await self._create_batch(batch_id)
            try:
                snapshot, _ = await client.fetch_all_liked_songs(raw_cookie)
                counts = await self._persist_snapshot(batch_id, snapshot)
            except Exception as exc:
                await self._mark_failed(batch_id, self._error_code(exc))
                raise

            return LibrarySyncResult(
                runId=batch_id,
                status="completed",
                pagesFetched=snapshot.pages_fetched,
                reportedTotal=snapshot.reported_total,
                fetchedCount=snapshot.fetched_count,
                uniqueCount=len(snapshot.unique_songs),
                insertedCount=counts.inserted,
                updatedCount=counts.updated,
                deactivatedCount=counts.deactivated,
                skippedMissingId=snapshot.skipped_missing_id,
            )

    async def list_liked_songs(self, *, page: int, page_size: int) -> LibrarySongPage:
        try:
            async with self._database.session_factory() as session:
                membership_filter = (
                    LibraryMembership.library == LIKED_LIBRARY,
                    LibraryMembership.active.is_(True),
                )
                total = await session.scalar(
                    select(func.count()).select_from(LibraryMembership).where(*membership_filter)
                )
                rows = (
                    await session.execute(
                        select(Song, LibraryMembership)
                        .join(LibraryMembership, LibraryMembership.song_id == Song.id)
                        .where(*membership_filter)
                        .order_by(Song.title, Song.source_track_id)
                        .offset(page * page_size)
                        .limit(page_size)
                    )
                ).all()
        except SQLAlchemyError as exc:
            raise LibraryDatabaseError("无法读取本地曲库，请检查 PostgreSQL 是否已启动。") from exc

        songs = [
            LibrarySong(
                id=song.id,
                sourceTrackId=song.source_track_id,
                title=song.title,
                artists=[ArtistPreview(name=artist["name"]) for artist in song.artists],
                album=song.album,
                durationMs=song.duration_ms,
                firstSeenAt=membership.first_seen_at,
                lastSeenAt=membership.last_seen_at,
            )
            for song, membership in rows
        ]
        return LibrarySongPage(page=page, pageSize=page_size, total=total or 0, songs=songs)

    async def _create_batch(self, batch_id: uuid.UUID) -> None:
        try:
            async with self._database.session_factory() as session, session.begin():
                session.add(
                    ImportBatch(
                        id=batch_id,
                        source=IMPORT_SOURCE,
                        status="running",
                        pages_fetched=0,
                        fetched_count=0,
                        unique_count=0,
                        inserted_count=0,
                        updated_count=0,
                        deactivated_count=0,
                    )
                )
        except SQLAlchemyError as exc:
            raise LibraryDatabaseError(
                "无法创建同步批次，请检查 PostgreSQL 是否已启动并完成迁移。"
            ) from exc

    async def _persist_snapshot(
        self, batch_id: uuid.UUID, snapshot: LikedLibrarySnapshot
    ) -> PersistCounts:
        now = utc_now()
        try:
            async with self._database.session_factory() as session, session.begin():
                batch = await session.get(ImportBatch, batch_id, with_for_update=True)
                if batch is None:
                    raise LibraryDatabaseError("同步批次不存在。")

                source_ids = [song.sourceTrackId for song in snapshot.unique_songs]
                existing_songs = list(
                    await session.scalars(
                        select(Song).where(
                            Song.provider == QQMUSIC_PROVIDER,
                            Song.source_track_id.in_(source_ids),
                        )
                    )
                )
                songs_by_source_id = {song.source_track_id: song for song in existing_songs}

                inserted = 0
                updated = 0
                for preview in snapshot.unique_songs:
                    song = songs_by_source_id.get(preview.sourceTrackId)
                    artists = [{"name": artist.name} for artist in preview.artists]
                    if song is None:
                        song = Song(
                            provider=QQMUSIC_PROVIDER,
                            source_track_id=preview.sourceTrackId,
                            title=preview.title,
                            artists=artists,
                            album=preview.album,
                            duration_ms=preview.durationMs,
                            playable_state="unknown",
                            metadata_source=IMPORT_SOURCE,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(song)
                        songs_by_source_id[preview.sourceTrackId] = song
                        inserted += 1
                    else:
                        song.title = preview.title
                        song.artists = artists
                        song.album = preview.album
                        song.duration_ms = preview.durationMs
                        song.updated_at = now
                        updated += 1

                await session.flush()
                memberships = list(
                    await session.scalars(
                        select(LibraryMembership).where(LibraryMembership.library == LIKED_LIBRARY)
                    )
                )
                memberships_by_song_id = {
                    membership.song_id: membership for membership in memberships
                }
                current_song_ids = {songs_by_source_id[source_id].id for source_id in source_ids}

                for song_id in current_song_ids:
                    membership = memberships_by_song_id.get(song_id)
                    if membership is None:
                        session.add(
                            LibraryMembership(
                                song_id=song_id,
                                library=LIKED_LIBRARY,
                                active=True,
                                first_seen_at=now,
                                last_seen_at=now,
                                removed_at=None,
                                import_batch_id=batch_id,
                            )
                        )
                    else:
                        membership.active = True
                        membership.last_seen_at = now
                        membership.removed_at = None
                        membership.import_batch_id = batch_id

                deactivated = 0
                for membership in memberships:
                    if membership.active and membership.song_id not in current_song_ids:
                        membership.active = False
                        membership.removed_at = now
                        membership.import_batch_id = batch_id
                        deactivated += 1

                batch.status = "completed"
                batch.completed_at = now
                batch.reported_total = snapshot.reported_total
                batch.pages_fetched = snapshot.pages_fetched
                batch.fetched_count = snapshot.fetched_count
                batch.unique_count = len(snapshot.unique_songs)
                batch.inserted_count = inserted
                batch.updated_count = updated
                batch.deactivated_count = deactivated
                batch.error_code = None
        except LibraryDatabaseError:
            raise
        except SQLAlchemyError as exc:
            raise LibraryDatabaseError("保存完整曲库失败，旧曲库未被修改。") from exc

        return PersistCounts(inserted=inserted, updated=updated, deactivated=deactivated)

    async def _mark_failed(self, batch_id: uuid.UUID, error_code: str) -> None:
        try:
            async with self._database.session_factory() as session, session.begin():
                batch = await session.get(ImportBatch, batch_id)
                if batch is not None:
                    batch.status = "failed"
                    batch.completed_at = utc_now()
                    batch.error_code = error_code
        except SQLAlchemyError:
            return

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, LibraryDatabaseError):
            return "database.failed"
        return "qqmusic.snapshot_failed"
