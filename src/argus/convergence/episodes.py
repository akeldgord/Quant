"""argus.convergence.episodes -- MASTER_SPEC.md Phase 8 (CONVERGENCE +
NEGATIVE EVIDENCE), section 59 (CONVERGENCE SURPRISE): pure grouping of
same-token tracked-wallet entries into convergence episodes.

An "episode" is one token's own first wave of tracked-wallet interest: it
is anchored at the earliest known entrant and includes every distinct
wallet's own earliest entry into that token within a configured window of
that anchor. A wallet re-entering the same token later does not start a
second episode -- convergence is about a token's own first wave of
tracked-wallet interest, not every entry ever recorded against it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from argus.graph.lead_follow import WalletTokenEntry


@dataclass(frozen=True)
class ConvergenceEpisode:
    token_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    entries: tuple[WalletTokenEntry, ...]
    raw_wallet_count: int


def build_convergence_episodes(
    entries: list[WalletTokenEntry], *, window: timedelta
) -> list[ConvergenceEpisode]:
    """One episode per distinct ``token_id`` present in ``entries``."""
    by_token: dict[uuid.UUID, list[WalletTokenEntry]] = {}
    for entry in entries:
        by_token.setdefault(entry.token_id, []).append(entry)

    episodes: list[ConvergenceEpisode] = []
    for token_id, token_entries in by_token.items():
        earliest_by_wallet: dict[uuid.UUID, WalletTokenEntry] = {}
        for entry in token_entries:
            existing = earliest_by_wallet.get(entry.wallet_id)
            if existing is None or entry.entered_at < existing.entered_at:
                earliest_by_wallet[entry.wallet_id] = entry
        if not earliest_by_wallet:
            continue
        ordered = sorted(earliest_by_wallet.values(), key=lambda e: e.entered_at)
        window_start = ordered[0].entered_at
        window_end = window_start + window
        members = tuple(e for e in ordered if e.entered_at <= window_end)
        episodes.append(
            ConvergenceEpisode(
                token_id=token_id,
                window_start=window_start,
                window_end=window_end,
                entries=members,
                raw_wallet_count=len(members),
            )
        )
    return episodes
