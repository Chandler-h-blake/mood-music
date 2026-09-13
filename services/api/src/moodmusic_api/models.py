from __future__ import annotations

from datetime import datetime
from typing import Literal
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


class ModelApiKeyInput(BaseModel):
    apiKey: SecretStr = Field(min_length=1, max_length=512)


class ModelSettings(BaseModel):
    chatProvider: str
    chatModel: str
    embeddingProvider: str
    embeddingModel: str
    embeddingDimensions: int
    apiKeyConfigured: bool


class EmotionValues(BaseModel):
    joy: float | None = Field(ge=0, le=1)
    sadness: float | None = Field(ge=0, le=1)
    loneliness: float | None = Field(ge=0, le=1)
    warmth: float | None = Field(ge=0, le=1)
    hope: float | None = Field(ge=0, le=1)
    tension: float | None = Field(ge=0, le=1)
    calm: float | None = Field(ge=0, le=1)


class SongProfileData(BaseModel):
    sourceTrackId: str
    identitySummary: str
    language: str | None
    vocalType: str | None
    genres: list[str]
    energy: float | None = Field(ge=0, le=1)
    valence: float | None = Field(ge=0, le=1)
    danceability: float | None = Field(ge=0, le=1)
    acousticness: float | None = Field(ge=0, le=1)
    emotions: EmotionValues
    scenes: list[str]
    themes: list[str]
    arrangement: list[str]
    semanticDescription: str = Field(min_length=1, max_length=1200)
    confidence: float = Field(ge=0, le=1)


class SongProfileBatch(BaseModel):
    profiles: list[SongProfileData]


LanguageCode = Literal["zh", "yue", "en", "ja", "ko", "es", "fr", "de", "ru", "other"]
VocalMode = Literal[
    "male_solo",
    "female_solo",
    "mixed_duet",
    "male_duet",
    "female_duet",
    "group",
    "choir",
    "instrumental",
    "other",
]


class SearchIntent(BaseModel):
    summary: str
    semanticQuery: str
    scenes: list[str]
    exclusions: list[str]
    excludedGenres: list[str]
    requiredVocalModes: list[VocalMode] = Field(default_factory=list)
    excludedVocalModes: list[VocalMode] = Field(default_factory=list)
    allowedLanguages: list[LanguageCode] = Field(default_factory=list)
    excludedLanguages: list[LanguageCode] = Field(default_factory=list)
    instrumentalAllowed: bool | None = None
    targetEnergy: float | None = Field(ge=0, le=1)
    maxEnergy: float | None = Field(default=None, ge=0, le=1)
    targetValence: float | None = Field(ge=0, le=1)
    targetDanceability: float | None = Field(ge=0, le=1)
    maxSadness: float | None = Field(ge=0, le=1)
    maxTension: float | None = Field(ge=0, le=1)
    threshold: float = Field(ge=0.45, le=0.8)


class ProfileJobCreate(BaseModel):
    mode: str = Field(default="incremental", pattern="^(incremental|rebuild)$")


class JobStatus(BaseModel):
    jobId: UUID
    status: str
    total: int
    completed: int
    failed: int
    lastError: str | None = None


class SearchSessionCreate(BaseModel):
    description: str = Field(min_length=2, max_length=1000)
    matchingPolicy: str = Field(default="balanced", pattern="^balanced$")
    sortMode: str = Field(default="match", pattern="^match$")
    library: str = Field(default="liked", pattern="^liked$")


class SearchRefinementCreate(BaseModel):
    requirement: str = Field(min_length=2, max_length=1000)


class EmotionCurve(BaseModel):
    start: str = Field(default="calm", pattern="^(calm|balanced|lifted)$")
    middle: str = Field(default="lifted", pattern="^(calm|balanced|lifted)$")
    end: str = Field(default="settled", pattern="^(calm|balanced|lifted|settled)$")


class QueueSortCreate(BaseModel):
    mode: str = Field(pattern="^(match|emotionCurve|random)$")
    curve: EmotionCurve | None = None
    randomSeed: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)


class CandidateOrderUpdate(BaseModel):
    candidateIds: list[UUID] = Field(min_length=1)


class QueueSong(BaseModel):
    candidateId: UUID
    songId: UUID
    sourceTrackId: str
    title: str
    artists: list[ArtistPreview]
    album: str | None
    score: float
    semanticScore: float
    featureScore: float


class TemporaryQueue(BaseModel):
    sessionId: UUID
    playlistId: UUID
    name: str
    description: str
    intent: SearchIntent
    candidateSetHash: str
    evaluatedCount: int
    matchedCount: int
    songs: list[QueueSong]
    sortMode: str = "match"
    randomSeed: int | None = None
    curve: EmotionCurve | None = None
    createdAt: datetime | None = None


class PlaylistSummary(BaseModel):
    playlistId: UUID
    sessionId: UUID
    name: str
    description: str
    sortMode: str
    songCount: int
    createdAt: datetime


class PlaylistHistoryPage(BaseModel):
    page: int
    pageSize: int
    total: int
    playlists: list[PlaylistSummary]
