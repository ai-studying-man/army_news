"""Deterministic article classification rules."""

import re
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
    "국방부",
    "군",
    "군사",
    "군부대",
    "부대",
    "장병",
    "민군",
    "민·군",
    "군관",
    "군·관",
    "군인",
)

_REGION_ALCOHOL_TERMS = ("음주", "주취", "만취")

_REGION_DISASTER_TERMS = (
    "재난",
    "재해",
    "산불",
    "화재",
    "호우",
    "폭우",
    "홍수",
    "침수",
    "폭염",
    "한파",
    "태풍",
    "대설",
    "폭설",
    "강풍",
    "지진",
    "산사태",
    "수해",
    "가뭄",
    "물바다",
    "고립",
)

_REGION_MUNICIPAL_TERMS = (
    "지자체",
    "시청",
    "군청",
    "구청",
    "협력",
    "협약",
    "상생",
    "행사",
    "업무",
    "지원",
    "대응",
    "참여",
    "논의",
    "공동",
    "교류",
    "현안",
    "봉사",
    "복구",
    "점검",
    "교육",
    "안전교육",
    "재난",
    "민관",
)

_ARMY_WORK_TERMS = (
    "전력화",
    "전력화사업",
    "훈련",
    "합동훈련",
    "연합훈련",
    "교육훈련",
    "기동훈련",
    "전투훈련",
    "작전",
    "작전사령부",
    "경계작전",
    "장병",
    "장병복지",
    "부대",
    "군부대",
    "대민지원",
    "군사",
    "국방",
    "국방부",
    "방위",
    "방산",
    "무기",
    "무기체계",
    "전차",
    "장갑차",
    "포병",
    "드론",
    "무인",
    "무인체계",
    "정비",
    "군수",
    "동원",
    "예비군",
    "병영",
    "복지",
    "인권",
    "기강",
    "정책",
    "조직",
    "개편",
    "교리",
    "안보",
    "운용",
    "도입",
    "개발",
    "시험",
    "시험평가",
    "양산",
    "현대화",
    "합동",
    "연합",
    "지휘",
    "통신",
    "감시",
    "정찰",
    "사격",
    "기동",
    "경계",
    "시범",
    "재난대응",
    "재난 대응",
    "재해대응",
    "재해 대응",
    "수해복구",
    "산불 대응",
    "화재 진압",
    "안전관리",
    "안전교육",
    "민군",
    "군관",
)

_PERSONAL_NOSTALGIA_CUES = ("배우", "가수", "연예인", "방송인", "아이돌", "탤런트")
_PERSONAL_NOSTALGIA_TERMS = ("복무 시절", "군 시절", "회상", "추억")

_PARTICLE_SUFFIXES = (
    "으로부터",
    "에게서",
    "에서",
    "에게",
    "부터",
    "까지",
    "으로",
    "처럼",
    "보다",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "에",
    "의",
    "와",
    "과",
    "도",
    "로",
    "만",
    "며",
    "고",
)
_PARTICLE_SUFFIX_PATTERN = "(?:" + "|".join(_PARTICLE_SUFFIXES) + ")?"
_REGION_ADMIN_SUFFIXES = (
    "읍사무소",
    "면사무소",
    "동주민센터",
    "시청",
    "군청",
    "구청",
    "지역",
    "시",
    "군",
    "구",
    "읍",
    "면",
    "동",
    "선",
)
_REGION_ADMIN_SUFFIX_PATTERN = "(?:" + "|".join(_REGION_ADMIN_SUFFIXES) + ")?"


class OutputGroup(StrEnum):
    DIVISION = "사단"
    REGION = "지역"


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    group: OutputGroup
    matched_term: str


def _contains_token(context: str, term: str) -> bool:
    """Match a configured term without accepting an alphanumeric compound."""

    normalized_term = term.casefold()
    numeric_prefix = r"(?:제\s*)?" if normalized_term[:1].isdigit() else ""
    pattern = (
        rf"(?<!\w){numeric_prefix}{re.escape(normalized_term)}"
        rf"{_PARTICLE_SUFFIX_PATTERN}(?!\w)"
    )
    return re.search(pattern, context) is not None


def _contains_region(context: str, region: str) -> bool:
    """Match a configured region and its common administrative suffixes."""

    pattern = (
        rf"(?<!\w){re.escape(region.casefold())}{_REGION_ADMIN_SUFFIX_PATTERN}"
        rf"{_PARTICLE_SUFFIX_PATTERN}(?!\w)"
    )
    return re.search(pattern, context) is not None


def _contains_any_token(context: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_token(context, term) for term in terms)


def _contains_any_stem(context: str, terms: tuple[str, ...]) -> bool:
    return any(term.casefold() in context for term in terms)


def _is_personal_nostalgia(context: str) -> bool:
    return _contains_any_stem(context, _PERSONAL_NOSTALGIA_CUES) and _contains_any_stem(
        context, _PERSONAL_NOSTALGIA_TERMS
    )


def _has_army_work_context(context: str) -> bool:
    return _contains_any_token(context, _ARMY_WORK_TERMS)


def _classify_region(context: str, config: BriefConfig) -> ClassificationResult | None:
    region_match: str | None = None
    for rule in config.divisions:
        for region in rule.regions:
            if _contains_region(context, region):
                region_match = region
                break
        if region_match is not None:
            break
    if region_match is None:
        return None

    has_alcohol_incident = _contains_any_stem(context, _REGION_ALCOHOL_TERMS)
    has_natural_hazard = _contains_any_stem(context, _REGION_DISASTER_TERMS)
    has_military_context = _contains_any_token(context, _REGION_CONTEXT_TERMS)
    has_municipal_context = _contains_any_token(context, _REGION_MUNICIPAL_TERMS)
    has_military_municipal_context = has_military_context and has_municipal_context
    if not (has_alcohol_incident or has_natural_hazard or has_military_municipal_context):
        return None
    return ClassificationResult(group=OutputGroup.REGION, matched_term=region_match)


def classify_article(article: Article, config: BriefConfig) -> ClassificationResult | None:
    context = " ".join((article.title, article.description)).casefold()
    if any(term.casefold() in context for term in _FALSE_POSITIVE_TERMS):
        return None
    if any(term.casefold() in context for term in _SENSITIVE_TERMS):
        return None
    if _is_personal_nostalgia(context):
        return None

    general_army_aliases: list[str] = []
    direct_division_alias: str | None = None
    for rule in config.divisions:
        for alias in rule.aliases:
            if alias.casefold() == "육군":
                general_army_aliases.append(alias)
            elif direct_division_alias is None and _contains_token(context, alias):
                direct_division_alias = alias

    # A configured unit alias is a direct monitoring target; only the broad
    # ``육군`` alias needs an additional Army-work relevance cue below.
    if direct_division_alias is not None:
        return ClassificationResult(
            group=OutputGroup.DIVISION,
            matched_term=direct_division_alias,
        )

    region_result = _classify_region(context, config)
    if region_result is not None:
        return region_result

    if (
        general_army_aliases
        and _contains_any_stem(context, tuple(general_army_aliases))
        and _has_army_work_context(context)
    ):
        return ClassificationResult(
            group=OutputGroup.DIVISION,
            matched_term=general_army_aliases[0],
        )
    return None
