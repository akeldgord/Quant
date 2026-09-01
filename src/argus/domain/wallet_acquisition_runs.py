"""``wallet_acquisition_runs`` — Phase 3 remediation round 2 (P3-R1/P3-R2,
`argus-phase-3-remediation-002`).

The real, structured, immutable RESULT of an actually-executed
acquisition walk (see ``argus.wallets.acquisition.run_wallet_acquisition``),
persisted with an explicit wallet binding so a later score can load-and-
verify it by ``run_id`` instead of trusting an arbitrary caller-supplied
JSON file (the exact P3-R2 defect this replaces -- see
``argus.wallets.history_reconstruction`` module docstring history for the
prior, now-removed, caller-file-based path).

``manifest`` stores ``argus.wallets.history_reconstruction.manifest_as_dict(...)``
verbatim -- the wallet-address walk's terminal status, whether associated
token-account enumeration was genuinely attempted, each enumerated
account's own pubkey/owner/mint/status coverage, the provider set, known
gaps, and an evidence reference. ``observation_cutoff`` is the point in
time this run's own evidence walk was actually executed at (``now`` at
acquisition time) -- a score computed for an earlier ``as_of`` may never
load a run whose ``observation_cutoff`` is later than that ``as_of``: a
run "learned after T cannot justify history at T" (this instruction's own
explicit requirement).

Append-only, never updated in place: a wallet may accumulate several
acquisition runs over time (a later, more complete walk), each its own
immutable row; a score binds to exactly one run by ``run_id``, never "the
latest run" implicitly (a stale/superseded run must remain loadable and
verifiable for a historical score's own exact replay).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class WalletAcquisitionRun(Base):
    """One immutable, verified acquisition-run result for one wallet."""

    __tablename__ = "wallet_acquisition_runs"
    __table_args__ = (
        CheckConstraint(
            "length(algorithm_version) > 0", name="ck_wallet_acquisition_runs_algo_version"
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )

    observation_cutoff: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
