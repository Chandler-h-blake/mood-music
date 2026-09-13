from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from moodmusic_api.connector_protocol import (
    CONNECTOR_MESSAGE_ADAPTER,
    ConnectorHelloMessage,
    ConnectorHelloPayload,
    PlaybackQueueRequestPayload,
    TrackReference,
    connector_message_json_schema,
    negotiate_connector,
)
from moodmusic_api.main import create_app

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "packages" / "contracts" / "schema" / "connector-message-v1.schema.json"


def hello_message(connector_type: str) -> ConnectorHelloMessage:
    return ConnectorHelloMessage(
        protocolVersion="1.0",
        type="connector.hello",
        requestId=uuid4(),
        sentAt=datetime.now(UTC),
        payload=ConnectorHelloPayload(
            installationId=uuid4(),
            connectorType=connector_type,
            connectorVersion="0.1.0",
            targetAppVersion="QQMusic test",
            adapterVersion="qqmusic-test-v1",
            capabilities=["queue.play", "playback.state"],
        ),
    )


@pytest.mark.parametrize("connector_type", ["web", "pc"])
def test_web_and_pc_connectors_share_negotiation(connector_type: str) -> None:
    hello = hello_message(connector_type)
    welcome = negotiate_connector(hello)

    assert welcome.requestId == hello.requestId
    assert welcome.payload.connectorType == connector_type
    assert welcome.payload.negotiatedCapabilities == ["queue.play", "playback.state"]
    assert welcome.payload.heartbeatIntervalSeconds == 15


def test_connector_capabilities_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        ConnectorHelloPayload(
            installationId=uuid4(),
            connectorType="web",
            connectorVersion="0.1.0",
            targetAppVersion="QQMusic test",
            adapterVersion="qqmusic-web-v1",
            capabilities=["queue.play", "queue.play"],
        )


def test_queue_requires_stable_snapshot_and_unique_tracks() -> None:
    track = TrackReference(sourceTrackId="mid-1", title="Song", artists=["Artist"])

    with pytest.raises(ValidationError):
        PlaybackQueueRequestPayload(
            playlistId=uuid4(),
            snapshotHash="not-a-sha256",
            stopAfterLast=True,
            tracks=[track],
        )

    with pytest.raises(ValidationError):
        PlaybackQueueRequestPayload(
            playlistId=uuid4(),
            snapshotHash="a" * 64,
            stopAfterLast=True,
            tracks=[track, track],
        )


def test_message_discriminator_rejects_mismatched_payload() -> None:
    hello = hello_message("pc").model_dump(mode="json")
    hello["type"] = "playback.queueRequested"

    with pytest.raises(ValidationError):
        CONNECTOR_MESSAGE_ADAPTER.validate_python(hello)


def test_envelope_requires_explicit_protocol_version() -> None:
    hello = hello_message("web").model_dump(mode="json")
    del hello["protocolVersion"]

    with pytest.raises(ValidationError):
        CONNECTOR_MESSAGE_ADAPTER.validate_python(hello)


def test_checked_in_json_schema_matches_runtime_models() -> None:
    checked_in = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    checked_in.pop("$schema")
    checked_in.pop("$id")
    checked_in.pop("title")

    assert checked_in == connector_message_json_schema()


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_type", ["web", "pc"])
async def test_protocol_http_negotiation(connector_type: str) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        descriptor = await client.get("/api/v1/connectors/protocol")
        response = await client.post(
            "/api/v1/connectors/negotiate",
            json=hello_message(connector_type).model_dump(mode="json"),
        )

    assert descriptor.status_code == 200
    assert descriptor.json()["connectorTypes"] == ["web", "pc"]
    assert response.status_code == 200
    assert response.json()["payload"]["connectorType"] == connector_type
