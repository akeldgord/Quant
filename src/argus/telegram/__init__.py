"""Telegram notification-only integration (MASTER_SPEC.md section 94).

"Telegram is notification-only initially" and "MUST NOT initially arm
live trading, modify risk, send arbitrary transactions" -- there is no
inbound command handler anywhere in this package, only outbound
``send_message`` calls for a fixed, closed set of event types. This
sandbox has no configured bot token, and this instruction's own absolute
prohibitions forbid exercising real external delivery here -- every test
and the Phase 4 REPLAY demonstration use :class:`FakeTelegramTransport`.
"""

from __future__ import annotations
