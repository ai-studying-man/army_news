"""Command-line entry point for deterministic briefing collection and delivery."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

from army_morning_brief.briefing import render_briefing_html
from army_morning_brief.collector import (
    CollectionDiagnostic,
    FeedParseError,
    collect_articles,
    parse_rss,
)
from army_morning_brief.config import KST, BriefConfig, CollectionWindow, kst_collection_window
from army_morning_brief.models import Article, Source
from army_morning_brief.pipeline import select_articles
from army_morning_brief.sources import configured_sources
from army_morning_brief.telegram import TelegramDeliveryError, send_telegram_message

_FIXTURE_SOURCE = Source("fixture", "https://fixture.invalid/feed.xml")


def _aware_iso8601(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a valid ISO 8601 datetime") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("must include a UTC offset")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="army-news")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print HTML without sending")
    mode.add_argument("--send", action="store_true", help="send the briefing to Telegram")
    parser.add_argument("--fixture", type=Path, help="read one local RSS fixture")
    parser.add_argument("--now", type=_aware_iso8601, default=datetime.now(KST))
    parser.add_argument("--max-per-group", type=int, choices=range(1, 6), default=5)
    return parser


def _load_fixture_articles(path: Path, window: CollectionWindow) -> tuple[Article, ...]:
    return parse_rss(path.read_bytes(), _FIXTURE_SOURCE, window)


def _print_diagnostics(diagnostics: tuple[CollectionDiagnostic, ...]) -> None:
    for diagnostic in diagnostics:
        print(f"source diagnostic: {diagnostic.code}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Collect, select, and either print or deliver one briefing."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    fixture = cast(Path | None, arguments.fixture)
    run_at = cast(datetime, arguments.now)
    max_per_group = cast(int, arguments.max_per_group)
    send = cast(bool, arguments.send)

    token: str | None = None
    chat_ids: str | None = None
    if send:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_ids = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_ids:
            print(
                "army-news: error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required for --send",
                file=sys.stderr,
            )
            return 2

    try:
        config = BriefConfig.from_env()
    except ValueError:
        parser.error("ARMY_BRIEF_CONFIG_JSON is invalid")

    window = kst_collection_window(run_at)
    if fixture is not None:
        try:
            articles = _load_fixture_articles(fixture, window)
        except OSError:
            print("fixture failed: unreadable", file=sys.stderr)
            return 1
        except FeedParseError:
            print("fixture failed: invalid_feed", file=sys.stderr)
            return 1
    else:
        collection = collect_articles(configured_sources(config), window)
        articles = collection.articles
        _print_diagnostics(collection.diagnostics)

    groups = select_articles(articles, config, per_group_limit=max_per_group)
    briefing = render_briefing_html(groups, run_at)
    if not send:
        print(briefing)
        return 0

    assert token is not None and chat_ids is not None
    try:
        send_telegram_message(token=token, chat_ids=chat_ids, text=briefing)
    except TelegramDeliveryError as error:
        print(f"delivery failed: {error}", file=sys.stderr)
        return 1
    print("briefing sent")
    return 0
