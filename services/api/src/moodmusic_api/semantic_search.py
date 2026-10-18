from __future__ import annotations

import hashlib
import math
import random
import secrets
import uuid
from collections import Counter

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .ai_client import DeepSeekModelClient, LocalEmbeddingClient
from .database import Database
from .db_models import (
    GeneratedPlaylist,
    LibraryMembership,
    PlaylistItem,
    SearchCandidate,
    SearchSession,
    Song,
    SongEmbedding,
    SongProfile,
    utc_now,
)
from .library import LIKED_LIBRARY, LibraryDatabaseError
from .models import (
    ArtistPreview,
    CandidateExplanation,
    EmotionCurve,
    PlaylistHistoryPage,
    PlaylistSummary,
    QueueSong,
    QueueSortCreate,
    RejectionSummary,
    SearchDiagnostics,
    SearchIntent,
    TemporaryQueue,
)
from .profiles import profile_basis
from .tag_normalizer import (
    apply_explicit_intent_rules,
    normalize_genres,
    normalize_language,
    normalize_profile_vocal_mode,
    vocal_label,
)


class NoProfilesError(RuntimeError):
    pass


class SearchSessionNotFoundError(RuntimeError):
    pass


class CandidateNotFoundError(RuntimeError):
    pass


class CandidateSetMismatchError(RuntimeError):
    pass


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def score_profile(
    intent: SearchIntent, profile: dict, query_vector: list[float], song_vector: list[float]
) -> tuple[float, float, float, str | None]:
    genres = normalize_genres(profile.get("genres", []))
    excluded = normalize_genres(intent.excludedGenres)
    if excluded and not genres:
        return 0.0, 0.0, 0.0, "画像缺少流派证据，无法验证明确排除项"
    overlap = genres & excluded
    if overlap:
        return 0.0, 0.0, 0.0, f"排除流派：{next(iter(overlap))}"

    vocal_mode = normalize_profile_vocal_mode(profile)
    if vocal_mode is None and (intent.excludedVocalModes or intent.instrumentalAllowed is False):
        return 0.0, 0.0, 0.0, "画像缺少人声类型，无法验证明确排除项"
    if intent.requiredVocalModes:
        if vocal_mode is None:
            return 0.0, 0.0, 0.0, "画像缺少人声类型，无法验证明确要求"
        if vocal_mode not in intent.requiredVocalModes:
            return 0.0, 0.0, 0.0, f"人声类型不符合要求：{vocal_label(vocal_mode)}"
    if vocal_mode in intent.excludedVocalModes:
        return 0.0, 0.0, 0.0, f"排除人声类型：{vocal_label(vocal_mode)}"
    if intent.instrumentalAllowed is False and vocal_mode == "instrumental":
        return 0.0, 0.0, 0.0, "明确要求有人声，排除纯音乐"

    language = normalize_language(profile.get("language"))
    if language is None and intent.excludedLanguages:
        return 0.0, 0.0, 0.0, "画像缺少语言，无法验证明确排除项"
    if intent.allowedLanguages:
        if language is None:
            return 0.0, 0.0, 0.0, "画像缺少语言，无法验证明确要求"
        if language not in intent.allowedLanguages:
            return 0.0, 0.0, 0.0, f"演唱语言不符合要求：{language}"
    if language in intent.excludedLanguages:
        return 0.0, 0.0, 0.0, f"排除演唱语言：{language}"

    emotions = profile.get("emotions") or {}
    sadness = emotions.get("sadness")
    tension = emotions.get("tension")
    if intent.maxSadness is not None:
        if sadness is None:
            return 0.0, 0.0, 0.0, "画像缺少悲伤强度，无法验证明确上限"
        if sadness > intent.maxSadness:
            return 0.0, 0.0, 0.0, "悲伤强度超过明确上限"
    if intent.maxTension is not None:
        if tension is None:
            return 0.0, 0.0, 0.0, "画像缺少紧张强度，无法验证明确上限"
        if tension > intent.maxTension:
            return 0.0, 0.0, 0.0, "紧张强度超过明确上限"
    energy = profile.get("energy")
    if intent.maxEnergy is not None:
        if energy is None:
            return 0.0, 0.0, 0.0, "画像缺少能量值，无法验证明确上限"
        if energy > intent.maxEnergy:
            return 0.0, 0.0, 0.0, "能量超过明确上限"

    semantic = max(0.0, cosine_similarity(query_vector, song_vector))
    comparisons: list[float] = []
    for target, key in (
        (intent.targetEnergy, "energy"),
        (intent.targetValence, "valence"),
        (intent.targetDanceability, "danceability"),
    ):
        actual = profile.get(key)
        if target is not None and actual is not None:
            comparisons.append(1.0 - abs(target - float(actual)))
    feature = sum(comparisons) / len(comparisons) if comparisons else semantic
    score = 0.72 * semantic + 0.28 * feature
    return score, semantic, feature, None


