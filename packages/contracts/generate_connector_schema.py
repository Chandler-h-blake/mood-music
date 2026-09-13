from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "services" / "api" / "src"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "connector-message-v1.schema.json"

sys.path.insert(0, str(API_SRC))

from moodmusic_api.connector_protocol import connector_message_json_schema  # noqa: E402


def main() -> None:
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = connector_message_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://moodmusic.local/contracts/connector-message-v1.schema.json"
    schema["title"] = "MoodMusic Connector Message v1"
    SCHEMA_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
