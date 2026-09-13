from __future__ import annotations

import re
from collections.abc import Iterable

from .models import SearchIntent

_LANGUAGE_ALIASES = {
    "zh": ("zh", "中文", "华语", "国语", "普通话", "mandarin", "chinese"),
    "yue": ("yue", "粤语", "粤语歌", "cantonese"),
    "en": ("en", "英语", "英文", "english"),
    "ja": ("ja", "日语", "日文", "japanese"),
    "ko": ("ko", "韩语", "韩文", "korean"),
    "es": ("es", "西班牙语", "spanish"),
    "fr": ("fr", "法语", "french"),
    "de": ("de", "德语", "german"),
    "ru": ("ru", "俄语", "russian"),
}

_GENRE_ALIASES = {
    "hard_rock": ("hard rock", "硬摇滚", "重型摇滚"),
    "metal": ("metal", "金属", "重金属"),
    "hip_hop": ("hip hop", "hip-hop", "嘻哈"),
    "rap": ("rap", "说唱"),
    "dance_pop": ("dance pop", "dance-pop", "舞曲流行", "流行舞曲"),
    "edm": ("edm", "electronic dance", "电子舞曲"),
    "electropop": ("electropop", "electro pop", "电子流行"),
    "indie_pop": ("indie pop", "独立流行"),
    "folk_pop": ("folk pop", "民谣流行"),
    "country_pop": ("country pop", "乡村流行"),
    "pop_rock": ("pop rock", "流行摇滚"),
    "punk": ("punk", "朋克"),
    "industrial": ("industrial", "工业"),
    "ballad": ("ballad", "抒情", "情歌"),
    "ambient": ("ambient", "氛围音乐", "氛围"),
    "instrumental": ("instrumental", "纯音乐", "器乐"),
    "soundtrack": ("soundtrack", "原声", "配乐"),
    "classical": ("classical", "古典"),
    "jazz": ("jazz", "爵士"),
    "rnb": ("r&b", "rnb", "节奏布鲁斯"),
    "soul": ("soul", "灵魂乐"),
    "folk": ("folk", "民谣"),
    "country": ("country", "乡村"),
    "rock": ("rock", "摇滚"),
    "pop": ("pop", "流行"),
    "electronic": ("electronic", "电子"),
    "lofi": ("lo-fi", "lofi", "低保真"),
    "chillout": ("chillout", "chill out", "驰放"),
}

_VOCAL_LABELS = {
    "male_solo": "男声独唱",
    "female_solo": "女声独唱",
    "mixed_duet": "男女对唱",
    "male_duet": "双男声对唱",
    "female_duet": "双女声对唱",
    "group": "组合/多人演唱",
    "choir": "合唱团",
    "instrumental": "纯音乐",
    "other": "其他人声",
}


def _compact(value: str) -> str:
    return re.sub(r"[\s_\-/（）()]+", "", value.casefold())


