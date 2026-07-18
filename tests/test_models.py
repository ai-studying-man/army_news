from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from army_morning_brief.config import BriefConfig, kst_collection_window
from army_morning_brief.models import Article, Source

KST = timezone(timedelta(hours=9))


def make_source(**overrides: object) -> Source:
    values: dict[str, object] = {
        "name": "육군 공식",
        "url": "https://army.example/feed",
        "priority": 3,
    }
    values.update(overrides)
    return Source(**values)  # type: ignore[arg-type]


def test_source_and_article_preserve_ranking_metadata_and_are_frozen() -> None:
    source = make_source()
    article = Article(
        title="육군 훈련",
        description="공식 발표",
        url="https://news.example/article/1",
        published_at=datetime(2026, 7, 18, 6, 30, tzinfo=KST),
        source=source,
        feed_rank=2,
        view_count=1500,
    )

    assert (source.priority, article.feed_rank, article.view_count) == (3, 2, 1500)
    with pytest.raises(FrozenInstanceError):
        source.priority = 4  # type: ignore[misc]


@pytest.mark.parametrize("url", ["http://example.com/feed", "ftp://example.com/feed", "not-a-url"])
def test_source_rejects_non_https_urls(url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        make_source(url=url)


def test_article_rejects_non_https_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        Article(
            title="제목",
            description="설명",
            url="http://news.example/1",
            published_at=datetime(2026, 7, 18, 6, 30, tzinfo=KST),
            source=make_source(),
        )


def test_article_rejects_naive_published_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Article(
            title="제목",
            description="설명",
            url="https://news.example/1",
            published_at=datetime(2026, 7, 18, 6, 30),
            source=make_source(),
        )


def test_kst_window_starts_at_previous_day_1400_and_ends_at_actual_run_time() -> None:
    run_at = datetime(2026, 7, 18, 8, 17, tzinfo=KST)
    window = kst_collection_window(run_at)

    assert window.start == datetime(2026, 7, 17, 14, 0, tzinfo=KST)
    assert window.end == run_at
    assert window.contains(datetime(2026, 7, 17, 14, 0, tzinfo=KST))
    assert not window.contains(datetime(2026, 7, 17, 13, 59, 59, 999999, tzinfo=KST))
    assert window.contains(run_at)


def test_kst_window_converts_an_aware_non_kst_run_time() -> None:
    run_at_utc = datetime(2026, 7, 17, 21, 30, tzinfo=UTC)
    window = kst_collection_window(run_at_utc)

    assert window.start == datetime(2026, 7, 17, 14, 0, tzinfo=KST)
    assert window.end == datetime(2026, 7, 18, 6, 30, tzinfo=KST)


def test_window_rejects_naive_run_and_candidate_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        kst_collection_window(datetime(2026, 7, 18, 6, 30))

    window = kst_collection_window(datetime(2026, 7, 18, 6, 30, tzinfo=KST))
    with pytest.raises(ValueError, match="timezone-aware"):
        window.contains(datetime(2026, 7, 17, 14, 0))


def test_default_config_uses_prompt_aliases_and_regions() -> None:
    rule = BriefConfig.default().divisions[0]

    assert rule.aliases == ("8사단", "8기동사단", "3070부대", "오뚜기부대")
    assert rule.regions == ("양주", "동두천", "포천", "연천", "의정부")


def test_config_accepts_mapping_and_environment_json_overrides() -> None:
    data = {
        "divisions": [
            {"name": "별빛사단", "aliases": ["별빛부대"], "regions": ["춘천", "홍천"]},
            {"name": "해오름사단", "aliases": ["해오름부대"], "regions": ["강릉"]},
        ]
    }

    mapped = BriefConfig.from_mapping(data)
    from_environment = BriefConfig.from_env(
        {"ARMY_BRIEF_CONFIG_JSON": '{"divisions": [{"name": "교체사단", '
        '"aliases": ["교체부대"], "regions": ["원주"]}]}' }
    )

    assert [rule.name for rule in mapped.divisions] == ["별빛사단", "해오름사단"]
    assert mapped.divisions[0].regions != mapped.divisions[1].regions
    assert from_environment.divisions[0].aliases == ("교체부대",)
