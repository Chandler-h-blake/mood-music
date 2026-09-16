from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from .ai_client import (
    DeepSeekModelClient,
    LocalEmbeddingClient,
    ModelConfigurationError,
    ModelRequestError,
)
from .connector_protocol import (
    ConnectorHelloMessage,
    ConnectorProtocolDescriptor,
    ConnectorWelcomeMessage,
    connector_protocol_descriptor,
    negotiate_connector,
)
from .credentials import (
    CredentialStore,
    CredentialStoreError,
    InvalidCookieError,
    ModelCredentialStore,
    WindowsCredentialStore,
)
from .database import Database
from .library import LibraryDatabaseError, LibraryService, LibrarySyncInProgressError
from .models import (
    CandidateOrderUpdate,
    CredentialStatus,
    JobStatus,
    LibrarySongPage,
    LibrarySyncResult,
    LikedPagePreview,
    ModelApiKeyInput,
    ModelSettings,
    PCPlaybackActionInput,
    PCPlaybackActionResult,
    PCPlaybackQueueInput,
    PCPlaybackQueueResult,
    PCPlaybackState,
    PlaylistHistoryPage,
    ProfileJobCreate,
    QQMusicCookieInput,
    QueueSortCreate,
    SearchRefinementCreate,
    SearchSessionCreate,
    TemporaryQueue,
)
from .profiles import ProfileJobConflictError, ProfileJobNotFoundError, ProfileService
from .qqmusic import QQMusicAuthenticationError, QQMusicClient, QQMusicRequestError
from .qqmusic_pc import QQMusicPCError, QQMusicPCService
from .semantic_search import (
    CandidateNotFoundError,
    CandidateSetMismatchError,
    NoProfilesError,
    SearchSessionNotFoundError,
    SemanticSearchService,
)
from .windows_media import WindowsMediaError, WindowsMediaService


@lru_cache
def get_credential_store() -> CredentialStore:
    return WindowsCredentialStore()


@lru_cache
def get_qqmusic_client() -> QQMusicClient:
    return QQMusicClient()


@lru_cache
def get_model_credential_store() -> ModelCredentialStore:
    return ModelCredentialStore()


@lru_cache
def get_model_client() -> DeepSeekModelClient:
    return DeepSeekModelClient()


@lru_cache
def get_embedding_client() -> LocalEmbeddingClient:
    return LocalEmbeddingClient()


@lru_cache
def get_database() -> Database:
    return Database()


@lru_cache
def get_windows_media_service() -> WindowsMediaService:
    return WindowsMediaService()


@lru_cache
def get_qqmusic_pc_service() -> QQMusicPCService:
    return QQMusicPCService(get_qqmusic_client(), get_windows_media_service())


@lru_cache
def get_library_service() -> LibraryService:
    return LibraryService(get_database())


@lru_cache
def get_profile_service() -> ProfileService:
    return ProfileService(get_database(), get_model_client(), get_embedding_client())


@lru_cache
def get_semantic_search_service() -> SemanticSearchService:
    return SemanticSearchService(get_database(), get_model_client(), get_embedding_client())


def require_model_api_key(store: ModelCredentialStore) -> str:
    try:
        api_key = store.get_deepseek_api_key()
    except CredentialStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "credentials.unavailable", "message": str(exc)},
        ) from exc
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "model.apiKeyMissing", "message": "请先设置 DeepSeek API Key。"},
        )
    return api_key


def require_cookie(store: CredentialStore) -> str:
    try:
        cookie = store.get_qqmusic_cookie()
    except CredentialStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "credentials.unavailable", "message": str(exc)},
        ) from exc
    if cookie is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "qqmusic.cookieMissing",
                "message": "请先在本机设置 QQ 音乐 Cookie。",
            },
        )
    return cookie


