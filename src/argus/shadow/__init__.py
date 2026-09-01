"""Phase 4 (PROSPECTIVE MONITORING + SHADOW COPYING) service layer.

MASTER_SPEC.md sections 44-48, 84 (`argus-phase-4-001`). Consumes the
real, already-ingested Phase 1 ``chain_events``/``swaps`` evidence and
the real Phase 3 wallet score/tier/position/cluster state -- never a
test-only fixture -- to build an honest, point-in-time-frozen research
record of tracked-wallet trades and simulated (never signed, never
broadcast) shadow copy attempts.

No module in this package ever imports a signing, key-management, or
broadcast capability. ``argus.providers.ExecutionProvider`` (Jupiter) is
used strictly for its quote/order-construction surface, exactly as Phase
1 already restricts it -- this package adds no new execution capability
of its own.
"""

from __future__ import annotations
