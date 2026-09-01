from __future__ import annotations

import pytest

from argus.telegram.notifier import (
    NOTIFICATION_EVENT_TYPES,
    FakeTelegramTransport,
    SecretLikeContentError,
    TelegramNotifier,
    UnrecognizedNotificationEventError,
)

pytestmark = pytest.mark.asyncio


async def test_notify_delivers_to_transport_for_recognized_event_type() -> None:
    transport = FakeTelegramTransport()
    notifier = TelegramNotifier(transport, chat_id="chat-1")

    await notifier.notify(event_type="SHADOW_EVENT", text="wallet X entered a shadow position")

    assert transport.sent == [("chat-1", "wallet X entered a shadow position")]


async def test_notify_rejects_unrecognized_event_type() -> None:
    transport = FakeTelegramTransport()
    notifier = TelegramNotifier(transport, chat_id="chat-1")

    with pytest.raises(UnrecognizedNotificationEventError):
        await notifier.notify(event_type="NOT_A_REAL_EVENT", text="hello")

    assert transport.sent == []


async def test_notify_rejects_text_that_looks_like_a_secret() -> None:
    transport = FakeTelegramTransport()
    notifier = TelegramNotifier(transport, chat_id="chat-1")

    with pytest.raises(SecretLikeContentError):
        await notifier.notify(
            event_type="SYSTEM_FAILURE", text="api_key: sk-abcdefghijklmnopqrstuvwx"
        )

    assert transport.sent == []


async def test_notify_allows_short_colon_separated_text_that_is_not_secret_shaped() -> None:
    transport = FakeTelegramTransport()
    notifier = TelegramNotifier(transport, chat_id="chat-1")

    await notifier.notify(event_type="DAILY_SUMMARY", text="status: OK, trades: 3")

    assert transport.sent == [("chat-1", "status: OK, trades: 3")]


async def test_all_twelve_notification_event_types_are_accepted() -> None:
    transport = FakeTelegramTransport()
    notifier = TelegramNotifier(transport, chat_id="chat-1")

    for event_type in sorted(NOTIFICATION_EVENT_TYPES):
        await notifier.notify(event_type=event_type, text=f"{event_type} fired")

    assert len(transport.sent) == len(NOTIFICATION_EVENT_TYPES) == 12


async def test_fake_transport_records_every_call_independently() -> None:
    transport = FakeTelegramTransport()
    notifier = TelegramNotifier(transport, chat_id="chat-42")

    await notifier.notify(event_type="WALLET_PROMOTION", text="first")
    await notifier.notify(event_type="WALLET_QUARANTINE", text="second")

    assert transport.sent == [("chat-42", "first"), ("chat-42", "second")]
