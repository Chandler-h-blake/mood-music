from __future__ import annotations

from types import SimpleNamespace

import pytest

from moodmusic_api.ai_client import (
    DeepSeekModelClient,
    InvalidModelResponseError,
    LocalEmbeddingClient,
)
from moodmusic_api.db_models import Song
from moodmusic_api.models import (
    EmotionCurve,
    EmotionValues,
    SearchIntent,
    SongProfileBatch,
    SongProfileData,
)
from moodmusic_api.profiles import ProfileService
from moodmusic_api.semantic_search import SemanticSearchService, cosine_similarity, score_profile
from moodmusic_api.tag_normalizer import (
    apply_explicit_intent_rules,
    normalize_genres,
    normalize_language,
    normalize_profile_vocal_mode,
    normalize_vocal_mode,
)


def intent(**overrides) -> SearchIntent:
    values = {
        "summary": "安静但不悲伤的夜晚",
        "semanticQuery": "适合夜晚的安静、温暖、略带孤独但不悲伤的音乐",
        "scenes": ["夜晚"],
        "exclusions": ["不要太悲伤"],
        "excludedGenres": [],
        "requiredVocalModes": [],
        "excludedVocalModes": [],
        "allowedLanguages": [],
        "excludedLanguages": [],
        "instrumentalAllowed": None,
        "targetEnergy": 0.3,
        "maxEnergy": None,
        "targetValence": 0.55,
        "targetDanceability": None,
        "maxSadness": 0.6,
        "maxTension": 0.5,
        "threshold": 0.56,
    }
    values.update(overrides)
    return SearchIntent.model_validate(values)


def test_cosine_similarity_handles_exact_and_empty_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_provider_error_message_is_safely_extracted() -> None:
    response = __import__("httpx").Response(
        400, json={"error": {"message": "Invalid JSON schema", "code": "bad_request"}}
    )
    assert DeepSeekModelClient._provider_error_message(response) == "Invalid JSON schema"


def test_deepseek_strict_schema_requires_every_property() -> None:
    schema = DeepSeekModelClient._strict_json_schema(SearchIntent.model_json_schema())
    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False
    assert "default" not in schema["properties"]["requiredVocalModes"]


def test_explicit_sadness_boundary_is_a_hard_exclusion() -> None:
    profile = {
        "genres": ["流行"],
        "energy": 0.3,
        "valence": 0.4,
        "danceability": 0.2,
        "emotions": {"sadness": 0.9, "tension": 0.1},
    }
    score, semantic, feature, reason = score_profile(intent(), profile, [1.0, 0.0], [1.0, 0.0])
    assert (score, semantic, feature) == (0.0, 0.0, 0.0)
    assert reason == "悲伤强度超过明确上限"


def test_unknown_value_cannot_bypass_an_explicit_boundary() -> None:
    profile = {
        "genres": ["流行"],
        "energy": 0.3,
        "valence": 0.4,
        "danceability": 0.2,
        "emotions": {"sadness": None, "tension": 0.1},
    }
    score, _, _, reason = score_profile(intent(), profile, [1.0, 0.0], [1.0, 0.0])
    assert score == 0.0
    assert reason == "画像缺少悲伤强度，无法验证明确上限"


def test_balanced_score_combines_semantics_and_continuous_features() -> None:
    profile = {
        "genres": ["氛围流行"],
        "energy": 0.4,
        "valence": 0.5,
        "danceability": None,
        "emotions": {"sadness": 0.4, "tension": 0.2},
    }
    score, semantic, feature, reason = score_profile(intent(), profile, [1.0, 0.0], [1.0, 0.0])
    assert reason is None
    assert semantic == pytest.approx(1.0)
    assert feature == pytest.approx(0.925)
    assert score == pytest.approx(0.979)


def test_embedding_cosine_is_not_artificially_shifted_upward() -> None:
    profile = {
        "genres": ["流行"],
        "energy": None,
        "valence": None,
        "danceability": None,
        "emotions": {"sadness": 0.2, "tension": 0.2},
    }
    score, semantic, feature, reason = score_profile(
        intent(targetEnergy=None, targetValence=None),
        profile,
        [1.0, 0.0],
        [0.0, 1.0],
    )
    assert reason is None
    assert semantic == 0.0
    assert feature == 0.0
    assert score == 0.0


