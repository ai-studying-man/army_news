from datetime import datetime, timedelta, timezone

import pytest

from army_morning_brief.classification import OutputGroup
from army_morning_brief.config import BriefConfig, DivisionRule
from army_morning_brief.models import Article, Source
from army_morning_brief.pipeline import select_articles

KST = timezone(timedelta(hours=9))
CONFIG = BriefConfig(
    divisions=(
        DivisionRule(
            "legacy test unit",
            ("육군", "8사단", "8기동사단", "3070부대", "오뚜기부대"),
            ("양주", "동두천", "포천", "연천", "의정부"),
        ),
    )
)


def article(
    title: str,
    *,
    description: str = "",
    url: str,
    source: str = "지역일보",
    priority: int = 0,
    views: int | None = None,
    rank: int = 0,
    hour: int = 6,
) -> Article:
    return Article(
        title=title,
        description=description,
        url=url,
        published_at=datetime(2026, 7, 18, hour, tzinfo=KST),
        source=Source(name=source, url=f"https://feeds.example/{source}", priority=priority),
        feed_rank=rank,
        view_count=views,
    )


def test_pipeline_pins_existing_division_region_and_rejection_classification() -> None:
    items = (
        article("오뚜기부대 장병 안전교육", url="https://news.example/division"),
        article("포천 산불 재난 대응", url="https://news.example/region"),
        article("포천 여름 축제 개막", url="https://news.example/rejected"),
    )

    selected = select_articles(items, CONFIG)

    assert [item.article.url for item in selected[OutputGroup.DIVISION]] == [
        "https://news.example/division"
    ]
    assert [item.article.url for item in selected[OutputGroup.REGION]] == [
        "https://news.example/region"
    ]


def test_pipeline_includes_diplomacy_north_korea_group() -> None:
    item = article(
        "평양서 열린 북중 정상회담",
        url="https://news.example/diplomacy",
    )

    selected = select_articles((item,), CONFIG)

    assert [entry.article.url for entry in selected[OutputGroup.DIPLOMACY_NORTH_KOREA]] == [
        "https://news.example/diplomacy"
    ]


def test_global_dedup_uses_canonical_url_and_best_representative() -> None:
    less_preferred = article(
        "포천 산불 현장에 육군 장병 투입",
        description="포천 산불 현장에 육군 장병이 투입됐다.",
        url="https://NEWS.example/story/?utm_source=rss#top",
        source="통신사",
        priority=1,
        views=999,
    )
    official_direct = article(
        "8사단, 포천 산불 현장 장병 투입",
        description="포천 산불 현장에 육군 장병이 투입됐다.",
        url="https://news.example/story",
        source="육군 공식",
        priority=10,
        views=1,
    )

    selected = select_articles((less_preferred, official_direct), CONFIG)

    assert sum(map(len, selected.values())) == 1
    assert selected[OutputGroup.DIVISION][0].article is official_direct


def test_event_dedup_collapses_different_outlets_and_ranks_all_fields() -> None:
    candidates = (
        article(
            "양주 집중호우 피해 복구 장병 대민지원",
            description="양주시 집중호우 피해 복구를 위해 장병들이 대민지원에 나섰다.",
            url="https://one.example/a",
            source="낮은우선순위",
            priority=1,
            views=20,
            rank=2,
            hour=7,
        ),
        article(
            "양주시 집중호우 피해복구에 장병 대민지원",
            description="양주시 집중호우 피해 복구를 위해 장병들이 대민지원에 나섰다.",
            url="https://two.example/b",
            source="높은우선순위",
            priority=3,
            views=20,
            rank=2,
            hour=7,
        ),
    )

    selected = select_articles(candidates, CONFIG)

    assert [item.article.source.name for item in selected[OutputGroup.REGION]] == ["높은우선순위"]


def test_event_dedup_keeps_distinct_ordinary_army_events() -> None:
    candidates = (
        article(
            "8사단 장병 안전교육 실시",
            description="8사단 육군 관련 소식: 장병 공개 행사를 실시했다.",
            url="https://one.example/safety-training",
        ),
        article(
            "8사단 장병 전투훈련 실시",
            description="8사단 육군 관련 소식: 장병 공개 행사를 실시했다.",
            url="https://two.example/combat-training",
        ),
    )

    selected = select_articles(candidates, CONFIG)

    assert sum(map(len, selected.values())) == 2
    assert {item.article.url for group_items in selected.values() for item in group_items} == {
        "https://one.example/safety-training",
        "https://two.example/combat-training",
    }


def test_event_dedup_collapses_near_duplicate_rewrite_to_best_representative() -> None:
    less_preferred = article(
        "8사단 장병 안전교육 실시",
        description="8사단 장병 안전교육을 진행했다.",
        url="https://one.example/safety-training",
        priority=1,
    )
    preferred_rewrite = article(
        "8사단, 장병 대상 안전교육 진행",
        description="장병 대상 안전교육을 진행했다.",
        url="https://two.example/safety-training-rewrite",
        priority=10,
    )

    selected = select_articles((less_preferred, preferred_rewrite), CONFIG)

    assert sum(map(len, selected.values())) == 1
    assert selected[OutputGroup.DIVISION][0].article is preferred_rewrite


