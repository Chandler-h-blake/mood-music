from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, field_validator

PROTOCOL_VERSION = "1.0"
SUPPORTED_CONNECTOR_TYPES = ("web", "pc")
SUPPORTED_CAPABILITIES = (
    "catalog.search",
    "queue.play",
    "playback.control",
    "playback.state",
)

ConnectorType = Literal["web", "pc"]
ConnectorCapability = Literal[
    "catalog.search",
    "queue.play",
    "playback.control",
    "playback.state",
]
PlaybackAction = Literal["play", "pause", "resume", "next", "previous", "stop"]
PlaybackStatus = Literal["idle", "loading", "playing", "paused", "stopped", "ended", "error"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrackReference(StrictModel):
    sourceTrackId: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    artists: list[str] = Field(min_length=1, max_length=32)
    album: str | None = Field(default=None, max_length=512)
    durationMs: int | None = Field(default=None, ge=0)


class ConnectorHelloPayload(StrictModel):
    installationId: UUID
    connectorType: ConnectorType
    connectorVersion: str = Field(min_length=1, max_length=64)
    targetAppVersion: str = Field(min_length=1, max_length=128)
    adapterVersion: str = Field(min_length=1, max_length=64)
    capabilities: list[ConnectorCapability] = Field(min_length=1)

    @field_validator("capabilities")
    @classmethod
    def capabilities_must_be_unique(
        cls, capabilities: list[ConnectorCapability]
    ) -> list[ConnectorCapability]:
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("capabilities must not contain duplicates")
        return capabilities


class ConnectorWelcomePayload(StrictModel):
    accepted: Literal[True]
    connectorType: ConnectorType
    serverVersion: str
    negotiatedCapabilities: list[ConnectorCapability]
    heartbeatIntervalSeconds: int = Field(ge=5, le=300)


class ConnectorHeartbeatPayload(StrictModel):
    installationId: UUID
    status: Literal["ready", "degraded"]
    activeTarget: bool
    currentTrackId: str | None = Field(default=None, max_length=128)


class CatalogSearchRequestPayload(StrictModel):
    query: str = Field(min_length=1, max_length=512)
    expectedTrack: TrackReference
    limit: int = Field(default=10, ge=1, le=50)


class CatalogSearchResult(StrictModel):
    sourceTrackId: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    artists: list[str] = Field(min_length=1, max_length=32)
    album: str | None = Field(default=None, max_length=512)
    playable: bool | None = None
    confidence: float = Field(ge=0, le=1)


class CatalogSearchCompletedPayload(StrictModel):
    results: list[CatalogSearchResult] = Field(max_length=50)


class PlaybackQueueRequestPayload(StrictModel):
    playlistId: UUID
    snapshotHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stopAfterLast: Literal[True]
    tracks: list[TrackReference] = Field(min_length=1)

    @field_validator("tracks")
    @classmethod
    def tracks_must_be_unique(cls, tracks: list[TrackReference]) -> list[TrackReference]:
        ids = [track.sourceTrackId for track in tracks]
        if len(ids) != len(set(ids)):
            raise ValueError("tracks must not contain duplicate sourceTrackId values")
        return tracks


class PlaybackQueueAcceptedPayload(StrictModel):
    playlistId: UUID
    snapshotHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    acceptedTrackIds: list[str]
    rejectedTrackIds: list[str] = Field(default_factory=list)


class PlaybackQueueRejectedPayload(StrictModel):
    playlistId: UUID
    snapshotHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code: Literal[
        "connector.notReady",
        "connector.capabilityMissing",
        "connector.targetIncompatible",
        "queue.snapshotMismatch",
        "queue.trackNotFound",
        "queue.trackUnplayable",
        "queue.ambiguousTrack",
        "queue.operationFailed",
    ]
    message: str = Field(min_length=1, max_length=512)


class PlaybackActionRequestPayload(StrictModel):
    action: PlaybackAction
    playlistId: UUID | None = None


class PlaybackStateChangedPayload(StrictModel):
    status: PlaybackStatus
    playlistId: UUID | None = None
    sourceTrackId: str | None = Field(default=None, max_length=128)
    positionMs: int | None = Field(default=None, ge=0)
    durationMs: int | None = Field(default=None, ge=0)
    queueIndex: int | None = Field(default=None, ge=0)
    errorCode: str | None = Field(default=None, max_length=128)


class MessageEnvelope(StrictModel):
    protocolVersion: Literal["1.0"]
    requestId: UUID
    sentAt: AwareDatetime


class ConnectorHelloMessage(MessageEnvelope):
    type: Literal["connector.hello"]
    payload: ConnectorHelloPayload


class ConnectorWelcomeMessage(MessageEnvelope):
    type: Literal["connector.welcome"]
    payload: ConnectorWelcomePayload


class ConnectorHeartbeatMessage(MessageEnvelope):
    type: Literal["connector.heartbeat"]
    payload: ConnectorHeartbeatPayload


class CatalogSearchRequestedMessage(MessageEnvelope):
    type: Literal["catalog.searchRequested"]
    payload: CatalogSearchRequestPayload


class CatalogSearchCompletedMessage(MessageEnvelope):
    type: Literal["catalog.searchCompleted"]
    payload: CatalogSearchCompletedPayload


class PlaybackQueueRequestedMessage(MessageEnvelope):
    type: Literal["playback.queueRequested"]
    payload: PlaybackQueueRequestPayload


class PlaybackQueueAcceptedMessage(MessageEnvelope):
    type: Literal["playback.queueAccepted"]
    payload: PlaybackQueueAcceptedPayload


class PlaybackQueueRejectedMessage(MessageEnvelope):
    type: Literal["playback.queueRejected"]
    payload: PlaybackQueueRejectedPayload


class PlaybackActionRequestedMessage(MessageEnvelope):
    type: Literal["playback.actionRequested"]
    payload: PlaybackActionRequestPayload


class PlaybackStateChangedMessage(MessageEnvelope):
    type: Literal["playback.stateChanged"]
    payload: PlaybackStateChangedPayload


ConnectorMessage = Annotated[
    ConnectorHelloMessage
    | ConnectorWelcomeMessage
    | ConnectorHeartbeatMessage
    | CatalogSearchRequestedMessage
    | CatalogSearchCompletedMessage
    | PlaybackQueueRequestedMessage
    | PlaybackQueueAcceptedMessage
    | PlaybackQueueRejectedMessage
    | PlaybackActionRequestedMessage
    | PlaybackStateChangedMessage,
    Field(discriminator="type"),
]

CONNECTOR_MESSAGE_ADAPTER = TypeAdapter(ConnectorMessage)


class ConnectorProtocolDescriptor(StrictModel):
    protocolVersion: str
    connectorTypes: list[str]
    capabilities: list[str]
    messageTypes: list[str]


def connector_protocol_descriptor() -> ConnectorProtocolDescriptor:
    return ConnectorProtocolDescriptor(
        protocolVersion=PROTOCOL_VERSION,
        connectorTypes=list(SUPPORTED_CONNECTOR_TYPES),
        capabilities=list(SUPPORTED_CAPABILITIES),
        messageTypes=[
            "connector.hello",
            "connector.welcome",
            "connector.heartbeat",
            "catalog.searchRequested",
            "catalog.searchCompleted",
            "playback.queueRequested",
            "playback.queueAccepted",
            "playback.queueRejected",
            "playback.actionRequested",
            "playback.stateChanged",
        ],
    )


def negotiate_connector(
    hello: ConnectorHelloMessage,
    *,
    server_version: str = "0.1.0",
    heartbeat_interval_seconds: int = 15,
) -> ConnectorWelcomeMessage:
    negotiated = [
        capability
        for capability in SUPPORTED_CAPABILITIES
        if capability in hello.payload.capabilities
    ]
    return ConnectorWelcomeMessage(
        protocolVersion=PROTOCOL_VERSION,
        type="connector.welcome",
        requestId=hello.requestId,
        sentAt=datetime.now(UTC),
        payload=ConnectorWelcomePayload(
            accepted=True,
            connectorType=hello.payload.connectorType,
            serverVersion=server_version,
            negotiatedCapabilities=negotiated,
            heartbeatIntervalSeconds=heartbeat_interval_seconds,
        ),
    )


def connector_message_json_schema() -> dict:
    return CONNECTOR_MESSAGE_ADAPTER.json_schema()
