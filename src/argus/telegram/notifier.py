"""``TelegramNotifier`` (MASTER_SPEC.md section 94).

Every call is one outbound ``send_message`` to a fixed, closed set of
notification event types (below); there is no method here that reads or
acts on an inbound Telegram update, and no method that arms live trading,
changes risk configuration, or sends an arbitrary transaction -- the
absence of those capabilities is the actual enforcement, not a runtime
check that could be bypassed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    import httpx

NOTIFICATION_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "SYSTEM_FAILURE",
        "PROVIDER_BUDGET_WARNING",
        "WALLET_PROMOTION",
        "WALLET_QUARANTINE",
        "HIGH_VALUE_SIGNAL",
        "SHADOW_EVENT",
        "LIVE_ORDER_SUBMITTED",
        "LIVE_ORDER_CONFIRMED",
        "LIVE_ORDER_REJECTED",
        "RISK_KILL_SWITCH",
        "POSITION_EXIT",
        "DAILY_SUMMARY",
    }
)

# A best-effort guard against accidentally including an obvious secret-
# shaped token in a notification body -- "Never send secrets" (section
# 94). Not exhaustive; the real control is that no code path in this
# project ever hands a signing key, seed phrase, or API credential value
# to this module in the first place.
_SECRET_LIKE_RE = re.compile(
    r"(api[_-]?key|secret|token|password|private[_-]?key|seed[_-]?phrase)\s*[:=]\s*\S{8,}",
    re.IGNORECASE,
)


class SecretLikeContentError(ValueError):
    pass


class UnrecognizedNotificationEventError(ValueError):
    pass


class TelegramTransport(Protocol):
    async def send_message(self, *, chat_id: str, text: str) -> None: ...


class FakeTelegramTransport:
    """Deterministic in-memory transport -- every test and the Phase 4
    REPLAY demonstration use this, never a real Telegram Bot API call."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, *, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


class HttpTelegramTransport:
    """A real Telegram Bot API ``sendMessage`` transport. Exists as real,
    reviewable code -- never invoked with a real bot token anywhere in
    this repository's tests, CLI wiring, or REPLAY demonstration, per
    this instruction's own explicit prohibition on external delivery
    without separately established human authority."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        bot_token: str,
        base_url: str = "https://api.telegram.org",
    ) -> None:
        self._http = http_client
        self._bot_token = bot_token
        self._base_url = base_url

    async def send_message(self, *, chat_id: str, text: str) -> None:
        response = await self._http.post(
            f"{self._base_url}/bot{self._bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        response.raise_for_status()


class TelegramNotifier:
    def __init__(self, transport: TelegramTransport, *, chat_id: str) -> None:
        self._transport = transport
        self._chat_id = chat_id

    async def notify(self, *, event_type: str, text: str) -> None:
        if event_type not in NOTIFICATION_EVENT_TYPES:
            raise UnrecognizedNotificationEventError(
                f"unrecognized Telegram notification event_type {event_type!r} -- must be one "
                f"of {sorted(NOTIFICATION_EVENT_TYPES)}"
            )
        if _SECRET_LIKE_RE.search(text):
            raise SecretLikeContentError(
                "refusing to send a Telegram message whose text looks like it contains a secret"
            )
        await self._transport.send_message(chat_id=self._chat_id, text=text)
