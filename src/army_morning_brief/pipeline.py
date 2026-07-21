"""Deterministic classification, event deduplication, and article selection."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from army_morning_brief.classification import (
    ClassificationResult,
    OutputGroup,
    classify_article,
)
from army_morning_brief.config import BriefConfig
from army_morning_brief.models import Article


@dataclass(frozen=True, slots=True)
class SelectedArticle:
    article: Article
    classification: ClassificationResult


_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "ref", "source"}
_COUNTRIES = (
    "대한민국",
    "한국",
    "미국",
    "일본",
    "중국",
    "폴란드",
    "루마니아",
    "호주",
    "인도",
    "이집트",
    "사우디",
    "우크라이나",
    "러시아",
)
_STATE_DIMENSIONS = (
    (("취소", "해지", "중단", "철회"), ("체결", "서명", "수주")),
    (("양산", "전력화", "배치"), ("시험", "평가", "실증")),
)
_WORD_PATTERN = re.compile(r"[0-9a-zA-Z가-힣]+")
_NUMBER_PATTERN = re.compile(r"\d+")
_DIVISION_NUMBER_PATTERN = re.compile(r"(?:제\s*)?(\d+)\s*(?:보병|기동)?사단")
_VOLATILE_COUNT_TERMS = (
    "고립",
    "대피",
    "피해",
    "사망",
    "부상",
    "실종",
    "캠핑객",
)
MAX_ARTICLES_PER_GROUP = 5
_INCIDENT_CONCEPTS = (
    ("경보", "주의보"),
    ("홍수", "범람"),
    ("호우", "폭우", "집중호우"),
    ("침수", "물바다"),
    ("산불", "화재"),
    ("지진",),
    ("태풍",),
    ("폭설", "대설"),
    ("붕괴",),
    ("대피", "피난"),
)
_PLACE_SUFFIXES = ("강", "교", "댐", "천", "산", "시", "구", "읍", "면", "동")
_NON_PLACE_TERMS = frozenset({"육군", "미군", "한국군", "국방부", "군부대"})
_INCIDENT_REWRITE_THRESHOLD = 0.3
_EVENT_BOILERPLATE_TERMS = frozenset(
    {
        "관련",
        "소식",
        "기사",
        "보도",
        "내용",
        "공개",
        "장병",
        "부대",
        "사단",
        "육군",
        "군",
        "군인",
        "대상",
        "행사",
        "실시",
        "진행",
        "개최",
        "참석",
        "참여",
        "발표",
        "전해",
        "밝혀",
        "알려",
        "추진",
        "마련",
        "예정",
        "계획",
        "위해",
        "통해",
        "따라",
        "대해",
    }
)
_KOREAN_PARTICLE_SUFFIXES = (
    "으로",
    "에서",
    "에게",
    "부터",
    "까지",
    "을",
    "를",
    "은",
    "는",
    "이",
    "가",
    "에",
    "의",
)
_KOREAN_SENTENCE_SUFFIXES = (
    "했다",
    "한다",
    "하며",
    "하고",
    "하여",
    "되는",
    "됐다",
    "된",
    "한",
    "할",
    "하는",
    "함",
)


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_QUERY_KEYS
        )
    )
    return urlunsplit(("https", parsed.netloc.casefold(), path, query, ""))


def _text(article: Article) -> str:
    return f"{article.title} {article.description}".casefold()


def _terms(article: Article) -> set[str]:
    return set(_WORD_PATTERN.findall(_text(article)))


def _normalize_term(term: str) -> str:
    normalized = term.casefold()
    for suffix in _KOREAN_SENTENCE_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            normalized = normalized[: -len(suffix)]
            break
    for suffix in _KOREAN_PARTICLE_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def _is_entity_term(term: str, config: BriefConfig) -> bool:
    entity_values = (*_COUNTRIES, *(alias for rule in config.divisions for alias in rule.aliases))
    entity_values += tuple(region for rule in config.divisions for region in rule.regions)
    return any(value.casefold() in term for value in entity_values)


def _meaningful_terms(article: Article, config: BriefConfig) -> set[str]:
    """Return subject/event anchors, excluding shared entities and news boilerplate."""
    meaningful: set[str] = set()
    for term in _terms(article):
        normalized = _normalize_term(term)
        if (
            not normalized
            or normalized.isdigit()
            or normalized in _EVENT_BOILERPLATE_TERMS
            or _is_entity_term(normalized, config)
        ):
            continue
        meaningful.add(normalized)
    return meaningful


def _ngrams(article: Article, size: int = 3) -> set[str]:
    compact = "".join(_WORD_PATTERN.findall(_text(article)))
    if len(compact) <= size:
        return {compact} if compact else set()
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def _place_roots(article: Article) -> set[str]:
    roots: set[str] = set()
    for term in _terms(article):
        normalized = _normalize_term(term)
        if normalized in _NON_PLACE_TERMS:
            continue
        for suffix in _PLACE_SUFFIXES:
            if normalized.endswith(suffix) and len(normalized) >= len(suffix) + 2:
                roots.add(normalized[: -len(suffix)])
                break
    return roots


def _compact_title(article: Article) -> str:
    return "".join(_WORD_PATTERN.findall(article.title.casefold()))


def _incident_rewrite_similarity(left: Article, right: Article) -> float:
    left_title = _compact_title(left)
    right_title = _compact_title(right)
    if not left_title or not right_title:
        return 0.0
    left_text = "".join(_WORD_PATTERN.findall(_text(left)))
    right_text = "".join(_WORD_PATTERN.findall(_text(right)))
    shared_concepts = sum(
        any(keyword in left_text for keyword in concept)
        and any(keyword in right_text for keyword in concept)
        for concept in _INCIDENT_CONCEPTS
    )
    if shared_concepts < 2:
        return 0.0
    return SequenceMatcher(None, left_title, right_title, autojunk=False).ratio()


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _exclusive_state(text: str, alternatives: tuple[tuple[str, ...], ...]) -> int | None:
    for index, terms in enumerate(alternatives):
        if any(term in text for term in terms):
            return index
    return None


def _has_distinct_dimensions(left: Article, right: Article, config: BriefConfig) -> bool:
    left_text = _text(left)
    right_text = _text(right)
    dimensions = (
        _COUNTRIES,
        tuple(region for rule in config.divisions for region in rule.regions),
    )
    for values in dimensions:
        left_values = {value for value in values if value.casefold() in left_text}
        right_values = {value for value in values if value.casefold() in right_text}
        if left_values and right_values and left_values.isdisjoint(right_values):
            return True

    left_places = _place_roots(left)
    right_places = _place_roots(right)
    if left_places and right_places and left_places.isdisjoint(right_places):
        return True

    for alternatives in _STATE_DIMENSIONS:
        left_state = _exclusive_state(left_text, alternatives)
        right_state = _exclusive_state(right_text, alternatives)
        if left_state is not None and right_state is not None and left_state != right_state:
            return True

    left_divisions = set(_DIVISION_NUMBER_PATTERN.findall(left_text))
    right_divisions = set(_DIVISION_NUMBER_PATTERN.findall(right_text))
    if left_divisions and right_divisions and left_divisions.isdisjoint(right_divisions):
        return True

    left_training_state = 1 if any(term in left_text for term in ("사고", "부상", "사망")) else 0
    right_training_state = 1 if any(term in right_text for term in ("사고", "부상", "사망")) else 0
    if left_training_state != right_training_state and (
        "훈련" in left_text and "훈련" in right_text
    ):
        return True

    left_numbers = set(_NUMBER_PATTERN.findall(left_text))
    right_numbers = set(_NUMBER_PATTERN.findall(right_text))
    if any(term in left_text or term in right_text for term in _VOLATILE_COUNT_TERMS):
        return False
    return bool(left_numbers and right_numbers and left_numbers.isdisjoint(right_numbers))


def _same_event(left: Article, right: Article, config: BriefConfig) -> bool:
    if _canonical_url(left.url) == _canonical_url(right.url):
        return True
    if _has_distinct_dimensions(left, right, config):
        return False
    left_anchors = _meaningful_terms(left, config)
    right_anchors = _meaningful_terms(right, config)
    shared_anchors = left_anchors & right_anchors
    if not shared_anchors:
        return _incident_rewrite_similarity(left, right) >= _INCIDENT_REWRITE_THRESHOLD
    if _incident_rewrite_similarity(left, right) >= _INCIDENT_REWRITE_THRESHOLD:
        return True
    if len(shared_anchors) >= 3:
        return True
    if len(shared_anchors) >= 2 and all(
        any(term in text for term in _VOLATILE_COUNT_TERMS) for text in (_text(left), _text(right))
    ):
        return True
    word_overlap = _overlap(_terms(left), _terms(right))
    ngram_overlap = _overlap(_ngrams(left), _ngrams(right))
    return word_overlap >= 0.72 or ngram_overlap >= 0.76


def _published_timestamp(value: datetime) -> float:
    return value.timestamp()


def _ranking_key(selected: SelectedArticle) -> tuple[object, ...]:
    article = selected.article
    group_rank = {
        OutputGroup.ARMY: 0,
        OutputGroup.CORPS: 1,
        OutputGroup.DIVISION: 2,
        OutputGroup.REGION: 3,
        OutputGroup.DEFENSE_SECURITY: 4,
        OutputGroup.DIPLOMACY_NORTH_KOREA: 5,
        OutputGroup.COLUMN_EDITORIAL: 6,
    }
    return (
        group_rank[selected.classification.group],
        -article.source.priority,
        -(article.view_count if article.view_count is not None else -1),
        article.feed_rank,
        -_published_timestamp(article.published_at),
        _canonical_url(article.url),
        article.title.casefold(),
        article.source.name.casefold(),
    )


def select_articles(
    articles: Iterable[Article],
    config: BriefConfig,
    *,
    per_group_limit: int = MAX_ARTICLES_PER_GROUP,
) -> dict[OutputGroup, tuple[SelectedArticle, ...]]:
    """Classify, deduplicate, rank, and cap collected articles."""
    if not 1 <= per_group_limit <= MAX_ARTICLES_PER_GROUP:
        raise ValueError(f"per_group_limit must be between 1 and {MAX_ARTICLES_PER_GROUP}")

    classified = [
        SelectedArticle(article, result)
        for article in articles
        if (result := classify_article(article, config)) is not None
    ]
    classified.sort(key=_ranking_key)

    representatives: list[SelectedArticle] = []
    for candidate in classified:
        duplicate_index = next(
            (
                index
                for index, representative in enumerate(representatives)
                if _same_event(candidate.article, representative.article, config)
            ),
            None,
        )
        if duplicate_index is None:
            representatives.append(candidate)
        elif _ranking_key(candidate) < _ranking_key(representatives[duplicate_index]):
            representatives[duplicate_index] = candidate

    result_groups: dict[OutputGroup, tuple[SelectedArticle, ...]] = {}
    for group in OutputGroup:
        group_items = sorted(
            (item for item in representatives if item.classification.group is group),
            key=_ranking_key,
        )
        result_groups[group] = tuple(group_items[:per_group_limit])
    return result_groups
