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
    result = classify_article(article("양주시 비룡부대 수해복구 대민지원"), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.DIVISION
    assert result.matched_term == "비룡부대"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("125사단 장병 훈련", None),
        ("비룡부대찌개 신메뉴 출시", None),
        ("25사단 장병 훈련", OutputGroup.DIVISION),
        ("제25보병사단 장병 훈련", OutputGroup.DIVISION),
        ("비룡부대와 대민지원", OutputGroup.DIVISION),
    ],
)
def test_division_alias_matching_is_token_safe(title: str, expected: OutputGroup | None) -> None:
    result = classify_article(article(title), BriefConfig.default())

    assert result is None if expected is None else result is not None and result.group is expected


def test_direct_configured_unit_alias_is_strong_evidence() -> None:
    result = classify_article(article("비룡부대 단순 소개"), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.DIVISION
    assert result.matched_term == "비룡부대"


def test_general_army_alias_classifies_content_as_division() -> None:
    result = classify_article(article("육군, AI 기반 드론 전력화 추진"), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.ARMY
    assert result.matched_term == "육군"


def test_general_army_alias_matches_relevant_embedded_title_form() -> None:
    result = classify_article(
        article("춘천코리아오픈국제태권도대회 육군태권도시범단 격파 시범"),
        BriefConfig.default(),
    )

    assert result is not None
    assert result.group is OutputGroup.ARMY
    assert result.matched_term == "육군"


@pytest.mark.parametrize(
    "title",
    [
        "육군 전력화 추진",
        "육군 합동훈련 실시",
        "육군 작전 수행",
        "육군 장병 복지",
        "육군 부대 점검",
        "육군 대민지원 실시",
    ],
)
def test_general_army_alias_requires_army_work_context(title: str) -> None:
    result = classify_article(article(title), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.ARMY
    assert result.matched_term == "육군"


def test_personal_army_nostalgia_is_not_division_news() -> None:
    assert (
        classify_article(article("배우가 육군 복무 시절을 회상했다"), BriefConfig.default()) is None
    )


def test_foreign_army_youth_committee_translation_is_not_korean_army_news() -> None:
    title = (
        "육군청년위원회는 캄보디아 교환 프로그램에 참가할 젊은 장교 대표단을 "
        "준비시키기 위한 훈련을 제공하고 있습니다."
    )

    assert classify_article(article(title), BriefConfig.default()) is None


def test_general_army_alias_does_not_override_region_context() -> None:
    result = classify_article(
        article("연천 산불 재난 대응", "육군 장병이 주민 안전을 지원했다"), BriefConfig.default()
    )

    assert result is not None
    assert result.group is OutputGroup.REGION
    assert result.matched_term == "연천"


def test_feed_label_division_alias_does_not_override_region_flood_content() -> None:
    result = classify_article(
        article(
            "파주 집중호우 피해",
            "도로 침수와 주민 대피",
            "Google 뉴스: 제8기동사단 지역",
        ),
        BriefConfig.default(),
    )

    assert result is not None
    assert result.group is OutputGroup.REGION
    assert result.matched_term == "파주"


def test_feed_label_division_alias_does_not_include_unrelated_region_education() -> None:
    result = classify_article(
        article(
            "파주도시교육재단 평생학습 프로그램",
            "시민 교육 수강생 모집",
            "Google 뉴스: 제8기동사단 지역",
        ),
        BriefConfig.default(),
    )

    assert result is None


@pytest.mark.parametrize(
    ("title", "description", "source_name"),
    [
        ("양주시 집중호우 피해", "육군 장병이 수해복구 대민지원에 나섰다", "지역일보"),
        ("파주 산불 재난 대응", "소방과 지자체가 주민 안전을 점검했다", "안전신문"),
        ("연천군 민군 상생 행사 개최", "지자체와 군 관계자가 참석했다", "군청 보도자료"),
    ],
)
def test_region_needs_configured_place_and_allowed_context(
    title: str, description: str, source_name: str
) -> None:
    result = classify_article(article(title, description, source_name), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.REGION


def test_context_is_evaluated_across_title_and_description() -> None:
    config = BriefConfig(divisions=(DivisionRule("별빛사단", ("별빛부대",), ("춘천",)),))

    result = classify_article(article("춘천시 협력 행사", "육군과 지역 현안을 논의했다"), config)

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
        "25사단 병력 이동 경로 공개",
        "비룡부대 세부 주둔 위치 추정",
        "제25보병사단 병력 규모와 장비 배치 현황",
        "1군단 향후 전개 계획 분석",
    ],
)
def test_sensitive_location_movement_and_deployment_content_is_rejected(title: str) -> None:
    assert classify_article(article(title), BriefConfig.default()) is None


def test_region_without_army_safety_disaster_or_civil_military_context_is_rejected() -> None:
    assert classify_article(article("연천군 여름 축제 개막"), BriefConfig.default()) is None


@pytest.mark.parametrize(
    "title",
    [
        "또 물바다 된 고양시 화전동…양주선 옹벽 무너져",
        "파주지역 18일 시간당 44.0mm 물폭탄 이어 산사태 주의보",
    ],
)
def test_region_matches_natural_forms_with_live_disaster_cues(title: str) -> None:
    result = classify_article(article(title), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.REGION


def test_natural_region_form_does_not_admit_ordinary_education_news() -> None:
    assert (
        classify_article(
            article("파주지역 초등학생 교육 프로그램 참가자 모집"),
            BriefConfig.default(),
        )
        is None
    )


@pytest.mark.parametrize(
    "title",
    [
        "北, DMZ 인근에 방사포 시설 건설한 정황",
        "평양서 왕후닝 만난 김정은, 북중 관계 발전 강조",
        "北과 군사 밀착하는 러시아, 한국·나토 협력 비판",
        "한미일 협력에 북중러로 맞서나",
        "韓 기업 차별 보고, 美 국방수권법서 제동",
        "美, 상선 공격 중단 요구 무시한 이란에 또 공습…호르무즈 긴장",
        "K방산 최대시장 수출 날개…핵심광물 공급망 확대",
    ],
)
def test_diplomacy_and_north_korea_articles_are_classified(title: str) -> None:
    result = classify_article(article(title), BriefConfig.default())

    assert result is not None
    expected_group = (
        OutputGroup.DEFENSE_SECURITY
        if title.casefold().startswith("k방산")
        else OutputGroup.DIPLOMACY_NORTH_KOREA
    )
    assert result.group is expected_group


@pytest.mark.parametrize(
    "title",
    [
        "북한산 등산로 정비 완료",
        "평양냉면 여름 신메뉴 출시",
        "미국 기업 일반 소비재 수출 증가",
    ],
)
def test_diplomacy_group_rejects_homonyms_and_unrelated_trade(title: str) -> None:
    assert classify_article(article(title), BriefConfig.default()) is None


@pytest.mark.parametrize(
    "title",
    [
        "양주시 교통사고로 도로 정체",
        "파주 시민 안전교육 행사",
    ],
)
def test_region_requires_allowed_subject_or_military_municipal_context(title: str) -> None:
    assert classify_article(article(title), BriefConfig.default()) is None


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("양주시 군부대 협력 업무", "지자체와 부대가 공동 대응했다"),
        ("파주 국방 협약 행사", "장병과 시청 관계자가 참여했다"),
        ("연천 부대 지원 사업", "군과 지자체가 현안을 논의했다"),
        ("연천 장병 봉사 활동", "지역 주민과 군이 교류했다"),
    ],
)
def test_region_keeps_military_municipal_work_and_events(title: str, description: str) -> None:
    result = classify_article(article(title, description), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.REGION


def test_source_labels_are_not_classification_evidence() -> None:
    result = classify_article(
        article("일반 시민 행사", source_name="육군 8사단 지역 뉴스"), BriefConfig.default()
    )

    assert result is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("제1군단, 공개 훈련 실시", OutputGroup.CORPS),
        ("제25보병사단 장병 안전교육", OutputGroup.DIVISION),
        ("파주 집중호우 피해", OutputGroup.REGION),
        ("육군 드론 전력화 추진", OutputGroup.ARMY),
        ("국방부 안보정책 발표", OutputGroup.DEFENSE_SECURITY),
        ("북한 방사포 시설 건설 정황", OutputGroup.DIPLOMACY_NORTH_KOREA),
        ("[사설] 국방개혁 방향", OutputGroup.COLUMN_EDITORIAL),
    ],
)
def test_requested_monitoring_groups_are_classified(title: str, expected: OutputGroup) -> None:
    result = classify_article(article(title), BriefConfig.default())

    assert result is not None
    assert result.group is expected