def create_app() -> FastAPI:
    app = FastAPI(
        title="MoodMusic API",
        version="0.1.0",
        description="Local-only API for MoodMusic",
    )
    configured_origins = os.environ.get(
        "WEB_ORIGIN",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    allowed_origins = [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "moodmusic-api"}

    @app.get(
        "/api/v1/connectors/protocol",
        response_model=ConnectorProtocolDescriptor,
    )
    async def connector_protocol() -> ConnectorProtocolDescriptor:
        return connector_protocol_descriptor()

    @app.post(
        "/api/v1/connectors/negotiate",
        response_model=ConnectorWelcomeMessage,
    )
    async def connector_negotiate(
        payload: ConnectorHelloMessage,
    ) -> ConnectorWelcomeMessage:
        return negotiate_connector(payload)

    @app.get("/api/v1/playback/state", response_model=PCPlaybackState)
    async def get_playback_state(
        media: Annotated[WindowsMediaService, Depends(get_windows_media_service)],
    ) -> PCPlaybackState:
        try:
            return await media.get_state()
        except WindowsMediaError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "playback.unavailable", "message": str(exc)},
            ) from exc

    @app.post("/api/v1/playback/actions", response_model=PCPlaybackActionResult)
    async def control_playback(
        payload: PCPlaybackActionInput,
        pc: Annotated[QQMusicPCService, Depends(get_qqmusic_pc_service)],
    ) -> PCPlaybackActionResult:
        try:
            return await pc.control(payload.action)
        except (QQMusicPCError, WindowsMediaError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "playback.controlFailed", "message": str(exc)},
            ) from exc


    @app.get("/api/v1/settings", response_model=ModelSettings)
    async def settings_view(
        store: Annotated[ModelCredentialStore, Depends(get_model_credential_store)],
        model: Annotated[DeepSeekModelClient, Depends(get_model_client)],
        embedding: Annotated[LocalEmbeddingClient, Depends(get_embedding_client)],
    ) -> ModelSettings:
        try:
            configured = store.get_deepseek_api_key() is not None
        except CredentialStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "credentials.unavailable", "message": str(exc)},
            ) from exc
        return ModelSettings(
            chatProvider="deepseek",
            chatModel=model.chat_model,
            embeddingProvider="local",
            embeddingModel=embedding.embedding_model,
            embeddingDimensions=embedding.embedding_dimensions,
            apiKeyConfigured=configured,
        )

    @app.put("/api/v1/credentials/deepseek", response_model=CredentialStatus)
    async def set_deepseek_key(
        payload: ModelApiKeyInput,
        store: Annotated[ModelCredentialStore, Depends(get_model_credential_store)],
    ) -> CredentialStatus:
        try:
            store.set_deepseek_api_key(payload.apiKey.get_secret_value())
        except InvalidCookieError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "model.apiKeyInvalid", "message": str(exc)},
            ) from exc
        except CredentialStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "credentials.unavailable", "message": str(exc)},
            ) from exc
        return CredentialStatus(
            configured=True,
            valid=None,
            message="DeepSeek API Key 已保存到本机 DPAPI 加密凭据存储。",
        )

    @app.delete("/api/v1/credentials/deepseek", response_model=CredentialStatus)
    async def delete_deepseek_key(
        store: Annotated[ModelCredentialStore, Depends(get_model_credential_store)],
    ) -> CredentialStatus:
        try:
            deleted = store.delete_deepseek_api_key()
        except CredentialStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "credentials.unavailable", "message": str(exc)},
            ) from exc
        return CredentialStatus(
            configured=False,
            valid=None,
            message="DeepSeek API Key 已清除。" if deleted else "当前没有已保存的 API Key。",
        )

    @app.post("/api/v1/providers/deepseek/test", response_model=CredentialStatus)
    async def test_deepseek(
        store: Annotated[ModelCredentialStore, Depends(get_model_credential_store)],
        model: Annotated[DeepSeekModelClient, Depends(get_model_client)],
    ) -> CredentialStatus:
        api_key = require_model_api_key(store)
        try:
            await model.test_connection(api_key)
        except (ModelRequestError, ModelConfigurationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "model.requestFailed", "message": str(exc)},
            ) from exc
        return CredentialStatus(configured=True, valid=True, message="DeepSeek 模型连接有效。")

    @app.get("/api/v1/health/ready")
    async def readiness(
        database: Annotated[Database, Depends(get_database)],
    ) -> dict[str, str]:
        try:
            await database.ping()
        except (SQLAlchemyError, OSError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "database.unavailable", "message": "PostgreSQL 尚未就绪。"},
            ) from exc
        return {"status": "ready", "database": "ok"}

    @app.put(
        "/api/v1/credentials/qqmusic-cookie",
        response_model=CredentialStatus,
    )
    async def set_qqmusic_cookie(
        payload: QQMusicCookieInput,
        store: Annotated[CredentialStore, Depends(get_credential_store)],
    ) -> CredentialStatus:
        try:
            store.set_qqmusic_cookie(payload.cookie.get_secret_value())
        except InvalidCookieError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "qqmusic.cookieInvalid", "message": str(exc)},
            ) from exc
        except CredentialStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "credentials.unavailable", "message": str(exc)},
            ) from exc
        return CredentialStatus(
            configured=True,
            valid=None,
            message="Cookie 已保存到本机 DPAPI 加密凭据存储，请继续验证登录状态。",
        )

    @app.delete(
        "/api/v1/credentials/qqmusic-cookie",
        response_model=CredentialStatus,
    )
    async def delete_qqmusic_cookie(
        store: Annotated[CredentialStore, Depends(get_credential_store)],
    ) -> CredentialStatus:
        try:
            deleted = store.delete_qqmusic_cookie()
        except CredentialStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "credentials.unavailable", "message": str(exc)},
            ) from exc
        return CredentialStatus(
            configured=False,
            valid=None,
            message="QQ 音乐 Cookie 已清除。" if deleted else "当前没有已保存的 QQ 音乐 Cookie。",
        )

    @app.post(
        "/api/v1/providers/qqmusic-cookie/test",
        response_model=CredentialStatus,
    )
    async def test_qqmusic_cookie(
        store: Annotated[CredentialStore, Depends(get_credential_store)],
        client: Annotated[QQMusicClient, Depends(get_qqmusic_client)],
    ) -> CredentialStatus:
        cookie = require_cookie(store)
        try:
            _, masked_account = await client.fetch_liked_page(cookie, page=0, page_size=1)
        except QQMusicAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "qqmusic.cookieExpired", "message": str(exc)},
            ) from exc
        except QQMusicRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "qqmusic.requestFailed", "message": str(exc)},
            ) from exc
        return CredentialStatus(
            configured=True,
            valid=True,
            maskedAccount=masked_account,
            message="QQ 音乐登录状态有效。",
        )

    @app.post(
        "/api/v1/library/sync-preview",
        response_model=LikedPagePreview,
    )
    async def sync_liked_preview(
        store: Annotated[CredentialStore, Depends(get_credential_store)],
        client: Annotated[QQMusicClient, Depends(get_qqmusic_client)],
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 30,
    ) -> LikedPagePreview:
        cookie = require_cookie(store)
        try:
            result, _ = await client.fetch_liked_page(cookie, page=0, page_size=page_size)
            return result
        except QQMusicAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "qqmusic.cookieExpired", "message": str(exc)},
            ) from exc
        except QQMusicRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "qqmusic.requestFailed", "message": str(exc)},
            ) from exc

    @app.post(
        "/api/v1/library/sync",
        response_model=LibrarySyncResult,
    )
    async def sync_liked_library(
        store: Annotated[CredentialStore, Depends(get_credential_store)],
        client: Annotated[QQMusicClient, Depends(get_qqmusic_client)],
        library: Annotated[LibraryService, Depends(get_library_service)],
    ) -> LibrarySyncResult:
        cookie = require_cookie(store)
        try:
            return await library.sync_liked(cookie, client)
        except QQMusicAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "qqmusic.cookieExpired", "message": str(exc)},
            ) from exc
        except QQMusicRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "qqmusic.snapshotFailed", "message": str(exc)},
            ) from exc
        except LibrarySyncInProgressError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "library.syncInProgress", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.get(
        "/api/v1/library/songs",
        response_model=LibrarySongPage,
    )
    async def list_liked_songs(
        library: Annotated[LibraryService, Depends(get_library_service)],
        page: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 50,
        query: Annotated[str | None, Query(alias="q", max_length=100)] = None,
    ) -> LibrarySongPage:
        try:
            return await library.list_liked_songs(
                page=page,
                page_size=page_size,
                query=query,
            )
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.post(
        "/api/v1/profile-jobs",
        response_model=JobStatus,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_profile_job(
        payload: ProfileJobCreate,
        background_tasks: BackgroundTasks,
        credentials: Annotated[ModelCredentialStore, Depends(get_model_credential_store)],
        profiles: Annotated[ProfileService, Depends(get_profile_service)],
    ) -> JobStatus:
        api_key = require_model_api_key(credentials)
        try:
            result = await profiles.create_job(payload.mode)
        except ProfileJobConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "job.alreadyRunning", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc
        if result.status == "queued":
            background_tasks.add_task(
                profiles.run_job,
                result.jobId,
                lambda: api_key,
            )
        return result

    @app.get("/api/v1/jobs/{job_id}", response_model=JobStatus)
    async def get_job(
        job_id: str,
        profiles: Annotated[ProfileService, Depends(get_profile_service)],
    ) -> JobStatus:
        try:
            return await profiles.get_job(_parse_uuid(job_id))
        except ProfileJobNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "job.notFound", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.post("/api/v1/jobs/{job_id}/retry", response_model=JobStatus)
    async def retry_job(
        job_id: str,
        background_tasks: BackgroundTasks,
        credentials: Annotated[ModelCredentialStore, Depends(get_model_credential_store)],
        profiles: Annotated[ProfileService, Depends(get_profile_service)],
    ) -> JobStatus:
        api_key = require_model_api_key(credentials)
        try:
            result = await profiles.retry_job(_parse_uuid(job_id))
        except ProfileJobNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "job.notFound", "message": str(exc)},
            ) from exc
        except ProfileJobConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "job.invalidState", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc
        background_tasks.add_task(
            profiles.run_job,
            result.jobId,
            lambda: api_key,
        )
        return result

    @app.post("/api/v1/search-sessions", response_model=TemporaryQueue)
    async def create_search_session(
        payload: SearchSessionCreate,
        credentials: Annotated[ModelCredentialStore, Depends(get_model_credential_store)],
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
    ) -> TemporaryQueue:
        api_key = require_model_api_key(credentials)
        try:
            return await search_service.create_queue(api_key, payload.description)
        except NoProfilesError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "profiles.notReady", "message": str(exc)},
            ) from exc
        except ModelRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "model.requestFailed", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.get("/api/v1/search-sessions/{session_id}", response_model=TemporaryQueue)
    async def get_search_session(
        session_id: str,
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
    ) -> TemporaryQueue:
        try:
            result = await search_service.get_session_queue(_parse_uuid(session_id))
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "search.notFound", "message": "搜索会话不存在。"},
            )
        return result

    @app.post(
        "/api/v1/search-sessions/{session_id}/refinements", response_model=TemporaryQueue
    )
    async def refine_search_session(
        session_id: str,
        payload: SearchRefinementCreate,
        credentials: Annotated[ModelCredentialStore, Depends(get_model_credential_store)],
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
    ) -> TemporaryQueue:
        api_key = require_model_api_key(credentials)
        try:
            return await search_service.refine_queue(
                api_key, _parse_uuid(session_id), payload.requirement
            )
        except SearchSessionNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "search.notFound", "message": str(exc)},
            ) from exc
        except (ModelRequestError, NoProfilesError) as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "search.refinementFailed", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.post("/api/v1/search-sessions/{session_id}/sorts", response_model=TemporaryQueue)
    async def sort_search_session(
        session_id: str,
        payload: QueueSortCreate,
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
    ) -> TemporaryQueue:
        try:
            return await search_service.sort_queue(_parse_uuid(session_id), payload)
        except SearchSessionNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "search.notFound", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.delete(
        "/api/v1/search-sessions/{session_id}/candidates/{candidate_id}",
        response_model=TemporaryQueue,
    )
    async def remove_search_candidate(
        session_id: str,
        candidate_id: str,
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
    ) -> TemporaryQueue:
        try:
            return await search_service.remove_candidate(
                _parse_uuid(session_id), _parse_uuid(candidate_id)
            )
        except CandidateNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "candidate.notFound", "message": str(exc)},
            ) from exc
        except SearchSessionNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "search.notFound", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.patch(
        "/api/v1/search-sessions/{session_id}/candidate-order",
        response_model=TemporaryQueue,
    )
    async def update_candidate_order(
        session_id: str,
        payload: CandidateOrderUpdate,
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
    ) -> TemporaryQueue:
        try:
            return await search_service.save_candidate_order(
                _parse_uuid(session_id), payload.candidateIds
            )
        except CandidateSetMismatchError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "candidate.setChanged", "message": str(exc)},
            ) from exc
        except SearchSessionNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "search.notFound", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.post(
        "/api/v1/search-sessions/{session_id}/candidates/{candidate_id}/similar",
        response_model=TemporaryQueue,
    )
    async def find_similar_candidates(
        session_id: str,
        candidate_id: str,
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
    ) -> TemporaryQueue:
        try:
            return await search_service.find_similar(
                _parse_uuid(session_id), _parse_uuid(candidate_id)
            )
        except CandidateNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "candidate.notFound", "message": str(exc)},
            ) from exc
        except SearchSessionNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "search.notFound", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.get("/api/v1/generated-playlists", response_model=PlaylistHistoryPage)
    async def list_generated_playlists(
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
        page: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    ) -> PlaylistHistoryPage:
        try:
            return await search_service.list_history(page=page, page_size=page_size)
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.post(
        "/api/v1/generated-playlists/{playlist_id}/restore", response_model=TemporaryQueue
    )
    async def restore_generated_playlist(
        playlist_id: str,
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
    ) -> TemporaryQueue:
        try:
            return await search_service.restore_playlist(_parse_uuid(playlist_id))
        except SearchSessionNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "playlist.notFound", "message": str(exc)},
            ) from exc
        except CandidateSetMismatchError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "playlist.cannotRestore", "message": str(exc)},
            ) from exc
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc

    @app.get("/api/v1/generated-playlists/{playlist_id}", response_model=TemporaryQueue)
    async def get_generated_playlist(
        playlist_id: str,
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
    ) -> TemporaryQueue:
        try:
            result = await search_service.get_playlist(_parse_uuid(playlist_id))
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "playlist.notFound", "message": "临时播放队列不存在。"},
            )
        return result

    @app.post("/api/v1/playback/queues", response_model=PCPlaybackQueueResult)
    async def start_playback_queue(
        payload: PCPlaybackQueueInput,
        search_service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
        pc: Annotated[QQMusicPCService, Depends(get_qqmusic_pc_service)],
    ) -> PCPlaybackQueueResult:
        try:
            queue = await search_service.get_playlist(payload.playlistId)
            if queue is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "playlist.notFound", "message": "临时播放队列不存在。"},
                )
            return await pc.start_queue(queue)
        except HTTPException:
            raise
        except LibraryDatabaseError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "database.unavailable", "message": str(exc)},
            ) from exc
        except QQMusicPCError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "playback.queueFailed", "message": str(exc)},
            ) from exc

    return app


app = create_app()


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "request.invalidId", "message": "资源 ID 格式无效。"},
        ) from exc
