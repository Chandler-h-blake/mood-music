from __future__ import annotations

from datetime import datetime
from uuid import UUID

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


class LibrarySyncResult(BaseModel):
    runId: UUID
    status: str
    pagesFetched: int
    reportedTotal: int
    fetchedCount: int
    uniqueCount: int
    insertedCount: int
    updatedCount: int
    deactivatedCount: int
    skippedMissingId: int


class LibrarySong(BaseModel):
    id: UUID
    sourceTrackId: str
    title: str
    artists: list[ArtistPreview]
    album: str | None = None
    durationMs: int | None = None
    firstSeenAt: datetime
    lastSeenAt: datetime


class LibrarySongPage(BaseModel):
    page: int
    pageSize: int
    total: int
    songs: list[LibrarySong]
