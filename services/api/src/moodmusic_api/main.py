from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status

from .credentials import (
    CredentialStore,
    CredentialStoreError,
    InvalidCookieError,
    WindowsCredentialStore,
)
from .models import CredentialStatus, LikedPagePreview, QQMusicCookieInput
from .qqmusic import QQMusicAuthenticationError, QQMusicClient, QQMusicRequestError


@lru_cache
def get_credential_store() -> CredentialStore:
    return WindowsCredentialStore()


@lru_cache
def get_qqmusic_client() -> QQMusicClient:
    return QQMusicClient()


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

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "moodmusic-api"}

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
            message="Cookie 已保存到 Windows 凭据存储，请继续验证登录状态。",
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

    return app


app = create_app()