def test_column_marker_takes_priority_over_subject_group() -> None:
    result = classify_article(article("[사설] 육군 전력화의 방향"), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.COLUMN_EDITORIAL


def test_kim_jong_un_homonym_is_not_north_korea_news() -> None:
    title = "세종사이버대 아동학과 김정은 겸임교수 생방송 출연"

    assert classify_article(article(title), BriefConfig.default()) is None


def test_defense_industry_precedes_broad_diplomacy_search_terms() -> None:
    result = classify_article(article("K방산 유럽 수출 확대"), BriefConfig.default())

    assert result is not None
    assert result.group is OutputGroup.DEFENSE_SECURITY


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


def test_custom_config_scopes_unit_aliases_to_active_rules() -> None:
    config = BriefConfig(
        divisions=(
            DivisionRule(
                "교체사단",
                ("육군", "7군단", "77사단", "교체부대"),
                ("춘천",),
            ),
        )
    )

    assert classify_article(article("1군단 공개 훈련"), config) is None
    assert classify_article(article("25사단 장병 안전교육"), config) is None

    result = classify_article(article("교체부대 장병 안전교육"), config)

    assert result is not None
    assert result.group is OutputGroup.DIVISION
    assert result.matched_term == "교체부대"


def test_custom_config_classifies_corps_and_division_aliases_from_active_rule() -> None:
    config = BriefConfig(
        divisions=(
            DivisionRule(
                "제99보병사단",
                ("육군", "9군단", "99사단", "백호부대"),
                ("춘천",),
            ),
        )
    )

    assert classify_article(article("1군단 공개 훈련"), config) is None
    assert classify_article(article("25사단 장병 안전교육"), config) is None

    corps_result = classify_article(article("9군단 공개 훈련"), config)
    assert corps_result is not None
    assert corps_result.group is OutputGroup.CORPS
    assert corps_result.matched_term == "9군단"

    division_result = classify_article(article("99사단 장병 안전교육"), config)
    assert division_result is not None
    assert division_result.group is OutputGroup.DIVISION
    assert division_result.matched_term == "99사단"