def explain_profile(intent: SearchIntent, profile: SongProfile) -> CandidateExplanation:
    data = profile.profile
    reasons: list[str] = []
    uncertainties: list[str] = []
    if profile.model_provider != "manual":
        uncertainties.append("画像来自有限元数据推断，未使用歌词或音频分析")
    if profile.confidence < 0.6:
        uncertainties.append("画像自评可信度较低，建议试听或人工校正")
    for target, key, label in (
        (intent.targetEnergy, "energy", "能量"),
        (intent.targetValence, "valence", "情绪明亮度"),
        (intent.targetDanceability, "danceability", "律动"),
    ):
        if target is not None:
            actual = data.get(key)
            if actual is None:
                uncertainties.append(f"缺少{label}信息，该项未参与特征评分")
            elif abs(target - actual) <= 0.2:
                reasons.append(f"画像{label}接近需求（{actual:.2f} / 目标 {target:.2f}）")
    if (
        intent.allowedLanguages
        and normalize_language(data.get("language")) in intent.allowedLanguages
    ):
        reasons.append("画像语言符合明确要求")
    if intent.requiredVocalModes:
        reasons.append(f"画像人声类型符合要求：{vocal_label(normalize_profile_vocal_mode(data))}")
    for maximum, actual, label in (
        (intent.maxEnergy, data.get("energy"), "能量"),
        (intent.maxSadness, (data.get("emotions") or {}).get("sadness"), "悲伤强度"),
        (intent.maxTension, (data.get("emotions") or {}).get("tension"), "紧张强度"),
    ):
        if maximum is not None and actual is not None and actual <= maximum:
            reasons.append(f"画像{label}未超过明确上限（{actual:.2f} ≤ {maximum:.2f}）")
    if not reasons:
        reasons.append("主要根据需求与画像描述的语义相似度排序")
    return CandidateExplanation(
        profileVersion=profile.profile_version,
        basis=profile_basis(profile),
        confidence=profile.confidence,
        summary=profile.semantic_description,
        reasons=reasons,
        uncertainties=uncertainties,
    )


