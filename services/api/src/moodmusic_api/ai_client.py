from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from .models import SearchIntent, SongProfileBatch


class ModelConfigurationError(RuntimeError):
    """The local model configuration is incomplete or inconsistent."""


class ModelRequestError(RuntimeError):
    """A model provider request failed or returned invalid structured data."""


class InvalidModelResponseError(ModelRequestError):
    """The provider responded, but the structured content was unusable."""


class DeepSeekModelClient:
    def __init__(self, *, timeout: float = 120.0) -> None:
        self.base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.chat_model = os.environ.get("CHAT_MODEL", "deepseek-flash")
        self.timeout = timeout

    async def profile_songs(self, api_key: str, songs: list[dict[str, Any]]) -> SongProfileBatch:
        return await self._structured_response(
            api_key,
            schema_model=SongProfileBatch,
            schema_name="song_profile_batch",
            instructions=(
                "你是严谨的音乐资料分析器。只根据提供的歌名、歌手、专辑与时长建立画像。"
                "不得伪造 BPM、歌词事实或音频测量；不确定的标量使用 null。"
                "情绪和场景可以做谨慎的模型推断，但 confidence 必须反映有限证据。"
                "每首输入必须恰好输出一次，sourceTrackId 原样返回。semanticDescription 要用中文，"
                "紧凑覆盖曲风、氛围、情绪、能量、人声、适用场景及明确的不适用感觉。"
            ),
            input_text=json.dumps({"songs": songs}, ensure_ascii=False),
        )

    async def understand_feeling(self, api_key: str, description: str) -> SearchIntent:
        return await self._structured_response(
            api_key,
            schema_model=SearchIntent,
            schema_name="music_search_intent",
            instructions=(
                "把用户想听的整体感觉转换成音乐检索意图。保留程度词和否定要求。"
                "semanticQuery 写成可与歌曲画像比较的完整正向描述，同时在 exclusions 中列出排除项，"
                "明确排除的流派同时规范化写入 excludedGenres。"
                "只有用户明确提到悲伤、紧张或能量上限时，才分别填写 maxSadness、maxTension、"
                "maxEnergy；不要因为用户想轻松或愉快就自行添加悲伤上限。"
                "人声要求必须写入 requiredVocalModes 或 excludedVocalModes，枚举含 male_solo、"
                "female_solo、mixed_duet、male_duet、female_duet、group、choir、instrumental、other。"
                "‘男女对唱’必须设 requiredVocalModes=['mixed_duet'] 且 instrumentalAllowed=false。"
                "明确语言要求写入 allowedLanguages，明确不要的语言写入 excludedLanguages，使用 zh、"
                "yue、en、ja、ko、es、fr、de、ru、other。粤语使用 yue，普通话或泛华语使用 zh。"
                "balanced 默认 threshold 取 0.75，需求宽泛时不低于 0.72，"
                "严格复合需求时可提高到 0.78。"
            ),
            input_text=description,
        )

    async def test_connection(self, api_key: str) -> None:
        await self.understand_feeling(api_key, "安静放松的音乐")

    async def _structured_response[T: BaseModel](
        self,
        api_key: str,
        *,
        schema_model: type[T],
        schema_name: str,
        instructions: str,
        input_text: str,
    ) -> T:
        payload = {
            "model": self.chat_model,
            "instructions": instructions,
            "input": input_text,
            "reasoning": {"effort": "none"},
            "max_output_tokens": 16_000,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": self._strict_json_schema(schema_model.model_json_schema()),
                }
            },
        }
        data = await self._post(api_key, "/responses", payload)
        output_text = data.get("output_text")
        if not output_text:
            for item in data.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text")
                        break
        if not isinstance(output_text, str) or not output_text.strip():
            raise InvalidModelResponseError("模型没有返回结构化文本。")
        last_error: ValidationError | None = None
        for candidate in self._json_candidates(output_text):
            try:
                return schema_model.model_validate_json(candidate)
            except ValidationError as exc:
                last_error = exc
        assert last_error is not None
        issues = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in last_error.errors(include_url=False)[:3]
        )
        raise InvalidModelResponseError(f"模型输出未通过 schema 校验：{issues}") from last_error

    @staticmethod
    def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
        """Adapt Pydantic schemas to DeepSeek's strict structured-output subset."""
        result = copy.deepcopy(schema)

        def visit(node: object) -> None:
            if isinstance(node, dict):
                node.pop("default", None)
                properties = node.get("properties")
                if isinstance(properties, dict):
                    node["required"] = list(properties)
                    node["additionalProperties"] = False
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(result)
        return result

    @staticmethod
    def _json_candidates(output_text: str) -> list[str]:
        """Accept JSON wrapped in prose or Markdown despite structured-output mode."""
        stripped = output_text.strip()
        candidates = [stripped]
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                candidates.append("\n".join(lines[1:-1]).strip())
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            candidates.append(stripped[start : end + 1])
        return list(dict.fromkeys(candidate for candidate in candidates if candidate))

    async def _post(self, api_key: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}{path}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            provider_message = self._provider_error_message(exc.response)
            message = "模型凭据无效。" if code in {401, 403} else f"模型服务返回 HTTP {code}。"
            if provider_message:
                message = f"{message} {provider_message}"
            raise ModelRequestError(message) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelRequestError("无法连接模型服务或响应不是有效 JSON。") from exc

    @staticmethod
    def _provider_error_message(response: httpx.Response) -> str | None:
        """Return only the provider's bounded error message, never request headers or secrets."""
        try:
            payload = response.json()
        except ValueError:
            return None
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if not isinstance(message, str) or not message.strip():
            return None
        return message.strip()[:500]


class LocalEmbeddingClient:
    """Lazily loads BGE-M3 and keeps song metadata on the local machine."""

    def __init__(self) -> None:
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")
        self.embedding_dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))
        if self.embedding_dimensions != 1024:
            raise ModelConfigurationError(
                "BGE-M3 与当前数据库均使用 1024 维，请将 EMBEDDING_DIMENSIONS 设为 1024。"
            )
        self._model: Any | None = None
        self._lock = asyncio.Lock()
        configured_data_dir = os.environ.get("MOODMUSIC_DATA_DIR")
        data_dir = (
            Path(configured_data_dir).expanduser().resolve()
            if configured_data_dir
            else Path(__file__).resolve().parents[4] / "data"
        )
        self._cache_dir = data_dir / "models" / "huggingface"

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ModelRequestError("Embedding 输入不能为空。")
        async with self._lock:
            try:
                return await asyncio.to_thread(self._encode, texts)
            except ModelRequestError:
                raise
            except Exception as exc:
                raise ModelRequestError(
                    "本地 BGE-M3 向量生成失败，请检查模型依赖和磁盘空间。"
                ) from exc

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError as exc:
                raise ModelRequestError("缺少 FlagEmbedding，请重新安装 API 依赖。") from exc
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = BGEM3FlagModel(
                self.embedding_model,
                use_fp16=False,
                cache_dir=str(self._cache_dir),
            )
        result = self._model.encode(
            texts,
            batch_size=min(16, len(texts)),
            max_length=1024,
        )
        vectors = result["dense_vecs"].tolist()
        if len(vectors) != len(texts) or any(
            len(vector) != self.embedding_dimensions for vector in vectors
        ):
            raise ModelRequestError("BGE-M3 输出数量或维度不匹配。")
        return vectors
