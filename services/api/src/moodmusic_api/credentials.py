from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Protocol

MAX_COOKIE_LENGTH = 16_384
CRYPTPROTECT_UI_FORBIDDEN = 0x1
QQMUSIC_DPAPI_ENTROPY = b"MoodMusic:v1:qqmusic-cookie"
DEEPSEEK_DPAPI_ENTROPY = b"MoodMusic:v1:deepseek-api-key"


class CredentialStoreError(RuntimeError):
    """Raised when the operating-system credential store cannot be used."""


class InvalidCookieError(ValueError):
    """Raised when a pasted Cookie header is not safe or usable."""


class CredentialStore(Protocol):
    def set_qqmusic_cookie(self, cookie: str) -> None: ...

    def get_qqmusic_cookie(self) -> str | None: ...

    def delete_qqmusic_cookie(self) -> bool: ...


@dataclass(frozen=True)
class ParsedCookie:
    raw: str
    values: dict[str, str]

    @property
    def uin(self) -> str:
        for key in ("uin", "wxuin", "p_uin"):
            value = self.values.get(key)
            if value:
                return value
        raise InvalidCookieError("Cookie 中没有找到 QQ 音乐用户标识，请重新复制完整 Cookie。")


def parse_cookie_header(raw_cookie: str) -> ParsedCookie:
    cookie = raw_cookie.strip()
    if not cookie:
        raise InvalidCookieError("Cookie 不能为空。")
    if len(cookie) > MAX_COOKIE_LENGTH:
        raise InvalidCookieError("Cookie 长度异常，请只粘贴 QQ 音乐请求中的 Cookie。")
    if "\r" in cookie or "\n" in cookie:
        raise InvalidCookieError("Cookie 不能包含换行符。")

    parsed = SimpleCookie()
    try:
        parsed.load(cookie)
    except CookieError as exc:
        raise InvalidCookieError("Cookie 格式无法识别，请重新复制完整 Cookie。") from exc

    values = {name: morsel.value for name, morsel in parsed.items()}
    if not values:
        raise InvalidCookieError("Cookie 格式无法识别，请重新复制完整 Cookie。")

    session_key_names = ("qm_keyst", "qqmusic_key", "skey", "p_skey")
    if not any(values.get(name) for name in session_key_names):
        raise InvalidCookieError("Cookie 中没有找到登录凭据，请确认 QQ 音乐网页版已登录。")

    parsed_cookie = ParsedCookie(raw=cookie, values=values)
    _ = parsed_cookie.uin
    return parsed_cookie


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _as_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(data), pointer), buffer


def _protect(data: bytes, entropy: bytes = QQMUSIC_DPAPI_ENTROPY) -> bytes:
    if os.name != "nt":
        raise CredentialStoreError("DPAPI 凭据存储只支持 Windows。")

    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    input_blob, input_buffer = _as_blob(data)
    entropy_blob, entropy_buffer = _as_blob(entropy)
    output_blob = _DataBlob()
    _ = input_buffer, entropy_buffer

    succeeded = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "MoodMusic QQ Music Cookie",
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not succeeded:
        raise CredentialStoreError("Windows DPAPI 无法加密 QQ 音乐 Cookie。")

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect(data: bytes, entropy: bytes = QQMUSIC_DPAPI_ENTROPY) -> bytes:
    if os.name != "nt":
        raise CredentialStoreError("DPAPI 凭据存储只支持 Windows。")

    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    input_blob, input_buffer = _as_blob(data)
    entropy_blob, entropy_buffer = _as_blob(entropy)
    output_blob = _DataBlob()
    _ = input_buffer, entropy_buffer

    succeeded = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not succeeded:
        raise CredentialStoreError("Windows DPAPI 无法解密 QQ 音乐 Cookie。")

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _default_credential_directory() -> Path:
    configured_data_directory = os.environ.get("MOODMUSIC_DATA_DIR")
    if configured_data_directory:
        return Path(configured_data_directory).expanduser().resolve() / "credentials"

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise CredentialStoreError("无法确定当前 Windows 用户的本机数据目录。")
    return Path(local_app_data) / "MoodMusic" / "credentials"


class WindowsCredentialStore:
    """Stores a long QQ Music Cookie in a current-user DPAPI encrypted file."""

    def __init__(self, base_directory: Path | None = None) -> None:
        directory = base_directory or _default_credential_directory()
        self.credential_path = directory / "qqmusic-cookie.dpapi"

    def set_qqmusic_cookie(self, cookie: str) -> None:
        parsed = parse_cookie_header(cookie)
        encrypted = _protect(parsed.raw.encode("utf-8"))
        temporary_path = self.credential_path.with_suffix(".dpapi.tmp")

        try:
            self.credential_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_bytes(encrypted)
            os.replace(temporary_path, self.credential_path)
        except OSError as exc:
            raise CredentialStoreError("无法保存 DPAPI 加密的 QQ 音乐 Cookie。") from exc
        finally:
            temporary_path.unlink(missing_ok=True)

    def get_qqmusic_cookie(self) -> str | None:
        if not self.credential_path.exists():
            return None
        try:
            encrypted = self.credential_path.read_bytes()
            cookie = _unprotect(encrypted).decode("utf-8")
            return parse_cookie_header(cookie).raw
        except CredentialStoreError:
            raise
        except (OSError, UnicodeError, InvalidCookieError) as exc:
            raise CredentialStoreError("无法读取 DPAPI 加密的 QQ 音乐 Cookie。") from exc

    def delete_qqmusic_cookie(self) -> bool:
        try:
            self.credential_path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CredentialStoreError("无法删除 DPAPI 加密的 QQ 音乐 Cookie。") from exc
        return True


class ModelCredentialStore:
    """Stores the DeepSeek API key in a separate current-user DPAPI envelope."""

    def __init__(self, base_directory: Path | None = None) -> None:
        directory = base_directory or _default_credential_directory()
        self.credential_path = directory / "deepseek-api-key.dpapi"

    def set_deepseek_api_key(self, api_key: str) -> None:
        normalized = api_key.strip()
        if not normalized or len(normalized) > 512 or "\r" in normalized or "\n" in normalized:
            raise InvalidCookieError("API Key 格式无效。")
        encrypted = _protect(normalized.encode("utf-8"), DEEPSEEK_DPAPI_ENTROPY)
        temporary_path = self.credential_path.with_suffix(".dpapi.tmp")
        try:
            self.credential_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_bytes(encrypted)
            os.replace(temporary_path, self.credential_path)
        except OSError as exc:
            raise CredentialStoreError("无法保存 DPAPI 加密的模型 API Key。") from exc
        finally:
            temporary_path.unlink(missing_ok=True)

    def get_deepseek_api_key(self) -> str | None:
        if not self.credential_path.exists():
            return None
        try:
            encrypted = self.credential_path.read_bytes()
            return _unprotect(encrypted, DEEPSEEK_DPAPI_ENTROPY).decode("utf-8")
        except CredentialStoreError:
            raise
        except (OSError, UnicodeError) as exc:
            raise CredentialStoreError("无法读取 DPAPI 加密的模型 API Key。") from exc

    def delete_deepseek_api_key(self) -> bool:
        try:
            self.credential_path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CredentialStoreError("无法删除 DPAPI 加密的模型 API Key。") from exc
        return True
