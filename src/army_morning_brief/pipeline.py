"""Deterministic classification, event deduplication, and article selection."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
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


def _ngrams(article: Article, size: int = 3) -> set[str]:
    compact = "".join(_WORD_PATTERN.findall(_text(article)))
    if len(compact) <= size:
        return {compact} if compact else set()
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


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

    for alternatives in _STATE_DIMENSIONS:
        left_state = _exclusive_state(left_text, alternatives)
        right_state = _exclusive_state(right_text, alternatives)
        if left_state is not None and right_state is not None and left_state != right_state:
            return True

    left_training_state = 1 if any(term in left_text for term in ("사고", "부상", "사망")) else 0
    right_training_state = 1 if any(term in right_text for term in ("사고", "부상", "사망")) else 0
    if left_training_state != right_training_state and (
        "훈련" in left_text and "훈련" in right_text
    ):
        return True

    left_numbers = set(_NUMBER_PATTERN.findall(left_text))
    right_numbers = set(_NUMBER_PATTERN.findall(right_text))
    return bool(left_numbers and right_numbers and left_numbers.isdisjoint(right_numbers))


def _same_event(left: Article, right: Article, config: BriefConfig) -> bool:
    if _canonical_url(left.url) == _canonical_url(right.url):
        return True
    if _has_distinct_dimensions(left, right, config):
        return False
    word_overlap = _overlap(_terms(left), _terms(right))
    ngram_overlap = _overlap(_ngrams(left), _ngrams(right))
    return word_overlap >= 0.72 or ngram_overlap >= 0.76


def _published_timestamp(value: datetime) -> float:
    return value.timestamp()


def _ranking_key(selected: SelectedArticle) -> tuple[object, ...]:
    article = selected.article
    return (
        0 if selected.classification.group is OutputGroup.DIVISION else 1,
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
    per_group_limit: int = 5,
) -> dict[OutputGroup, tuple[SelectedArticle, ...]]:
    """Classify, deduplicate, rank, and cap collected articles."""
    if per_group_limit < 1:
        raise ValueError("per_group_limit must be positive")

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
