from datetime import datetime, timedelta, timezone

import pytest

from army_morning_brief.classification import OutputGroup, classify_article
from army_morning_brief.config import BriefConfig, DivisionRule
from army_morning_brief.models import Article, Source

KST = timezone(timedelta(hours=9))


def article(title: str, description: str = "", source_name: str = "공개 뉴스") -> Article:
    return Article(
        title=title,
        description=description,
        url="https://news.example/article",
        published_at=datetime(2026, 7, 18, 6, 0, tzinfo=KST),
        source=Source(name=source_name, url="https://news.example/feed"),
    )


def test_direct_division_alias_is_classified_with_highest_rank() -> None:
    result = classify_article(
        article("양주시 오뚜기부대 수해복구 대민지원"), BriefConfig.default()
    )

    assert result is not None
    assert result.group is OutputGroup.DIVISION
    assert result.matched_term == "오뚜기부대"


@pytest.mark.parametrize(
    ("title", "description", "source_name"),
    [
        ("양주시 집중호우 피해", "육군 장병이 수해복구 대민지원에 나섰다", "지역일보"),
        ("동두천 산불 재난 대응", "소방과 지자체가 주민 안전을 점검했다", "안전신문"),
        ("포천시 민군 상생 행사 개최", "지자체와 군 관계자가 참석했다", "시청 보도자료"),
    ],
)
def test_region_needs_configured_place_and_allowed_context(
    title: str, description: str, source_name: str
) -> None:
    result = classify_article(article(title, description, source_name), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.REGION


def test_context_is_evaluated_across_title_description_and_source() -> None:
    config = BriefConfig(
        divisions=(DivisionRule("별빛사단", ("별빛부대",), ("춘천",)),)
    )

    result = classify_article(
        article("춘천시 협력 행사", "지역 현안을 논의했다", "육군 공식 보도자료"), config
    )

    assert result is not None
    assert result.group is OutputGroup.REGION


@pytest.mark.parametrize(
    "title",
    [
        "진천군, 농업용 드론 방제 확대",
        "김 군, AI 드론 대회 우승",
        "민간 물류기업 드론 배송 서비스 출시",
        "전직 육군참모총장, 정치 행사 참석",
        "육군참모총장 후보자 인사청문회 전망",
        "방산 관련주 하반기 주가 반등 기대",
    ],
)
def test_required_false_positives_are_rejected(title: str) -> None:
    assert classify_article(article(title), BriefConfig.default()) is None


@pytest.mark.parametrize(
    "title",
    [
        "8사단 병력 이동 경로 공개",
        "오뚜기부대 세부 주둔 위치 추정",
        "3070부대 병력 규모와 장비 배치 현황",
        "8기동사단 향후 전개 계획 분석",
    ],
)
def test_sensitive_location_movement_and_deployment_content_is_rejected(title: str) -> None:
    assert classify_article(article(title), BriefConfig.default()) is None


def test_region_without_army_safety_disaster_or_civil_military_context_is_rejected() -> None:
    assert classify_article(article("포천시 여름 축제 개막"), BriefConfig.default()) is None


def test_custom_rules_keep_different_divisions_and_regions_representable() -> None:
    config = BriefConfig(
        divisions=(
            DivisionRule("별빛사단", ("별빛부대",), ("춘천",)),
            DivisionRule("해오름사단", ("해오름부대",), ("강릉",)),
        )
    )

    division_result = classify_article(article("해오름부대 장병 안전교육"), config)
    region_result = classify_article(article("춘천 산불 재난 대응"), config)

    assert division_result is not None and division_result.matched_term == "해오름부대"
    assert region_result is not None and region_result.matched_term == "춘천"
