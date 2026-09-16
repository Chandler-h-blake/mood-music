from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from moodmusic_api.credentials import CredentialStore
from moodmusic_api.library import LibraryDatabaseError, LibraryService
from moodmusic_api.main import (
    create_app,
    get_credential_store,
    get_database,
    get_model_credential_store,
    get_profile_service,
    get_qqmusic_client,
    get_semantic_search_service,
)
from moodmusic_api.models import ArtistPreview, LikedPagePreview, SongPreview
from moodmusic_api.semantic_search import SearchSessionNotFoundError


class MemoryCredentialStore(CredentialStore):
    def __init__(self) -> None:
        self.cookie: str | None = None

    def set_qqmusic_cookie(self, cookie: str) -> None:
        self.cookie = cookie

    def get_qqmusic_cookie(self) -> str | None:
        return self.cookie

    def delete_qqmusic_cookie(self) -> bool:
        existed = self.cookie is not None
        self.cookie = None
        return existed


class FakeQQMusicClient:
    async def fetch_liked_page(
        self,
        raw_cookie: str,
        *,
        page: int,
        page_size: int,
    ) -> tuple[LikedPagePreview, str]:
        assert raw_cookie == "uin=12345678; qm_keyst=test-secret"
        return (
            LikedPagePreview(
                page=page,
                pageSize=page_size,
                total=1,
                songs=[
                    SongPreview(
                        sourceTrackId="song-mid-1",
                        title="示例歌曲",
                        artists=[ArtistPreview(name="示例歌手")],
                    )
                ],
            ),
            "12****78",
        )


class UnavailableDatabase:
    async def ping(self) -> None:
        raise ConnectionRefusedError("database is not running")


class RefusingSessionFactory:
    def __call__(self) -> None:
        raise ConnectionRefusedError("database is not running")


class RefusingDatabase:
    session_factory = RefusingSessionFactory()


class ConfiguredModelStore:
    def get_deepseek_api_key(self) -> str:
        return "test-key"


class MissingSearchService:
    async def save_candidate_order(self, session_id, candidate_ids):
        raise SearchSessionNotFoundError("搜索会话不存在。")

    async def find_similar(self, session_id, candidate_id):
        raise SearchSessionNotFoundError("搜索会话不存在。")


class UnavailableProfileService:
    async def retry_job(self, job_id):
        raise LibraryDatabaseError("无法读取画像任务。")


def build_app() -> tuple[FastAPI, MemoryCredentialStore]:
    app = create_app()
    store = MemoryCredentialStore()
    app.dependency_overrides[get_credential_store] = lambda: store
    app.dependency_overrides[get_qqmusic_client] = FakeQQMusicClient
    return app, store


@pytest.mark.asyncio
async def test_first_vertical_slice() -> None:
    app, store = build_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/v1/health")
        assert health.status_code == 200

        saved = await client.put(
            "/api/v1/credentials/qqmusic-cookie",
            json={"cookie": "uin=12345678; qm_keyst=test-secret"},
        )
        assert saved.status_code == 200
        assert "test-secret" not in saved.text
        assert store.cookie is not None

        login = await client.post("/api/v1/providers/qqmusic-cookie/test")
        assert login.status_code == 200
        assert login.json()["maskedAccount"] == "12****78"

        preview = await client.post("/api/v1/library/sync-preview?pageSize=30")
        assert preview.status_code == 200
        assert preview.json()["total"] == 1
        assert preview.json()["songs"][0]["title"] == "示例歌曲"

        deleted = await client.delete("/api/v1/credentials/qqmusic-cookie")
        assert deleted.status_code == 200
        assert store.cookie is None


@pytest.mark.asyncio
async def test_readiness_returns_service_unavailable_when_database_connection_is_refused() -> None:
    app, _ = build_app()
    app.dependency_overrides[get_database] = UnavailableDatabase
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "database.unavailable",
            "message": "PostgreSQL 尚未就绪。",
        }
    }


@pytest.mark.asyncio
async def test_library_wraps_database_connection_refusal() -> None:
    library = LibraryService(RefusingDatabase())  # type: ignore[arg-type]

    with pytest.raises(LibraryDatabaseError, match="无法创建同步批次"):
        await library._create_batch(uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "PATCH",
            "/api/v1/search-sessions/{session_id}/candidate-order",
            {"candidateIds": ["00000000-0000-0000-0000-000000000002"]},
        ),
        (
            "POST",
            (
                "/api/v1/search-sessions/{session_id}/candidates/"
                "00000000-0000-0000-0000-000000000002/similar"
            ),
            None,
        ),
    ],
)
async def test_missing_search_session_is_not_reported_as_database_outage(
    method: str, path: str, body: dict[str, list[str]] | None
) -> None:
    app, _ = build_app()
    app.dependency_overrides[get_semantic_search_service] = MissingSearchService
    transport = httpx.ASGITransport(app=app)
    url = path.format(session_id="00000000-0000-0000-0000-000000000001")

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, url, json=body)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "search.notFound"


@pytest.mark.asyncio
async def test_retry_job_maps_database_failure_to_service_unavailable() -> None:
    app, _ = build_app()
    app.dependency_overrides[get_model_credential_store] = ConfiguredModelStore
    app.dependency_overrides[get_profile_service] = UnavailableProfileService
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000001/retry"
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database.unavailable"
