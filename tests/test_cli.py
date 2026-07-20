from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from army_morning_brief import cli
from army_morning_brief.collector import CollectionDiagnostic, CollectionResult
from army_morning_brief.config import BriefConfig, CollectionWindow
from army_morning_brief.models import Article, Source
from army_morning_brief.telegram import TelegramDeliveryError

FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-07-18T06:30:00+09:00"


def _fixture(name: str) -> str:
    return str(FIXTURES / name)


def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ARMY_BRIEF_CONFIG_JSON", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)


def _unexpected_call(*args: object, **kwargs: object) -> NoReturn:
    pytest.fail(f"unexpected call: {args!r}, {sorted(kwargs)}")


def test_c001_daily_fixture_dry_run_renders_expected_briefing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_environment(monkeypatch)

    result = cli.main(["--fixture", _fixture("daily_feed.xml"), "--dry-run", "--now", NOW])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out.startswith("['26.7.18.(토), 아침 언론 모니터 결과]\n")
    assert "■ [사단] 8사단 장병 안전교육 실시 (공개 언론사)\n" in captured.out
    assert "https://news.example.test/division-safety" in captured.out
    assert "- 장병 대상 안전 교육 &amp; 점검" in captured.out
    assert "■ [지역] 양주시 군·관 재난대응 협력 (fixture)\n" in captured.out
    assert "https://news.example.test/region-cooperation" in captured.out
    assert "- 양주시와 군 관계자가 공개 훈련을 점검했다." in captured.out
    assert "※ 외교/북한 관련 보도 없음" in captured.out
    assert captured.out.index("■ [사단]") < captured.out.index("■ [지역]")
    assert "출처:" not in captured.out
    assert "발행:" not in captured.out
    assert "원문 기사" not in captured.out
    assert "too-early" not in captured.out
    assert "too-late" not in captured.out


