from __future__ import annotations

import json
from pathlib import Path

from moodmusic_api.connector_protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_CAPABILITIES,
    SUPPORTED_CONNECTOR_TYPES,
)

ROOT = Path(__file__).resolve().parents[3]
EXTENSION = ROOT / "extensions" / "qqmusic-web-connector"


def test_extension_manifest_has_minimum_permissions() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {"activeTab", "storage"}
    assert set(manifest["host_permissions"]) == {
        "http://127.0.0.1:8000/*",
        "https://y.qq.com/*",
    }
    assert manifest["content_scripts"][0]["matches"] == ["https://y.qq.com/*"]


def test_probe_iteration_cannot_read_credentials_or_click_page() -> None:
    source = "\n".join(
        (EXTENSION / name).read_text(encoding="utf-8")
        for name in ["service-worker.js", "content-adapter.js", "popup.js"]
    )

    forbidden = [
        "document.cookie",
        "chrome.cookies",
        "chrome.webRequest",
        "nativeMessaging",
        ".click(",
        "eval(",
        "new Function(",
    ]
    assert all(value not in source for value in forbidden)
    assert '[class*="playlist"]' not in source
    assert '[class*="queue"]' not in source


def test_extension_contract_bundle_matches_protocol_constants() -> None:
    source = (EXTENSION / "connector-contract.js").read_text(encoding="utf-8")

    assert f'PROTOCOL_VERSION = "{PROTOCOL_VERSION}"' in source
    for connector_type in SUPPORTED_CONNECTOR_TYPES:
        assert f'"{connector_type}"' in source
    for capability in SUPPORTED_CAPABILITIES:
        assert f'"{capability}"' in source
