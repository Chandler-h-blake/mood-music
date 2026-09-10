from __future__ import annotations

import json

import httpx
import pytest

from moodmusic_api.qqmusic import QQMusicClient


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