def test_delayed_run_keeps_fixed_0500_cutoff_and_boundary_region_article(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_environment(monkeypatch)

    result = cli.main(
        [
            "--fixture",
            _fixture("daily_feed.xml"),
            "--dry-run",
            "--now",
            "2026-07-18T08:17:00+09:00",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "■ [지역] 양주시 군·관 재난대응 협력" in captured.out
    assert "too-late" not in captured.out


def test_c002_adversarial_fixture_filters_invalid_and_escapes_html(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_environment(monkeypatch)
    monkeypatch.setenv(
        "ARMY_BRIEF_CONFIG_JSON",
        '{"divisions":[{"name":"test","aliases":["중복 사건","정상 별도 기사"],'
        '"regions":["양주"]}]}',
    )

    result = cli.main(["--fixture", _fixture("adversarial_feed.xml"), "--dry-run", "--now", NOW])

    output = capsys.readouterr().out
    assert result == 0
    assert "날짜 형식 오류" not in output
    assert "HTTP 링크 거부" not in output
    assert "날짜 누락" not in output
    assert "양주 가격 상승" not in output
    assert output.count("중복 사건") == 1
    assert "정상 별도 기사 &lt;확인&gt;" in output
    assert "공개 자료 &lt;검토&gt; &amp; 후속 발표" in output
    assert 'href="https://news.example.test/distinct"' in output


@pytest.mark.parametrize("now", ["2026-07-18T06:30:00", "not-a-time"])
def test_now_requires_valid_aware_iso8601(now: str) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--fixture", _fixture("daily_feed.xml"), "--dry-run", "--now", now])
    assert raised.value.code == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["--fixture", _fixture("daily_feed.xml"), "--now", NOW],
        ["--fixture", _fixture("daily_feed.xml"), "--dry-run", "--send", "--now", NOW],
        ["--fixture", _fixture("daily_feed.xml"), "--dry-run", "--max-per-group", "0"],
        ["--fixture", _fixture("daily_feed.xml"), "--dry-run", "--max-per-group", "6"],
        ["--fixture", _fixture("daily_feed.xml"), "--dry-run", "--token", "secret"],
    ],
)
def test_invalid_modes_limits_and_secret_cli_options_exit_two(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)
    assert raised.value.code == 2


def test_live_dry_run_uses_collection_window_and_safe_diagnostic_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_environment(monkeypatch)
    source = Source("name-with-PRIVATE", "https://feeds.example.test/token-value.xml")
    seen: list[tuple[tuple[Source, ...], CollectionWindow]] = []

    def sources(config: BriefConfig) -> tuple[Source, ...]:
        del config
        return (source,)

    monkeypatch.setattr(cli, "configured_sources", sources)

    def collect(input_sources: tuple[Source, ...], window: CollectionWindow) -> CollectionResult:
        seen.append((input_sources, window))
        return CollectionResult((), (CollectionDiagnostic("PRIVATE", "request_failed"),))

    monkeypatch.setattr(cli, "collect_articles", collect)
    monkeypatch.setattr(
        cli,
        "send_telegram_message",
        _unexpected_call,
    )

    result = cli.main(["--dry-run", "--now", NOW])

    captured = capsys.readouterr()
    assert result == 0
    assert len(seen) == 1
    window = seen[0][1]
    assert window.start.isoformat() == "2026-07-17T14:00:00+09:00"
    assert window.end.isoformat() == "2026-07-18T05:00:00+09:00"
    assert captured.err == "source diagnostic: request_failed\n"
    assert "PRIVATE" not in captured.err
    assert "token-value" not in captured.err


@pytest.mark.parametrize(
    ("token", "chat_id"),
    [(None, None), ("token", None), (None, "chat")],
)
def test_send_missing_credentials_exits_two_before_fixture_or_network(
    monkeypatch: pytest.MonkeyPatch,
    token: str | None,
    chat_id: str | None,
) -> None:
    _clean_environment(monkeypatch)
    if token is not None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    if chat_id is not None:
        monkeypatch.setenv("TELEGRAM_CHAT_ID", chat_id)
    monkeypatch.setattr(
        cli,
        "_load_fixture_articles",
        _unexpected_call,
    )
    monkeypatch.setattr(
        cli,
        "collect_articles",
        _unexpected_call,
    )
    monkeypatch.setattr(
        cli,
        "send_telegram_message",
        _unexpected_call,
    )

    assert cli.main(["--fixture", "missing.xml", "--send", "--now", NOW]) == 2


def test_send_reads_environment_and_reports_only_safe_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_environment(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "private-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "private-chat")
    sent: list[dict[str, object]] = []

    def record_send(**kwargs: object) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(cli, "send_telegram_message", record_send)

    result = cli.main(["--fixture", _fixture("daily_feed.xml"), "--send", "--now", NOW])

    captured = capsys.readouterr()
    assert result == 0
    assert len(sent) == 1
    assert sent[0]["token"] == "private-token"
    assert sent[0]["chat_ids"] == "private-chat"
    assert captured.out == "briefing sent\n"
    assert "private-token" not in captured.out + captured.err
    assert "private-chat" not in captured.out + captured.err


def test_telegram_delivery_failure_is_safe_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_environment(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "private-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "private-chat")

    def fail_delivery(**kwargs: object) -> None:
        del kwargs
        raise TelegramDeliveryError("Telegram request failed")

    monkeypatch.setattr(cli, "send_telegram_message", fail_delivery)

    result = cli.main(["--fixture", _fixture("daily_feed.xml"), "--send", "--now", NOW])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "delivery failed: Telegram request failed\n"
    assert "private-token" not in captured.err
    assert "private-chat" not in captured.err


def test_fixture_uses_synthetic_https_source_without_collection_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_environment(monkeypatch)
    seen: list[Source] = []
    original = cli.parse_rss

    def parse(xml: bytes, source: Source, window: CollectionWindow) -> tuple[Article, ...]:
        seen.append(source)
        return original(xml, source, window)

    monkeypatch.setattr(cli, "parse_rss", parse)
    monkeypatch.setattr(
        cli,
        "collect_articles",
        _unexpected_call,
    )

    assert cli.main(["--fixture", _fixture("daily_feed.xml"), "--dry-run", "--now", NOW]) == 0
    assert len(seen) == 1
    assert seen[0].url == "https://fixture.invalid/feed.xml"