def normalize_language(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.casefold().strip()
    compact = _compact(value)
    for code, aliases in _LANGUAGE_ALIASES.items():
        if raw in aliases or any(_compact(alias) == compact for alias in aliases):
            return code
    return "other"


def normalize_vocal_mode(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.casefold()
    compact = _compact(value)
    if any(token in raw for token in ("instrumental", "no vocal")) or any(
        token in compact for token in ("纯音乐", "器乐", "无人声")
    ):
        return "instrumental"
    if any(
        token in raw
        for token in (
            "male-female",
            "female-male",
            "male and female",
            "female and male",
            "mixed duet",
        )
    ) or any(token in compact for token in ("男女对唱", "男女合唱", "男女混声")):
        return "mixed_duet"
    if any(token in compact for token in ("双男", "男男", "男声对唱")) or "male and male" in raw:
        return "male_duet"
    if any(token in compact for token in ("双女", "女女", "女声对唱", "女声二重唱")) or (
        "female and female" in raw
    ):
        return "female_duet"
    if any(token in raw for token in ("choir", "choral")) or "合唱团" in compact:
        return "choir"
    if any(token in raw for token in ("group", "ensemble")) or any(
        token in compact for token in ("组合", "多人")
    ):
        return "group"
    if "mixed" in raw or "混声" in compact:
        return "other"
    if "duet" in raw or "对唱" in compact or "二重唱" in compact:
        return "other"
    if "female" in raw or any(token in compact for token in ("女声", "女主唱")):
        return "female_solo"
    if "male" in raw or any(token in compact for token in ("男声", "男主唱")):
        return "male_solo"
    return "other"


def normalize_profile_vocal_mode(profile: dict) -> str | None:
    primary = normalize_vocal_mode(profile.get("vocalType"))
    if primary not in {None, "other"}:
        return primary
    arrangement = profile.get("arrangement") or []
    if isinstance(arrangement, list):
        for value in arrangement:
            fallback = normalize_vocal_mode(value)
            if fallback not in {None, "other"}:
                return fallback
    return primary


def normalize_genres(values: Iterable[object]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        raw = value.casefold().strip()
        compact = _compact(value)
        matched = False
        for code, aliases in _GENRE_ALIASES.items():
            if any(alias in raw or _compact(alias) in compact for alias in aliases):
                normalized.add(code)
                matched = True
        if not matched:
            normalized.add(raw)
    return normalized


def vocal_label(mode: str) -> str:
    return _VOCAL_LABELS.get(mode, mode)


def apply_explicit_intent_rules(description: str, intent: SearchIntent) -> SearchIntent:
    """Keep model-inferred hard boundaries tied to words the user actually supplied."""
    compact = _compact(description)
    updates: dict[str, object] = {}

    sadness_terms = ("悲伤", "伤感", "难过", "忧伤", "emo", "丧")
    tension_terms = ("紧张", "刺激", "激烈", "躁", "吵", "重型", "压迫")
    energy_terms = ("能量", "动感", "节奏", "安静", "舒缓", "激烈", "躁", "吵")
    if not any(term in compact for term in sadness_terms):
        updates["maxSadness"] = None
    if not any(term in compact for term in tension_terms):
        updates["maxTension"] = None
    if not any(term in compact for term in energy_terms):
        updates["maxEnergy"] = None

    required = list(intent.requiredVocalModes)
    excluded = list(intent.excludedVocalModes)
    allowed_languages = list(intent.allowedLanguages)
    excluded_languages = list(intent.excludedLanguages)
    instrumental_allowed = intent.instrumentalAllowed
    if "男女对唱" in compact or "男女合唱" in compact:
        required = ["mixed_duet"]
        instrumental_allowed = False
    if "不要独唱" in compact or "非独唱" in compact:
        excluded = list(dict.fromkeys([*excluded, "male_solo", "female_solo"]))
    if any(term in compact for term in ("不要纯音乐", "不要器乐", "必须有人声")):
        instrumental_allowed = False
        excluded = list(dict.fromkeys([*excluded, "instrumental"]))
    if any(term in compact for term in ("只要纯音乐", "纯音乐为主", "无人声")):
        required = ["instrumental"]
        instrumental_allowed = True
    if "男声独唱" in compact:
        required = ["male_solo"]
    if "女声独唱" in compact:
        required = ["female_solo"]
    if "双男声" in compact or "男男对唱" in compact:
        required = ["male_duet"]
    if "双女声" in compact or "女女对唱" in compact:
        required = ["female_duet"]

    language_terms = {
        "yue": ("粤语",),
        "zh": ("中文歌", "华语歌", "国语歌", "普通话歌"),
        "en": ("英文歌", "英语歌"),
        "ja": ("日文歌", "日语歌"),
        "ko": ("韩文歌", "韩语歌"),
    }
    for code, terms in language_terms.items():
        for term in terms:
            if f"不要{term}" in compact or f"排除{term}" in compact:
                excluded_languages = list(dict.fromkeys([*excluded_languages, code]))
            elif term in compact:
                allowed_languages = list(dict.fromkeys([*allowed_languages, code]))

    if any(term in compact for term in ("别太吵", "不要太吵", "别太躁", "不要太躁")):
        updates["maxEnergy"] = intent.maxEnergy if intent.maxEnergy is not None else 0.68
        updates["maxTension"] = intent.maxTension if intent.maxTension is not None else 0.45

    updates.update(
        requiredVocalModes=required,
        excludedVocalModes=excluded,
        allowedLanguages=allowed_languages,
        excludedLanguages=excluded_languages,
        instrumentalAllowed=instrumental_allowed,
    )
    return intent.model_copy(update=updates)
