from __future__ import annotations

import json

import httpx
import pytest

from moodmusic_api.qqmusic import QQMusicClient, QQMusicRequestError


@pytest.mark.asyncio
async def test_resolve_numeric_song_ids_batches_mids() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["songmid"] == "003ekipq2vkaTF,002nYCor10GXh2"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [
                    {"mid": "003ekipq2vkaTF", "id": 252745135},
                    {"mid": "002nYCor10GXh2", "id": 472845496},
                ],
            },
        )

    client = QQMusicClient(transport=httpx.MockTransport(handler))

    result = await client.resolve_numeric_song_ids(
        ["003ekipq2vkaTF", "002nYCor10GXh2"]
    )

    assert result == {
        "003ekipq2vkaTF": 252745135,
        "002nYCor10GXh2": 472845496,
    }


@pytest.mark.asyncio
async def test_resolve_numeric_song_ids_respects_qqmusic_fifty_song_limit() -> None:
    mids = [f"{index:014d}" for index in range(76)]
    batches: list[list[str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        batch = request.url.params["songmid"].split(",")
        batches.append(batch)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [
                    {"mid": mid, "id": int(mid) + 1}
                    for mid in batch
                ],
            },
        )

    client = QQMusicClient(transport=httpx.MockTransport(handler))

    result = await client.resolve_numeric_song_ids(mids)

    assert [len(batch) for batch in batches] == [50, 26]
    assert len(result) == 76


@pytest.mark.asyncio
async def test_resolve_numeric_song_ids_keeps_old_mid_when_qqmusic_canonicalizes_it() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [{"mid": "0025sxHg4J8XEn", "id": 276964034}],
            },
        )

    client = QQMusicClient(transport=httpx.MockTransport(handler))

    result = await client.resolve_numeric_song_ids(["003UWh7a3V5Xhv"])

    assert result == {"003UWh7a3V5Xhv": 276964034}


@pytest.mark.asyncio
async def test_resolve_numeric_song_ids_rejects_non_qqmusic_mid() -> None:
    client = QQMusicClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))

    with pytest.raises(QQMusicRequestError, match="歌曲标识"):
        await client.resolve_numeric_song_ids(["metadata-sha256:unsafe"])


@pytest.mark.asyncio
async def test_fetch_liked_page_maps_qqmusic_response_without_exposing_cookie() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "req_0": {
                    "code": 0,
                    "data": {
                        "total_song_num": 1087,
                        "songlist": [
                            {
                                "songmid": "song-mid-1",
                                "songname": "示例歌曲",
                                "singer": [{"name": "示例歌手"}],
                                "albumname": "示例专辑",
                                "interval": 245,
                            }
                        ],
                    },
                }
            },
        )

    client = QQMusicClient(transport=httpx.MockTransport(handler))
    result, masked_account = await client.fetch_liked_page(
        "uin=12345678; qm_keyst=do-not-log-this",
        page=0,
        page_size=30,
    )

    assert result.total == 1087
    assert result.songs[0].sourceTrackId == "song-mid-1"
    assert result.songs[0].artists[0].name == "示例歌手"
    assert result.songs[0].durationMs == 245_000
    assert masked_account == "12****78"
    assert captured_request is not None

    request_payload = json.loads(captured_request.content)
    assert request_payload["req_0"]["param"]["dirid"] == 201
    assert request_payload["req_0"]["param"]["song_begin"] == 0
    assert captured_request.headers["cookie"] == "uin=12345678; qm_keyst=do-not-log-this"


@pytest.mark.asyncio
async def test_fetch_all_liked_songs_reads_every_page_and_preserves_order() -> None:
    offsets: list[int] = []
    all_songs = [
        {
            "songmid": f"song-{index:03d}",
            "songname": f"歌曲 {index}",
            "singer": [{"name": "歌手"}],
            "interval": 180,
        }
        for index in range(205)
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        params = payload["req_0"]["param"]
        begin = params["song_begin"]
        size = params["song_num"]
        offsets.append(begin)
        return httpx.Response(
            200,
            json={
                "req_0": {
                    "code": 0,
                    "data": {
                        "total_song_num": len(all_songs),
                        "songlist": all_songs[begin : begin + size],
                    },
                }
            },
        )

    client = QQMusicClient(transport=httpx.MockTransport(handler))
    snapshot, _ = await client.fetch_all_liked_songs(
        "uin=12345678; qm_keyst=test-secret",
        request_delay_seconds=0,
    )

    assert offsets == [0, 100, 200]
    assert snapshot.reported_total == 205
    assert snapshot.pages_fetched == 3
    assert snapshot.fetched_count == 205
    assert len(snapshot.unique_songs) == 205
    assert snapshot.unique_songs[0].sourceTrackId == "song-000"
    assert snapshot.unique_songs[-1].sourceTrackId == "song-204"


@pytest.mark.asyncio
async def test_fetch_all_liked_songs_deduplicates_track_ids() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "req_0": {
                    "code": 0,
                    "data": {
                        "total_song_num": 3,
                        "songlist": [
                            {"songmid": "song-a", "songname": "A", "singer": []},
                            {"songmid": "song-a", "songname": "A", "singer": []},
                            {"songmid": "song-b", "songname": "B", "singer": []},
                        ],
                    },
                }
            },
        )

    client = QQMusicClient(transport=httpx.MockTransport(handler))
    snapshot, _ = await client.fetch_all_liked_songs(
        "uin=12345678; qm_keyst=test-secret", request_delay_seconds=0
    )

    assert snapshot.fetched_count == 3
    assert [song.sourceTrackId for song in snapshot.unique_songs] == ["song-a", "song-b"]


def test_map_song_builds_stable_private_id_when_qqmusic_id_is_missing() -> None:
    raw_song = {
        "songname": "已下架歌曲",
        "singer": [{"name": "示例歌手"}],
        "albumname": "示例专辑",
        "interval": 180,
    }

    first = QQMusicClient._map_song(raw_song)
    second = QQMusicClient._map_song(raw_song)

    assert first.sourceTrackId == second.sourceTrackId
    assert first.sourceTrackId.startswith("metadata-sha256:")
    assert "已下架歌曲" not in first.sourceTrackId


@pytest.mark.asyncio
async def test_fetch_all_liked_songs_rejects_a_changed_total() -> None:
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        total = 101 if call_count == 1 else 102
        begin = json.loads(request.content)["req_0"]["param"]["song_begin"]
        count = 100 if begin == 0 else 1
        songs = [
            {"songmid": f"song-{begin + index}", "songname": "歌曲", "singer": []}
            for index in range(count)
        ]
        return httpx.Response(
            200,
            json={"req_0": {"code": 0, "data": {"total_song_num": total, "songlist": songs}}},
        )

    client = QQMusicClient(transport=httpx.MockTransport(handler))

    with pytest.raises(QQMusicRequestError, match="发生变化"):
        await client.fetch_all_liked_songs(
            "uin=12345678; qm_keyst=test-secret",
            request_delay_seconds=0,
        )