def test_live_style_training_and_flood_rewrites_collapse_but_different_unit_remains() -> None:
    items = (
        article(
            "육군 제6보병사단, 20~23일 철원·포천서 전투지휘검열 훈련 실시",
            url="https://one.example/6div-training",
            priority=10,
        ),
        article(
            "육군 3사단, 철원 일대서 전투지휘검열 훈련",
            url="https://two.example/3div-training",
        ),
        article(
            "육군 제6보병사단, 철원~포천 일대서 23일까지 전투 지휘검열 훈련",
            url="https://three.example/6div-training-rewrite",
        ),
        article(
            "포천 하천 범람으로 캠핑객 97명 고립…산길 우회로로 전원 대피",
            url="https://four.example/flood",
            priority=10,
        ),
        article(
            "집중호우에 옹벽 붕괴 포천 캠핑객 95명 고립",
            url="https://five.example/flood-update",
        ),
    )

    selected = select_articles(items, CONFIG)
    selected_urls = {item.article.url for group_items in selected.values() for item in group_items}

    assert selected_urls == {
        "https://one.example/6div-training",
        "https://two.example/3div-training",
        "https://four.example/flood",
    }


@pytest.mark.parametrize(
    (
        "left_views",
        "left_rank",
        "left_hour",
        "right_views",
        "right_rank",
        "right_hour",
        "expected_url",
    ),
    [
        (10, 0, 6, 20, 0, 6, "https://two.example/b"),
        (20, 2, 6, 20, 1, 6, "https://two.example/b"),
        (20, 1, 6, 20, 1, 7, "https://two.example/b"),
        (20, 1, 7, 20, 1, 7, "https://one.example/a"),
    ],
)
def test_representative_ranking_uses_views_feed_rank_recency_and_stable_tie_break(
    left_views: int,
    left_rank: int,
    left_hour: int,
    right_views: int,
    right_rank: int,
    right_hour: int,
    expected_url: str,
) -> None:
    left = article(
        "포천 산불 현장 육군 장병 안전 지원",
        description="포천 산불 현장에서 육군 장병이 주민 안전을 지원했다.",
        url="https://one.example/a",
        priority=1,
        views=left_views,
        rank=left_rank,
        hour=left_hour,
    )
    right = article(
        "포천 산불 현장 육군 장병 주민 지원",
        description="포천 산불 현장에서 육군 장병이 주민 안전을 지원했다.",
        url="https://two.example/b",
        priority=1,
        views=right_views,
        rank=right_rank,
        hour=right_hour,
    )

    forward = select_articles((left, right), CONFIG)
    backward = select_articles((right, left), CONFIG)

    assert forward[OutputGroup.REGION][0].article.url == expected_url
    assert backward[OutputGroup.REGION][0].article.url == expected_url


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("폴란드 K9 수출 계약 체결", "루마니아 K9 수출 계약 체결"),
        ("포천 장병 수해복구 대민지원", "양주 장병 수해복구 대민지원"),
        ("K9 수출 계약 체결", "K9 수출 계약 취소"),
        ("무인차량 야전 시험 착수", "무인차량 양산 착수"),
        ("8사단 장병 전술훈련 실시", "8사단 장병 훈련 중 안전사고"),
    ],
)
def test_similar_but_distinct_events_are_not_deduplicated(first: str, second: str) -> None:
    items = (
        article(first, description=f"8사단 육군 관련 소식: {first}", url="https://one.example/a"),
        article(second, description=f"8사단 육군 관련 소식: {second}", url="https://two.example/b"),
    )

    selected = select_articles(items, CONFIG)

    assert sum(map(len, selected.values())) == 2


def test_default_group_limit_is_five_and_smaller_limit_keeps_deterministic_order() -> None:
    items = tuple(
        article(
            f"포천 육군 장병 안전 점검 {index}",
            description=f"포천에서 육군 장병 안전 점검 {index} 행사가 열렸다.",
            url=f"https://news.example/{index}",
            views=index,
            rank=10 - index,
            hour=index,
        )
        for index in range(7)
    )

    first = select_articles(items, CONFIG)
    second = select_articles(reversed(items), CONFIG)
    capped = select_articles(items, CONFIG, per_group_limit=3)

    first_urls = [item.article.url for item in first[OutputGroup.REGION]]
    second_urls = [item.article.url for item in second[OutputGroup.REGION]]
    assert len(first_urls) == 5
    assert first_urls == second_urls
    assert first_urls[0] == "https://news.example/6"
    assert len(capped[OutputGroup.REGION]) == 3


def test_flood_alert_headline_rewrites_collapse_to_one_event() -> None:
    items = (
        article(
            "연천 임진강 홍수경보",
            description="임진강 수위 상승으로 홍수경보가 발령됐다.",
            url="https://preferred.example/flood",
            priority=10,
        ),
        article(
            "연천 임진교 일대 홍수경보 발령",
            description="임진교 일대에 홍수경보가 내려졌다.",
            url="https://rewrite.example/flood",
        ),
        article(
            "연천 임진강 홍수주의보 격상",
            description="임진강 홍수주의보가 격상됐다.",
            url="https://update.example/flood",
        ),
        article(
            "포천 한탄강 홍수경보 발령",
            description="한탄강 수위 상승으로 홍수경보가 내려졌다.",
            url="https://distinct.example/flood",
        ),
    )

    selected = select_articles(items, CONFIG)

    assert [item.article.url for item in selected[OutputGroup.REGION]] == [
        "https://preferred.example/flood",
        "https://distinct.example/flood",
    ]


def test_invalid_group_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="between"):
        select_articles((), CONFIG, per_group_limit=0)
    with pytest.raises(ValueError, match="between"):
        select_articles((), CONFIG, per_group_limit=6)
