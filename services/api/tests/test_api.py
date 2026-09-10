from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from moodmusic_api.credentials import CredentialStore
from moodmusic_api.main import create_app, get_credential_store, get_qqmusic_client
from moodmusic_api.models import ArtistPreview, LikedPagePreview, SongPreview


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
