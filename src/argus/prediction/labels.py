"""argus.prediction.labels -- MASTER_SPEC.md Phase 11 (PREDICT INFORMED
ORDER FLOW): pure construction of the labeled observation population.

An "observation" is a real, non-elite tracked-wallet entry (a genuine
point where ARGUS could ask "will an elite wallet follow?") -- entries
by wallets already elite AT THEIR OWN ENTRY TIME are excluded, since
predicting "does an already-elite wallet's own entry count as an elite
entry" is circular. The label at each horizon is whether ANY OTHER
wallet, itself elite AT ITS OWN ENTRY TIME, enters the same token within
that horizon.

FSR-10: a horizon's label is only ever a real ``bool`` when its full
``[entered_at, entered_at + horizon]`` window is already observable as of
``cutoff`` (``entered_at + horizon <= cutoff``). Otherwise the label is
``None`` -- RIGHT-CENSORED, never a fabricated ``False`` -- since the
absence of an elite follower in an INCOMPLETE future window is not
evidence of a true negative (MASTER_SPEC's own explicit rule). Every
consumer of ``labels`` must treat ``None`` as "exclude this observation
from this horizon's supervised population", never coerce it to ``False``.
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
    # FSR-10: None == right-censored (the horizon's label window is not
    # yet fully observable as of the run's cutoff) -- never a fabricated
    # False.
    labels: dict[int, bool | None]


def build_labeled_observations(
    entries: list[TieredEntry],
    *,
    horizons: tuple[timedelta, ...],
    elite_tiers: frozenset[str],
    cutoff: datetime,
) -> list[LabeledObservation]:
    by_token: dict[uuid.UUID, list[TieredEntry]] = {}
    for entry in entries:
        by_token.setdefault(entry.token_id, []).append(entry)

    observations: list[LabeledObservation] = []
    for entry in entries:
        if entry.tier_at_entry in elite_tiers:
            continue

        token_entries = by_token[entry.token_id]
        labels: dict[int, bool | None] = {}
        for horizon in horizons:
            deadline = entry.entered_at + horizon
            horizon_seconds = int(horizon.total_seconds())
            if deadline > cutoff:
                # FSR-10: the label window is not yet fully observed --
                # right-censored, never a fabricated negative.
                labels[horizon_seconds] = None
                continue
            followed = any(
                other.wallet_id != entry.wallet_id
                and other.tier_at_entry in elite_tiers
                and entry.entered_at < other.entered_at <= deadline
                for other in token_entries
            )
            labels[horizon_seconds] = followed

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
