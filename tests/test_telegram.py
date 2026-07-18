from __future__ import annotations

import html
import json
from collections.abc import Callable
from html.parser import HTMLParser
from typing import cast

import httpx
import pytest

from army_morning_brief.telegram import (
    TelegramDeliveryError,
    parse_chat_ids,
    send_telegram_message,
    split_html_message,
)

TOKEN = "TEST_ONLY_TOKEN"
CHAT = "recipient-alpha"


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _visible_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def _json_body(request: httpx.Request) -> dict[str, object]:
    return cast(dict[str, object], json.loads(request.content))


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_success_uses_https_html_payload_and_explicit_timeout() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    with _client(handler) as client:
        send_telegram_message(
            token=TOKEN,
            chat_ids=CHAT,
            text='<b>Morning</b> <a href="https://example.invalid/a">brief</a>',
            client=client,
        )

    assert len(requests) == 1
    request = requests[0]
    assert request.url.scheme == "https"
    assert request.method == "POST"
    assert request.extensions["timeout"] == {
        "connect": 5.0,
        "read": 15.0,
        "write": 15.0,
        "pool": 5.0,
    }
    assert _json_body(request) == {
        "chat_id": CHAT,
        "text": '<b>Morning</b> <a href="https://example.invalid/a">brief</a>',
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }


def test_http_200_api_error_is_rejected_without_sensitive_response_details() -> None:
    response_body = "PRIVATE_RESPONSE_BODY"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": response_body})

    with _client(handler) as client, pytest.raises(TelegramDeliveryError) as caught:
        send_telegram_message(token=TOKEN, chat_ids=CHAT, text="brief", client=client)

    message = str(caught.value)
    assert message == "Telegram rejected the message"
    assert TOKEN not in message
    assert CHAT not in message
    assert response_body not in message
    assert "api.telegram.org" not in message


def test_rate_limit_sleeps_for_bounded_retry_after_then_retries() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                json={"ok": False, "parameters": {"retry_after": 9999}},
            )
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        send_telegram_message(
            token=TOKEN,
            chat_ids=CHAT,
            text="brief",
            client=client,
            sleep=sleeps.append,
            max_retries=1,
        )

    assert attempts == 2
    assert sleeps == [60.0]


def test_migrated_chat_id_is_retried_without_exposing_or_reordering_recipients() -> None:
    received: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(cast(str, _json_body(request)["chat_id"]))
        if len(received) == 1:
            return httpx.Response(
                400,
                json={"ok": False, "parameters": {"migrate_to_chat_id": "replacement"}},
            )
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        send_telegram_message(
            token=TOKEN,
            chat_ids=("legacy", "second"),
            text="brief",
            client=client,
        )

    assert received == ["legacy", "replacement", "second"]


def test_transport_timeout_is_sanitized() -> None:
    leaked_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT}"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout at {leaked_url}", request=request)

    with _client(handler) as client, pytest.raises(TelegramDeliveryError) as caught:
        send_telegram_message(token=TOKEN, chat_ids=CHAT, text="brief", client=client)

    assert str(caught.value) == "Telegram request failed"
    assert TOKEN not in str(caught.value)
    assert CHAT not in str(caught.value)
    assert leaked_url not in str(caught.value)


def test_comma_separated_chat_ids_remain_opaque_and_send_in_order() -> None:
    received: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(cast(str, _json_body(request)["chat_id"]))
        return httpx.Response(200, json={"ok": True})

    assert parse_chat_ids(" 001, @channel-name,recipient:z ") == (
        "001",
        "@channel-name",
        "recipient:z",
    )
    with _client(handler) as client:
        send_telegram_message(
            token=TOKEN,
            chat_ids=" 001, @channel-name,recipient:z ",
            text="brief",
            client=client,
        )

    assert received == ["001", "@channel-name", "recipient:z"]


def test_long_korean_emoji_html_is_split_without_content_loss_or_broken_links() -> None:
    linked = '<a href="https://example.invalid/report?x=1&amp;y=2">' + ("육군😀" * 1500) + "</a>"
    source = "<b>아침 브리핑</b>\n" + linked + "\n<blockquote>끝 &amp; 확인</blockquote>"

    chunks = split_html_message(source)

    assert len(chunks) >= 2
    assert all(len(_visible_text(chunk)) <= 4096 for chunk in chunks)
    assert "".join(_visible_text(chunk) for chunk in chunks) == _visible_text(source)
    assert all(
        chunk.count('<a href="https://example.invalid/report?x=1&amp;y=2">') == chunk.count("</a>")
        for chunk in chunks
    )


def test_caller_escaped_html_like_text_stays_escaped() -> None:
    escaped = html.escape('<script data-x="bad">alert(1)</script> & done')
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(_json_body(request))
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        send_telegram_message(token=TOKEN, chat_ids=CHAT, text=escaped, client=client)

    assert bodies[0]["text"] == escaped
    assert "<script" not in cast(str, bodies[0]["text"])
