"""Deterministic article classification rules."""

from dataclasses import dataclass
from enum import StrEnum

from army_morning_brief.config import BriefConfig
from army_morning_brief.models import Article

_FALSE_POSITIVE_TERMS = (
    "농업용 드론",
    "김 군",
    "민간 물류",
    "물류기업 드론",
    "드론 배송 서비스",
    "전직 육군참모총장",
    "후보자",
    "인사청문회",
    "관련주",
    "주가",
)

_SENSITIVE_TERMS = (
    "세부 위치",
    "주둔 위치",
    "부대 위치",
    "병력 이동",
    "이동 경로",
    "병력 규모",
    "병력 배치",
    "장비 배치",
    "전력 배치",
    "배치 현황",
    "전개 계획",
    "작전 계획",
)

_REGION_CONTEXT_TERMS = (
    "육군",
    "국방",
    "군부대",
    "장병",
    "사단",
    "대민지원",
    "민군",
    "안전",
    "사고",
    "음주",
    "재난",
    "재해",
    "산불",
    "호우",
    "폭우",
    "폭염",
    "태풍",
    "대설",
    "수해",
    "소방",
)


class OutputGroup(StrEnum):
    DIVISION = "사단"
    REGION = "지역"


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    group: OutputGroup
    matched_term: str


def classify_article(article: Article, config: BriefConfig) -> ClassificationResult | None:
    context = " ".join((article.title, article.description, article.source.name)).casefold()
    if any(term.casefold() in context for term in _FALSE_POSITIVE_TERMS):
        return None
    if any(term.casefold() in context for term in _SENSITIVE_TERMS):
        return None

    for rule in config.divisions:
        for alias in rule.aliases:
            if alias.casefold() in context:
                return ClassificationResult(group=OutputGroup.DIVISION, matched_term=alias)

    if not any(term.casefold() in context for term in _REGION_CONTEXT_TERMS):
        return None
    for rule in config.divisions:
        for region in rule.regions:
            if region.casefold() in context:
                return ClassificationResult(group=OutputGroup.REGION, matched_term=region)
    return None
