from __future__ import annotations

import os
from pathlib import Path

import pytest

from moodmusic_api.credentials import (
    InvalidCookieError,
    WindowsCredentialStore,
    parse_cookie_header,
)


def test_parse_cookie_extracts_uin() -> None:
    parsed = parse_cookie_header("uin=12345678; qm_keyst=secret-value")

    assert parsed.uin == "12345678"
    assert parsed.values["qm_keyst"] == "secret-value"


@pytest.mark.parametrize(
    "cookie",
    [
        "",
        "uin=12345678",
        "qm_keyst=secret-value",
        "uin=12345678; qm_keyst=secret-value\r\nInjected: yes",
    ],
)
def test_parse_cookie_rejects_unusable_values(cookie: str) -> None:
    with pytest.raises(InvalidCookieError):
        parse_cookie_header(cookie)


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI is required")
def test_dpapi_store_supports_long_cookie(tmp_path: Path) -> None:
    store = WindowsCredentialStore(base_directory=tmp_path)
    cookie = f"uin=12345678; qm_keyst={'x' * 4_000}"

    store.set_qqmusic_cookie(cookie)

    encrypted = store.credential_path.read_bytes()
    assert cookie.encode("utf-8") not in encrypted
    assert store.get_qqmusic_cookie() == cookie
    assert store.delete_qqmusic_cookie() is True
    assert store.get_qqmusic_cookie() is None
