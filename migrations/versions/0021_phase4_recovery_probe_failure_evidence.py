"""Phase 4 recovery: shadow_quote_probes.failure_evidence

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-02

Per orchestrator instruction ``argus-phase-4-recovery-001`` (P4-REC-03,
frozen finding R4-E from ``argus-phase-4-failure-review-001``): "terminal
probe records must preserve safe, supplied provider status/code/reason and
scheduler rejection reason needed to explain NO_ROUTE,
PROVIDER_CAPACITY_MISS and QUOTE_FAILED. Do not store secrets, headers,
arbitrary URLs, or unsanitized bodies. Do not invent provider mappings."

Adds a nullable ``failure_evidence`` JSONB column to ``shadow_quote_
probes``, populated only on the shared entry/reverse exception seam
(``argus.shadow.quote_jobs._classify_provider_exception``) with a small,
bounded, already-sanitized set of keys -- never the raw response body,
headers, or request URL. Additive only; no existing row's meaning
changes; no new grant needed (migration 0016's table-level UPDATE grant on
``shadow_quote_probes`` for ``argus_ingest`` already covers this new
column).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shadow_quote_probes",
        sa.Column("failure_evidence", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shadow_quote_probes", "failure_evidence")
