from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil
from typing import Any

import httpx

from .credentials import ParsedCookie, parse_cookie_header
from .models import ArtistPreview, LikedPagePreview, SongPreview

QQMUSIC_API_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
QQMUSIC_SONG_DETAIL_URL = "https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg"
DEFAULT_PAGE_SIZE = 30
SYNC_PAGE_SIZE = 100
MAX_SYNC_PAGES = 200
SONG_DETAIL_BATCH_SIZE = 50


class QQMusicRequestError(RuntimeError):
    """A safe, user-facing category for QQ Music request failures."""


class QQMusicAuthenticationError(QQMusicRequestError):
    """The saved QQ Music session is missing or no longer accepted."""


@dataclass(frozen=True)
class LikedLibrarySnapshot:
    reported_total: int
    pages_fetched: int
    fetched_count: int
    unique_songs: list[SongPreview]
    skipped_missing_id: int


def _mask_account(uin: str) -> str:
    if len(uin) <= 4:
        return "*" * len(uin)
    return f"{uin[:2]}{'*' * (len(uin) - 4)}{uin[-2:]}"


class QQMusicClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def resolve_numeric_song_ids(
        self, source_track_ids: list[str]
    ) -> dict[str, int]:
        """Resolve public QQ Music song mids to the numeric IDs used by the PC client."""
        if not source_track_ids:
            return {}
        invalid = [
            value
            for value in source_track_ids
            if not re.fullmatch(r"[A-Za-z0-9]{14}", value)
        ]
        if invalid:
            raise QQMusicRequestError("临时队列包含 QQ 音乐无法识别的歌曲标识。")

        resolved: dict[str, int] = {}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://y.qq.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                for offset in range(0, len(source_track_ids), SONG_DETAIL_BATCH_SIZE):
                    batch = source_track_ids[offset : offset + SONG_DETAIL_BATCH_SIZE]
                    response = await client.get(
                        QQMUSIC_SONG_DETAIL_URL,
                        params={"songmid": ",".join(batch), "format": "json"},
                        headers=headers,
                    )
                    response.raise_for_status()
                    body = response.json()
                    data = body.get("data") if isinstance(body, Mapping) else None
                    if not isinstance(data, list):
                        raise QQMusicRequestError("QQ 音乐歌曲信息接口返回结构已经变化。")
                    if len(data) != len(batch):
                        raise QQMusicRequestError("QQ 音乐没有返回完整的歌曲编号。")
                    for requested_mid, item in zip(batch, data, strict=True):
                        if not isinstance(item, Mapping):
                            continue
                        numeric_id = item.get("id")
                        if isinstance(numeric_id, int) and numeric_id > 0:
                            # QQ Music can canonicalize an old mid in the response. The
                            # endpoint preserves request order, so retain the caller's mid.
                            resolved[requested_mid] = numeric_id
        except httpx.TimeoutException as exc:
            raise QQMusicRequestError("查询 QQ 音乐歌曲编号超时，请稍后重试。") from exc
        except httpx.HTTPStatusError as exc:
            raise QQMusicRequestError("QQ 音乐歌曲信息接口暂时无法响应。") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise QQMusicRequestError("无法解析 QQ 音乐歌曲信息。") from exc

        if len(resolved) != len(set(source_track_ids)):
            raise QQMusicRequestError("队列中有歌曲无法映射到 QQ 音乐 PC 客户端。")
        return resolved

    async def fetch_all_liked_songs(
        self,
        raw_cookie: str,
        *,
        page_size: int = SYNC_PAGE_SIZE,
        max_pages: int = MAX_SYNC_PAGES,
        request_delay_seconds: float = 0.1,
    ) -> tuple[LikedLibrarySnapshot, str]:
        """Read a stable, complete snapshot while guarding against destructive partial syncs."""
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds must be non-negative")

        first_page, masked_account = await self.fetch_liked_page(
            raw_cookie, page=0, page_size=page_size
        )
        reported_total = first_page.total
        expected_pages = max(1, ceil(reported_total / page_size))
        if expected_pages > max_pages:
            raise QQMusicRequestError("“我喜欢”歌曲数量超过当前安全同步上限，已停止同步。")

        pages = [first_page]
        for page_number in range(1, expected_pages):
            if request_delay_seconds:
                await asyncio.sleep(request_delay_seconds)
            page, _ = await self.fetch_liked_page(raw_cookie, page=page_number, page_size=page_size)
            if page.total != reported_total:
                raise QQMusicRequestError("同步期间“我喜欢”发生变化，请稍后重新同步。")
            pages.append(page)

        fingerprints: set[tuple[str, ...]] = set()
        unique_by_id: dict[str, SongPreview] = {}
        fetched_count = 0
        skipped_missing_id = 0
        for page in pages:
            fingerprint = tuple(song.sourceTrackId for song in page.songs)
            if fingerprint and fingerprint in fingerprints:
                raise QQMusicRequestError("QQ 音乐返回了重复分页，已停止本次同步。")
            fingerprints.add(fingerprint)
            fetched_count += len(page.songs)
            for song in page.songs:
                if not song.sourceTrackId:
                    skipped_missing_id += 1
                    continue
                unique_by_id.setdefault(song.sourceTrackId, song)

        if fetched_count != reported_total:
            raise QQMusicRequestError("QQ 音乐分页结果不完整，已保留原有本地曲库。")
        if skipped_missing_id:
            raise QQMusicRequestError("QQ 音乐分页结果包含缺失标识的歌曲，已保留原有本地曲库。")

        return (
            LikedLibrarySnapshot(
                reported_total=reported_total,
                pages_fetched=len(pages),
                fetched_count=fetched_count,
                unique_songs=list(unique_by_id.values()),
                skipped_missing_id=skipped_missing_id,
            ),
            masked_account,
        )

    async def fetch_liked_page(
        self,
        raw_cookie: str,
        *,
        page: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[LikedPagePreview, str]:
        if page < 0:
            raise ValueError("page must be non-negative")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")

        cookie = parse_cookie_header(raw_cookie)
        payload = self._build_liked_payload(cookie, page=page, page_size=page_size)
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Cookie": cookie.raw,
            "Origin": "https://y.qq.com",
            "Referer": "https://y.qq.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(QQMUSIC_API_URL, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise QQMusicRequestError("连接 QQ 音乐超时，请稍后重试。") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise QQMusicAuthenticationError("QQ 音乐 Cookie 已失效，请重新粘贴。") from exc
            raise QQMusicRequestError("QQ 音乐暂时无法响应，请稍后重试。") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise QQMusicRequestError("无法读取 QQ 音乐响应，请检查网络或接口兼容性。") from exc

        data = self._extract_data(body)
        songs_raw = data.get("songlist") or data.get("songList") or []
        if not isinstance(songs_raw, list):
            raise QQMusicRequestError("QQ 音乐返回结构已经变化，已停止解析。")

        total_raw = data.get("total_song_num", data.get("totalSongNum", len(songs_raw)))
        try:
            total = int(total_raw)
        except (TypeError, ValueError) as exc:
            raise QQMusicRequestError("QQ 音乐返回的歌曲总数无法识别。") from exc

        songs = [self._map_song(song) for song in songs_raw if isinstance(song, Mapping)]
        return (
            LikedPagePreview(
                page=page,
                pageSize=page_size,
                total=total,
                songs=songs,
            ),
            _mask_account(cookie.uin),
        )

    @staticmethod
    def _build_liked_payload(
        cookie: ParsedCookie,
        *,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        return {
            "comm": {
                "ct": 24,
                "cv": 0,
                "format": "json",
                "uin": cookie.uin,
            },
            "req_0": {
                "module": "music.srfDissInfo.DissInfo",
                "method": "CgiGetDiss",
                "param": {
                    "disstid": 0,
                    "dirid": 201,
                    "song_begin": page * page_size,
                    "song_num": page_size,
                    "enc_host_uin": cookie.uin,
                },
            },
        }

    @staticmethod
    def _extract_data(body: Any) -> Mapping[str, Any]:
        if not isinstance(body, Mapping):
            raise QQMusicRequestError("QQ 音乐返回结构已经变化，已停止解析。")

        for key, value in body.items():
            if key == "comm" or not isinstance(value, Mapping):
                continue
            code = value.get("code", 0)
            if code not in (0, "0", None):
                if code in (-1000, 1000, 2000, 3000):
                    raise QQMusicAuthenticationError("QQ 音乐 Cookie 已失效，请重新粘贴。")
                raise QQMusicRequestError("QQ 音乐拒绝了本次只读请求。")
            data = value.get("data")
            if isinstance(data, Mapping) and (
                "songlist" in data
                or "songList" in data
                or "total_song_num" in data
                or "totalSongNum" in data
            ):
                return data

        raise QQMusicAuthenticationError("未能读取“我喜欢”，请检查 Cookie 是否完整且仍然有效。")

    @staticmethod
    def _map_song(song: Mapping[str, Any]) -> SongPreview:
        source_track_id = QQMusicClient._source_track_id(song)
        title = str(song.get("songname") or song.get("title") or "未知歌曲")

        artists_raw = song.get("singer") or song.get("artists") or []
        artists: list[ArtistPreview] = []
        if isinstance(artists_raw, list):
            for artist in artists_raw:
                if isinstance(artist, Mapping):
                    name = artist.get("name")
                    if name:
                        artists.append(ArtistPreview(name=str(name)))

        album_raw = song.get("album")
        album: str | None
        if isinstance(album_raw, Mapping):
            album = str(album_raw.get("name")) if album_raw.get("name") else None
        else:
            album_value = song.get("albumname") or album_raw
            album = str(album_value) if album_value else None

        duration_raw = song.get("interval") or song.get("duration")
        duration_ms: int | None = None
        if duration_raw is not None:
            try:
                duration_ms = int(duration_raw) * 1000
            except (TypeError, ValueError):
                duration_ms = None

        return SongPreview(
            sourceTrackId=source_track_id,
            title=title,
            artists=artists,
            album=album,
            durationMs=duration_ms,
        )

    @staticmethod
    def _source_track_id(song: Mapping[str, Any]) -> str:
        for key in ("songmid", "mid", "songid", "id"):
            value = song.get(key)
            if value not in (None, "", 0, "0"):
                return str(value)

        file_raw = song.get("file")
        if isinstance(file_raw, Mapping):
            for key in ("media_mid", "songmid", "mid"):
                value = file_raw.get(key)
                if value:
                    return str(value)

        artists_raw = song.get("singer") or song.get("artists") or []
        artist_identity: list[dict[str, str]] = []
        if isinstance(artists_raw, list):
            for artist in artists_raw:
                if isinstance(artist, Mapping):
                    artist_identity.append(
                        {
                            "id": str(artist.get("mid") or artist.get("id") or ""),
                            "name": str(artist.get("name") or ""),
                        }
                    )

        album_raw = song.get("album")
        if isinstance(album_raw, Mapping):
            album_identity: object = {
                "id": str(album_raw.get("mid") or album_raw.get("id") or ""),
                "name": str(album_raw.get("name") or ""),
            }
        else:
            album_identity = str(song.get("albumname") or album_raw or "")

        identity = {
            "title": str(song.get("songname") or song.get("title") or ""),
            "artists": artist_identity,
            "album": album_identity,
            "duration": str(song.get("interval") or song.get("duration") or ""),
        }
        canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"metadata-sha256:{digest}"