def test_free_form_profile_tags_are_normalized() -> None:
    assert normalize_language("Mandarin") == "zh"
    assert normalize_language("粤语") == "yue"
    assert normalize_language("英语") == "en"
    assert normalize_vocal_mode("male-female duet") == "mixed_duet"
    assert normalize_vocal_mode("male and female duet") == "mixed_duet"
    assert normalize_vocal_mode("纯音乐") == "instrumental"
    assert (
        normalize_profile_vocal_mode({"vocalType": "Mixed", "arrangement": ["男女对唱"]})
        == "mixed_duet"
    )
    assert (
        normalize_profile_vocal_mode(
            {"vocalType": "duet male and male", "arrangement": ["男女声对唱"]}
        )
        == "male_duet"
    )
    assert {"edm", "pop"} <= normalize_genres(["EDM", "华语流行"])


def test_required_mixed_duet_rejects_solo_and_instrumental() -> None:
    search_intent = intent(requiredVocalModes=["mixed_duet"], instrumentalAllowed=False)
    base = {
        "genres": ["抒情流行"],
        "language": "zh",
        "energy": 0.3,
        "valence": 0.5,
        "danceability": 0.2,
        "emotions": {"sadness": 0.3, "tension": 0.1},
    }
    _, _, _, solo_reason = score_profile(
        search_intent, {**base, "vocalType": "女声独唱"}, [1.0], [1.0]
    )
    duet_score, _, _, duet_reason = score_profile(
        search_intent, {**base, "vocalType": "男女对唱"}, [1.0], [1.0]
    )
    assert solo_reason == "人声类型不符合要求：女声独唱"
    assert duet_reason is None
    assert duet_score > 0


def test_explicit_rules_do_not_invent_a_sadness_boundary() -> None:
    parsed = intent(maxSadness=0.35, maxTension=0.35, maxEnergy=0.7)
    normalized = apply_explicit_intent_rules("周五下班路上，轻快松弛，别太吵", parsed)
    assert normalized.maxSadness is None
    assert normalized.maxTension == pytest.approx(0.35)
    assert normalized.maxEnergy == pytest.approx(0.7)


def test_explicit_language_rules_are_executable() -> None:
    normalized = apply_explicit_intent_rules("只听粤语歌，不要英文歌", intent())
    assert normalized.allowedLanguages == ["yue"]
    assert normalized.excludedLanguages == ["en"]


def test_explicit_duet_words_override_missing_model_constraint() -> None:
    normalized = apply_explicit_intent_rules("男女对唱的抒情歌", intent())
    assert normalized.requiredVocalModes == ["mixed_duet"]
    assert normalized.instrumentalAllowed is False


def test_emotion_curve_reorders_without_changing_candidates() -> None:
    def row(identifier: str, energy: float, valence: float, score: float):
        return (
            SimpleNamespace(id=identifier, score=score),
            SimpleNamespace(source_track_id=identifier),
            SimpleNamespace(profile={"energy": energy, "valence": valence}),
            SimpleNamespace(vector=[0.0] * 1024),
        )

    rows = [
        row("lifted", 0.78, 0.8, 0.9),
        row("settled", 0.32, 0.66, 0.8),
        row("calm", 0.25, 0.58, 0.7),
    ]
    result = SemanticSearchService._emotion_curve_order(
        rows, EmotionCurve(start="calm", middle="lifted", end="settled")
    )
    assert [item[1].source_track_id for item in result] == ["calm", "lifted", "settled"]
    assert {item[0].id for item in result} == {item[0].id for item in rows}


@pytest.mark.asyncio
async def test_structured_response_is_validated() -> None:
    class FakeClient(DeepSeekModelClient):
        async def _post(self, api_key, path, payload):
            assert api_key == "secret"
            assert path == "/responses"
            assert payload["store"] is False
            assert payload["reasoning"] == {"effort": "none"}
            return {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": SearchIntent(**intent().model_dump()).model_dump_json(),
                            }
                        ]
                    }
                ]
            }

    parsed = await FakeClient().understand_feeling("secret", "夜晚安静，但不要太悲伤")
    assert parsed.maxSadness == 0.6
    assert parsed.semanticQuery.startswith("适合夜晚")