class SemanticSearchService:
    def __init__(
        self,
        database: Database,
        model_client: DeepSeekModelClient,
        embedding_client: LocalEmbeddingClient,
    ) -> None:
        self._database = database
        self._model_client = model_client
        self._embedding_client = embedding_client

    async def create_queue(
        self,
        api_key: str,
        description: str,
        *,
        parent_session_id: uuid.UUID | None = None,
        refinements: list[str] | None = None,
        base_description: str | None = None,
    ) -> TemporaryQueue:
        intent = await self._model_client.understand_feeling(api_key, description)
        intent = apply_explicit_intent_rules(description, intent)
        intent = intent.model_copy(update={"threshold": max(0.75, intent.threshold)})
        query_vector = (await self._embedding_client.embeddings([intent.semanticQuery]))[0]
        rows = await self._profile_rows()
        if not rows:
            raise NoProfilesError("还没有可搜索的歌曲画像，请先运行画像任务。")

        evaluated: list[tuple[Song, float, float, float, str | None]] = []
        explanations: dict[uuid.UUID, dict] = {}
        for song, profile, embedding in rows:
            vector = (
                embedding.vector.tolist()
                if hasattr(embedding.vector, "tolist")
                else list(embedding.vector)
            )
            score, semantic, feature, reason = score_profile(
                intent, profile.profile, query_vector, vector
            )
            evaluated.append((song, score, semantic, feature, reason))
            explanations[song.id] = explain_profile(intent, profile).model_dump(mode="json")
        passed = [row for row in evaluated if row[4] is None and row[1] >= intent.threshold]
        passed.sort(key=lambda row: (-row[1], row[0].source_track_id))

        digest_input = sorted(str(song.id) for song, *_ in passed)
        candidate_hash = hashlib.sha256("|".join(digest_input).encode()).hexdigest()
        session_id = uuid.uuid4()
        playlist_id = uuid.uuid4()
        queue_name = intent.summary[:256]
        queue_songs: list[QueueSong] = []
        try:
            async with self._database.session_factory() as session, session.begin():
                library_count = (
                    await session.scalar(
                        select(func.count())
                        .select_from(LibraryMembership)
                        .where(
                            LibraryMembership.library == LIKED_LIBRARY,
                            LibraryMembership.active.is_(True),
                        )
                    )
                    or 0
                )
                rejection_counts = Counter(
                    reason or "综合匹配分未达到阈值"
                    for _, score, _, _, reason in evaluated
                    if reason is not None or score < intent.threshold
                )
                diagnostics = SearchDiagnostics(
                    libraryCount=library_count,
                    profiledCount=len(rows),
                    missingProfileCount=max(0, library_count - len(rows)),
                    rejections=[
                        RejectionSummary(reason=reason, count=count)
                        for reason, count in rejection_counts.most_common()
                    ],
                )
                search = SearchSession(
                    id=session_id,
                    parent_session_id=parent_session_id,
                    description=base_description if base_description is not None else description,
                    refinements=refinements or [],
                    structured_intent=intent.model_dump(mode="json"),
                    diagnostics=diagnostics.model_dump(mode="json"),
                    matching_policy="balanced",
                    threshold=intent.threshold,
                    candidate_set_hash=candidate_hash,
                    status="completed",
                )
                session.add(search)
                await session.flush()
                playlist = GeneratedPlaylist(
                    id=playlist_id,
                    session_id=session_id,
                    name=queue_name,
                    candidate_set_hash=candidate_hash,
                    sort_mode="match",
                    snapshot_hash=self._snapshot_hash([song.id for song, *_ in passed]),
                )
                session.add(playlist)
                await session.flush()
                passed_ids = {song.id for song, *_ in passed}
                position_by_song_id = {song.id: index for index, (song, *_) in enumerate(passed)}
                for stable_order, (song, score, semantic, feature, reason) in enumerate(evaluated):
                    candidate = SearchCandidate(
                        session_id=session_id,
                        song_id=song.id,
                        score=score,
                        semantic_score=semantic,
                        feature_score=feature,
                        passed=song.id in passed_ids,
                        exclusion_reason=reason
                        if reason
                        else (None if song.id in passed_ids else "综合匹配度未达到阈值"),
                        stable_order=stable_order,
                        explanation=explanations[song.id],
                    )
                    session.add(candidate)
                    await session.flush()
                    if song.id in passed_ids:
                        position = position_by_song_id[song.id]
                        session.add(
                            PlaylistItem(
                                playlist_id=playlist_id,
                                song_id=song.id,
                                candidate_id=candidate.id,
                                position=position,
                            )
                        )
                        queue_songs.append(
                            QueueSong(
                                candidateId=candidate.id,
                                songId=song.id,
                                sourceTrackId=song.source_track_id,
                                title=song.title,
                                artists=[ArtistPreview(name=a["name"]) for a in song.artists],
                                album=song.album,
                                score=round(score, 4),
                                semanticScore=round(semantic, 4),
                                featureScore=round(feature, 4),
                            )
                        )
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法保存临时播放队列。") from exc

        result = await self.get_playlist(playlist_id)
        if result is None:
            raise LibraryDatabaseError("临时播放队列保存后无法读取。")
        return result

    async def get_playlist(self, playlist_id: uuid.UUID) -> TemporaryQueue | None:
        try:
            async with self._database.session_factory() as session:
                playlist = await session.get(GeneratedPlaylist, playlist_id)
                if playlist is None:
                    return None
                search = await session.get(SearchSession, playlist.session_id)
                rows = (
                    await session.execute(
                        select(PlaylistItem, SearchCandidate, Song)
                        .join(SearchCandidate, PlaylistItem.candidate_id == SearchCandidate.id)
                        .join(Song, PlaylistItem.song_id == Song.id)
                        .where(PlaylistItem.playlist_id == playlist_id)
                        .order_by(PlaylistItem.position)
                    )
                ).all()
                evaluated_count = await session.scalar(
                    select(func.count())
                    .select_from(SearchCandidate)
                    .where(SearchCandidate.session_id == playlist.session_id)
                )
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法读取临时播放队列。") from exc
        if search is None:
            return None
        songs = [
            QueueSong(
                candidateId=candidate.id,
                songId=song.id,
                sourceTrackId=song.source_track_id,
                title=song.title,
                artists=[ArtistPreview(name=a["name"]) for a in song.artists],
                album=song.album,
                score=round(candidate.score, 4),
                semanticScore=round(candidate.semantic_score, 4),
                featureScore=round(candidate.feature_score, 4),
                durationMs=song.duration_ms,
                explanation=(
                    CandidateExplanation.model_validate(candidate.explanation)
                    if candidate.explanation
                    else None
                ),
            )
            for _, candidate, song in rows
        ]
        return TemporaryQueue(
            sessionId=search.id,
            playlistId=playlist.id,
            name=playlist.name,
            description=search.description,
            intent=SearchIntent.model_validate(search.structured_intent),
            candidateSetHash=playlist.candidate_set_hash,
            evaluatedCount=evaluated_count or 0,
            matchedCount=len(songs),
            songs=songs,
            sortMode=playlist.sort_mode,
            randomSeed=playlist.random_seed,
            curve=EmotionCurve.model_validate(playlist.curve) if playlist.curve else None,
            createdAt=playlist.created_at,
            diagnostics=(
                SearchDiagnostics.model_validate(search.diagnostics) if search.diagnostics else None
            ),
        )

    async def validate_playback_queue(self, queue: TemporaryQueue) -> None:
        expected_ids = {song.songId for song in queue.songs}
        try:
            async with self._database.session_factory() as session:
                active_ids = set(
                    await session.scalars(
                        select(LibraryMembership.song_id).where(
                            LibraryMembership.song_id.in_(expected_ids),
                            LibraryMembership.library == LIKED_LIBRARY,
                            LibraryMembership.active.is_(True),
                        )
                    )
                )
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法校验播放队列，请稍后重试。") from exc
        if active_ids != expected_ids:
            raise CandidateSetMismatchError("当前喜欢集合已变化，请重新选歌；历史记录已保留。")

    @staticmethod
    def _snapshot_hash(song_ids: list[uuid.UUID]) -> str:
        return hashlib.sha256("|".join(str(song_id) for song_id in song_ids).encode()).hexdigest()

    async def refine_queue(
        self, api_key: str, session_id: uuid.UUID, requirement: str
    ) -> TemporaryQueue:
        try:
            async with self._database.session_factory() as session:
                search = await session.get(SearchSession, session_id)
                if search is None:
                    raise SearchSessionNotFoundError("搜索会话不存在。")
                root = search
                visited = {root.id}
                while root.parent_session_id is not None:
                    parent = await session.get(SearchSession, root.parent_session_id)
                    if parent is None or parent.id in visited:
                        raise SearchSessionNotFoundError("原始搜索会话不存在或历史关系异常。")
                    root = parent
                    visited.add(root.id)
                base_description = root.description
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法读取待追加要求的搜索会话。") from exc
        refinements = [*search.refinements, requirement]
        combined = f"{base_description}\n追加要求：" + "；".join(refinements)
        return await self.create_queue(
            api_key,
            combined,
            parent_session_id=search.id,
            refinements=refinements,
            base_description=base_description,
        )

    async def sort_queue(
        self,
        session_id: uuid.UUID,
        request: QueueSortCreate,
        *,
        refresh_candidate_hash: bool = False,
    ) -> TemporaryQueue:
        search, rows = await self._active_candidate_rows(session_id)
        if request.mode == "match":
            ordered = sorted(rows, key=lambda row: (-row[0].score, row[1].source_track_id))
            seed = None
            curve = None
        elif request.mode == "random":
            ordered = sorted(rows, key=lambda row: row[1].source_track_id)
            seed = (
                request.randomSeed
                if request.randomSeed is not None
                else secrets.randbelow(9_007_199_254_740_992)
            )
            random.Random(seed).shuffle(ordered)
            curve = None
        else:
            curve_model = request.curve or EmotionCurve()
            ordered = self._emotion_curve_order(rows, curve_model)
            seed = None
            curve = curve_model.model_dump(mode="json")
        return await self._persist_playlist(
            search,
            ordered,
            sort_mode=request.mode,
            random_seed=seed,
            curve=curve,
            candidate_hash=None if refresh_candidate_hash else search.candidate_set_hash,
        )

    async def remove_candidate(
        self, session_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> TemporaryQueue:
        try:
            async with self._database.session_factory() as session, session.begin():
                search = await session.get(SearchSession, session_id, with_for_update=True)
                if search is None:
                    raise SearchSessionNotFoundError("搜索会话不存在。")
                rows = await self._candidate_rows(session, session_id)
                candidate = next((row[0] for row in rows if row[0].id == candidate_id), None)
                if candidate is None:
                    raise CandidateNotFoundError("候选歌曲不存在、已经移除或画像不可用。")
                candidate.user_removed = True
                ordered = sorted(
                    (row for row in rows if row[0].id != candidate_id),
                    key=lambda row: (-row[0].score, row[1].source_track_id),
                )
                playlist_id = await self._write_playlist(
                    session, search, ordered, sort_mode="match"
                )
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法移除候选歌曲，原队列已保留。") from exc
        return await self._required_playlist(playlist_id)

    async def save_candidate_order(
        self, session_id: uuid.UUID, candidate_ids: list[uuid.UUID]
    ) -> TemporaryQueue:
        search, rows = await self._active_candidate_rows(session_id)
        by_id = {candidate.id: row for row in rows for candidate in [row[0]]}
        if len(candidate_ids) != len(set(candidate_ids)) or set(candidate_ids) != set(by_id):
            raise CandidateSetMismatchError(
                "拖动顺序必须恰好包含当前候选集合，不能缺少、重复或加入歌曲。"
            )
        ordered = [by_id[candidate_id] for candidate_id in candidate_ids]
        return await self._persist_playlist(
            search,
            ordered,
            sort_mode="manual",
            manually_adjusted=True,
            candidate_hash=search.candidate_set_hash,
        )

    async def find_similar(self, session_id: uuid.UUID, candidate_id: uuid.UUID) -> TemporaryQueue:
        search, rows = await self._active_candidate_rows(session_id)
        target = next((row for row in rows if row[0].id == candidate_id), None)
        if target is None:
            raise CandidateNotFoundError("找不到作为相似度基准的候选歌曲。")
        target_vector = self._vector(target[3].vector)
        ordered = sorted(
            rows,
            key=lambda row: (
                -cosine_similarity(target_vector, self._vector(row[3].vector)),
                row[1].source_track_id,
            ),
        )
        return await self._persist_playlist(
            search,
            ordered,
            sort_mode="similar",
            candidate_hash=search.candidate_set_hash,
        )

    async def list_history(self, *, page: int, page_size: int) -> PlaylistHistoryPage:
        count_items = (
            select(func.count(PlaylistItem.id))
            .where(PlaylistItem.playlist_id == GeneratedPlaylist.id)
            .correlate(GeneratedPlaylist)
            .scalar_subquery()
        )
        try:
            async with self._database.session_factory() as session:
                total = await session.scalar(select(func.count()).select_from(GeneratedPlaylist))
                rows = (
                    await session.execute(
                        select(GeneratedPlaylist, SearchSession, count_items.label("song_count"))
                        .join(SearchSession, GeneratedPlaylist.session_id == SearchSession.id)
                        .order_by(GeneratedPlaylist.created_at.desc(), GeneratedPlaylist.id.desc())
                        .offset(page * page_size)
                        .limit(page_size)
                    )
                ).all()
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法读取临时队列历史。") from exc
        return PlaylistHistoryPage(
            page=page,
            pageSize=page_size,
            total=total or 0,
            playlists=[
                PlaylistSummary(
                    playlistId=playlist.id,
                    sessionId=search.id,
                    name=playlist.name,
                    description=search.description,
                    sortMode=playlist.sort_mode,
                    songCount=song_count,
                    createdAt=playlist.created_at,
                )
                for playlist, search, song_count in rows
            ],
        )

    async def get_session_queue(self, session_id: uuid.UUID) -> TemporaryQueue | None:
        try:
            async with self._database.session_factory() as session:
                exists = await session.get(SearchSession, session_id)
                if exists is None:
                    return None
                playlist_id = await session.scalar(
                    select(GeneratedPlaylist.id)
                    .where(GeneratedPlaylist.session_id == session_id)
                    .order_by(GeneratedPlaylist.created_at.desc(), GeneratedPlaylist.id.desc())
                    .limit(1)
                )
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法读取搜索会话。") from exc
        return await self.get_playlist(playlist_id) if playlist_id else None

    async def restore_playlist(self, playlist_id: uuid.UUID) -> TemporaryQueue:
        try:
            async with self._database.session_factory() as session, session.begin():
                playlist = await session.get(GeneratedPlaylist, playlist_id)
                if playlist is None:
                    raise SearchSessionNotFoundError("历史队列快照不存在。")
                search = await session.get(SearchSession, playlist.session_id, with_for_update=True)
                if search is None:
                    raise SearchSessionNotFoundError("搜索会话不存在。")
                candidate_ids = list(
                    await session.scalars(
                        select(PlaylistItem.candidate_id)
                        .where(PlaylistItem.playlist_id == playlist_id)
                        .order_by(PlaylistItem.position)
                    )
                )
                rows = await self._candidate_rows(session, search.id, include_removed=True)
                by_id = {row[0].id: row for row in rows}
                if any(candidate_id not in by_id for candidate_id in candidate_ids):
                    raise CandidateSetMismatchError("历史候选所需的画像不可用，原队列已保留。")
                await session.execute(
                    update(SearchCandidate)
                    .where(
                        SearchCandidate.session_id == search.id,
                        SearchCandidate.passed.is_(True),
                    )
                    .values(user_removed=True)
                )
                if candidate_ids:
                    await session.execute(
                        update(SearchCandidate)
                        .where(
                            SearchCandidate.id.in_(candidate_ids),
                        )
                        .values(user_removed=False)
                    )
                restored_id = await self._write_playlist(
                    session,
                    search,
                    [by_id[candidate_id] for candidate_id in candidate_ids],
                    sort_mode="restored",
                    manually_adjusted=True,
                    candidate_hash=playlist.candidate_set_hash,
                )
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法恢复历史队列快照，原队列已保留。") from exc
        return await self._required_playlist(restored_id)

    async def _candidate_rows(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
        *,
        include_removed: bool = False,
    ) -> list[tuple[SearchCandidate, Song, SongProfile, SongEmbedding]]:
        conditions = [
            SearchCandidate.session_id == session_id,
            SearchCandidate.passed.is_(True),
            SongEmbedding.model_id == self._embedding_client.embedding_model,
        ]
        if not include_removed:
            conditions.append(SearchCandidate.user_removed.is_(False))
        return list(
            (
                await session.execute(
                    select(SearchCandidate, Song, SongProfile, SongEmbedding)
                    .join(Song, SearchCandidate.song_id == Song.id)
                    .join(
                        SongProfile, (SongProfile.song_id == Song.id) & SongProfile.active.is_(True)
                    )
                    .join(SongEmbedding, SongEmbedding.profile_id == SongProfile.id)
                    .where(*conditions)
                    .order_by(SearchCandidate.stable_order, SearchCandidate.id)
                )
            ).all()
        )

    async def _active_candidate_rows(
        self,
        session_id: uuid.UUID,
    ) -> tuple[SearchSession, list[tuple[SearchCandidate, Song, SongProfile, SongEmbedding]]]:
        try:
            async with self._database.session_factory() as session:
                search = await session.get(SearchSession, session_id)
                if search is None:
                    raise SearchSessionNotFoundError("搜索会话不存在。")
                rows = await self._candidate_rows(session, session_id)
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法读取当前候选集合。") from exc
        return search, rows

    async def _persist_playlist(
        self,
        search: SearchSession,
        rows: list[tuple[SearchCandidate, Song, SongProfile, SongEmbedding]],
        *,
        sort_mode: str,
        random_seed: int | None = None,
        curve: dict | None = None,
        manually_adjusted: bool = False,
        candidate_hash: str | None = None,
    ) -> TemporaryQueue:
        try:
            async with self._database.session_factory() as session, session.begin():
                playlist_id = await self._write_playlist(
                    session,
                    search,
                    rows,
                    sort_mode=sort_mode,
                    random_seed=random_seed,
                    curve=curve,
                    manually_adjusted=manually_adjusted,
                    candidate_hash=candidate_hash,
                )
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法保存新的队列快照，原队列已保留。") from exc
        return await self._required_playlist(playlist_id)

    async def _write_playlist(
        self,
        session: AsyncSession,
        search: SearchSession,
        rows: list[tuple[SearchCandidate, Song, SongProfile, SongEmbedding]],
        *,
        sort_mode: str,
        random_seed: int | None = None,
        curve: dict | None = None,
        manually_adjusted: bool = False,
        candidate_hash: str | None = None,
    ) -> uuid.UUID:
        stored_search = await session.get(SearchSession, search.id, with_for_update=True)
        if stored_search is None:
            raise SearchSessionNotFoundError("搜索会话不存在。")
        current_ids = set(
            await session.scalars(
                select(SearchCandidate.id).where(
                    SearchCandidate.session_id == search.id,
                    SearchCandidate.passed.is_(True),
                    SearchCandidate.user_removed.is_(False),
                )
            )
        )
        row_ids = [candidate.id for candidate, *_ in rows]
        if len(row_ids) != len(set(row_ids)) or set(row_ids) != current_ids:
            raise CandidateSetMismatchError("候选集合已变化或画像不可用，请重新读取当前队列。")
        song_ids = [song.id for _, song, _, _ in rows]
        candidate_hash = (
            candidate_hash
            or hashlib.sha256(
                "|".join(sorted(str(song_id) for song_id in song_ids)).encode()
            ).hexdigest()
        )
        playlist_id = uuid.uuid4()
        session.add(
            GeneratedPlaylist(
                id=playlist_id,
                session_id=search.id,
                name=SearchIntent.model_validate(search.structured_intent).summary[:256],
                candidate_set_hash=candidate_hash,
                sort_mode=sort_mode,
                random_seed=random_seed,
                curve=curve,
                snapshot_hash=self._snapshot_hash(song_ids),
            )
        )
        await session.flush()
        session.add_all(
            [
                PlaylistItem(
                    playlist_id=playlist_id,
                    song_id=song.id,
                    candidate_id=candidate.id,
                    position=position,
                    manually_adjusted=manually_adjusted,
                )
                for position, (candidate, song, _, _) in enumerate(rows)
            ]
        )
        stored_search.candidate_set_hash = candidate_hash
        stored_search.updated_at = utc_now()
        return playlist_id

    async def _required_playlist(self, playlist_id: uuid.UUID) -> TemporaryQueue:
        result = await self.get_playlist(playlist_id)
        if result is None:
            raise LibraryDatabaseError("队列快照保存后无法读取。")
        return result

    @staticmethod
    def _vector(value: object) -> list[float]:
        return value.tolist() if hasattr(value, "tolist") else list(value)  # type: ignore[arg-type]

    @classmethod
    def _emotion_curve_order(
        cls,
        rows: list[tuple[SearchCandidate, Song, SongProfile, SongEmbedding]],
        curve: EmotionCurve,
    ) -> list[tuple[SearchCandidate, Song, SongProfile, SongEmbedding]]:
        anchors = {
            "calm": (0.28, 0.58),
            "balanced": (0.5, 0.62),
            "lifted": (0.76, 0.78),
            "settled": (0.32, 0.66),
        }
        points = [anchors[curve.start], anchors[curve.middle], anchors[curve.end]]
        remaining = list(rows)
        ordered: list[tuple[SearchCandidate, Song, SongProfile, SongEmbedding]] = []
        previous: tuple[float, float] | None = None
        total = len(rows)
        for index in range(total):
            progress = index / max(1, total - 1)
            segment = min(1, int(progress * 2))
            local = progress * 2 - segment
            target = tuple(
                points[segment][axis] * (1 - local) + points[segment + 1][axis] * local
                for axis in range(2)
            )

            def cost(
                row: tuple[SearchCandidate, Song, SongProfile, SongEmbedding],
                target: tuple[float, float] = target,
                previous: tuple[float, float] | None = previous,
            ) -> tuple:
                profile = row[2].profile
                current = (
                    float(profile.get("energy") if profile.get("energy") is not None else 0.5),
                    float(profile.get("valence") if profile.get("valence") is not None else 0.5),
                )
                target_error = abs(current[0] - target[0]) + abs(current[1] - target[1])
                transition = (
                    abs(current[0] - previous[0]) + abs(current[1] - previous[1])
                    if previous
                    else 0.0
                )
                return (target_error + transition * 0.35, -row[0].score, row[1].source_track_id)

            chosen = min(remaining, key=cost)
            remaining.remove(chosen)
            profile = chosen[2].profile
            previous = (
                float(profile.get("energy") if profile.get("energy") is not None else 0.5),
                float(profile.get("valence") if profile.get("valence") is not None else 0.5),
            )
            ordered.append(chosen)
        return ordered

    async def _profile_rows(self) -> list[tuple[Song, SongProfile, SongEmbedding]]:
        try:
            async with self._database.session_factory() as session:
                return list(
                    (
                        await session.execute(
                            select(Song, SongProfile, SongEmbedding)
                            .join(LibraryMembership, LibraryMembership.song_id == Song.id)
                            .join(
                                SongProfile,
                                (SongProfile.song_id == Song.id) & SongProfile.active.is_(True),
                            )
                            .join(SongEmbedding, SongEmbedding.profile_id == SongProfile.id)
                            .where(
                                LibraryMembership.library == LIKED_LIBRARY,
                                LibraryMembership.active.is_(True),
                                SongEmbedding.model_id == self._embedding_client.embedding_model,
                            )
                        )
                    ).all()
                )
        except (SQLAlchemyError, OSError) as exc:
            raise LibraryDatabaseError("无法读取歌曲画像与向量。") from exc
