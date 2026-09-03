"""argus.prediction.labels -- MASTER_SPEC.md Phase 11 (PREDICT INFORMED
ORDER FLOW): pure construction of the labeled observation population.

An "observation" is a real, non-elite tracked-wallet entry (a genuine
point where ARGUS could ask "will an elite wallet follow?") -- entries
by wallets already elite AT THEIR OWN ENTRY TIME are excluded, since
predicting "does an already-elite wallet's own entry count as an elite
entry" is circular. The label at each horizon is whether ANY OTHER
wallet, itself elite AT ITS OWN ENTRY TIME, enters the same token within
that horizon.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class TieredEntry:
    wallet_id: uuid.UUID
    token_id: uuid.UUID
    entered_at: datetime
    source_id: uuid.UUID
    tier_at_entry: str | None


@dataclass(frozen=True)
class LabeledObservation:
    wallet_id: uuid.UUID
    token_id: uuid.UUID
    entered_at: datetime
    source_id: uuid.UUID
    labels: dict[int, bool]


def build_labeled_observations(
    entries: list[TieredEntry], *, horizons: tuple[timedelta, ...], elite_tiers: frozenset[str]
) -> list[LabeledObservation]:
    by_token: dict[uuid.UUID, list[TieredEntry]] = {}
    for entry in entries:
        by_token.setdefault(entry.token_id, []).append(entry)

    observations: list[LabeledObservation] = []
    for entry in entries:
        if entry.tier_at_entry in elite_tiers:
            continue

        token_entries = by_token[entry.token_id]
        labels: dict[int, bool] = {}
        for horizon in horizons:
            deadline = entry.entered_at + horizon
            followed = any(
                other.wallet_id != entry.wallet_id
                and other.tier_at_entry in elite_tiers
                and entry.entered_at < other.entered_at <= deadline
                for other in token_entries
            )
            labels[int(horizon.total_seconds())] = followed

        observations.append(
            LabeledObservation(
                wallet_id=entry.wallet_id,
                token_id=entry.token_id,
                entered_at=entry.entered_at,
                source_id=entry.source_id,
                labels=labels,
            )
        )
    return observations