@pytest.mark.asyncio
async def test_structured_response_accepts_markdown_wrapped_json() -> None:
    class WrappedClient(DeepSeekModelClient):
        async def _post(self, api_key, path, payload):
            content = SearchIntent(**intent().model_dump()).model_dump_json()
            return {"output_text": f"```json\n{content}\n```"}

    parsed = await WrappedClient().understand_feeling("secret", "安静的夜晚")
    assert parsed.threshold == pytest.approx(0.56)


def test_local_embedding_client_validates_bge_dimensions() -> None:
    class DenseVectors:
        def tolist(self):
            return [[0.0] * 1024]

    class FakeBGE:
        def encode(self, texts, **kwargs):
            assert texts == ["安静的音乐"]
            assert kwargs["max_length"] == 1024
            return {"dense_vecs": DenseVectors()}

    client = LocalEmbeddingClient()
    client._model = FakeBGE()
    assert len(client._encode(["安静的音乐"])[0]) == 1024


@pytest.mark.asyncio
async def test_invalid_batch_is_retried_then_split_without_losing_progress() -> None:
    class FlakyModel:
        chat_model = "deepseek-flash"

        async def profile_songs(self, api_key, songs):
            assert api_key == "secret"
            if len(songs) > 1:
                raise InvalidModelResponseError("invalid batch")
            song = songs[0]
            return SongProfileBatch(
                profiles=[
                    SongProfileData(
                        sourceTrackId=song["sourceTrackId"],
                        identitySummary=song["title"],
                        language=None,
                        vocalType=None,
                        genres=[],
                        energy=None,
                        valence=None,
                        danceability=None,
                        acousticness=None,
                        emotions=EmotionValues(
                            joy=None,
                            sadness=None,
                            loneliness=None,
                            warmth=None,
                            hope=None,
                            tension=None,
                            calm=None,
                        ),
                        scenes=[],
                        themes=[],
                        arrangement=[],
                        semanticDescription=f"{song['title']} 的谨慎画像",
                        confidence=0.3,
                    )
                ]
            )

    class FakeEmbedding:
        embedding_model = "BAAI/bge-m3"
        embedding_dimensions = 1024

        async def embeddings(self, texts):
            return [[0.0] * 1024 for _ in texts]

    class RecordingService(ProfileService):
        def __init__(self):
            super().__init__(None, FlakyModel(), FakeEmbedding())
            self.persisted = []

        async def _persist_batch(self, job_id, songs, profiles, vectors):
            self.persisted.extend(song.source_track_id for song in songs)

    service = RecordingService()
    songs = [
        Song(
            provider="qqmusic",
            source_track_id=f"song-{index}",
            title=f"歌曲 {index}",
            artists=[{"name": "歌手"}],
            album=None,
            duration_ms=None,
        )
        for index in range(2)
    ]
    await service._process_batch_resilient(__import__("uuid").uuid4(), songs, "secret")
    assert service.persisted == ["song-0", "song-1"]


@pytest.mark.asyncio
async def test_single_invalid_song_is_recorded_without_stopping_job() -> None:
    class InvalidModel:
        chat_model = "deepseek-flash"

        async def profile_songs(self, api_key, songs):
            raise InvalidModelResponseError("not json")

    class UnusedEmbedding:
        embedding_model = "BAAI/bge-m3"
        embedding_dimensions = 1024

    class RecordingService(ProfileService):
        def __init__(self):
            super().__init__(None, InvalidModel(), UnusedEmbedding())
            self.skipped = []

        async def _record_song_failure(self, job_id, song, error):
            self.skipped.append((song.source_track_id, error))

    service = RecordingService()
    song = Song(
        provider="qqmusic",
        source_track_id="bad-song",
        title="异常响应歌曲",
        artists=[{"name": "歌手"}],
        album=None,
        duration_ms=None,
    )
    await service._process_batch_resilient(__import__("uuid").uuid4(), [song], "secret")
    assert service.skipped == [("bad-song", "not json")]
