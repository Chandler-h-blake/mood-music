from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr


class QQMusicCookieInput(BaseModel):
    cookie: SecretStr = Field(description="Cookie copied from an authenticated QQ Music request")


class CredentialStatus(BaseModel):
    configured: bool
    valid: bool | None = None
    maskedAccount: str | None = None
    message: str


class ArtistPreview(BaseModel):
    name: str


class SongPreview(BaseModel):
    sourceTrackId: str
    title: str
    artists: list[ArtistPreview]
    album: str | None = None
    durationMs: int | None = None


class LikedPagePreview(BaseModel):
    page: int
    pageSize: int
    total: int
    songs: list[SongPreview]
    diagnosticOnly: bool = True
