"""baseline: least-privilege DB roles + provider_usage table

Revision ID: 0001
Revises:
Create Date: 2026-08-30

Implements MASTER_SPEC.md section 72 (database privilege separation) and the
provider_usage schema from section 14. Role passwords are read from required
environment variables (ARGUS_DB_{INGEST,RESEARCH,EXECUTOR}_PASSWORD) at
migration time via ``argus.db.credentials.require_password`` — there is no
fallback/default password anywhere in this file or elsewhere in the
repository (SEC-005 / section 108). If a required variable is missing, the
migration fails immediately with a ``LOCAL CREDENTIAL REQUIRED`` error
instead of silently substituting a working password.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from argus.config import load_config  # noqa: E402
from argus.db.credentials import PASSWORD_ENV_VARS, require_password  # noqa: E402
from argus.db.roles import DbRole  # noqa: E402

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_NAMES: tuple[str, ...] = (
    DbRole.INGEST.value,
    DbRole.RESEARCH.value,
    DbRole.EXECUTOR.value,
)


def _required_role_passwords() -> dict[str, str]:
    """Read each role's password from a required env var. Raises
    MissingCredentialError immediately if any is unset -- fail closed, no
    fallback (see module docstring).
    """
    env = load_config().env
    return {role.value: require_password(env, var) for role, var in PASSWORD_ENV_VARS.items()}


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _create_role_if_missing(role: str, password: str) -> None:
    pw_literal = _quote_literal(password)
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
            CREATE ROLE {role} LOGIN PASSWORD {pw_literal};
          END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    role_passwords = _required_role_passwords()
    for role, password in role_passwords.items():
        _create_role_if_missing(role, password)

    # GRANT CONNECT ON DATABASE requires a literal database name.
    current_db = op.get_bind().engine.url.database
    for role in _ROLE_NAMES:
        op.execute(f'GRANT CONNECT ON DATABASE "{current_db}" TO {role};')
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role};")

    op.create_table(
        "provider_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=256), nullable=False),
        sa.Column("request_class", sa.String(length=64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_credits", sa.Numeric(18, 6), nullable=True),
        sa.Column("bytes_received", sa.BigInteger(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("connection_count", sa.Integer(), nullable=True),
        sa.Column("subscription_count", sa.Integer(), nullable=True),
        sa.Column("reconnect_count", sa.Integer(), nullable=True),
        sa.Column("estimated_streaming_credits", sa.Numeric(18, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_usage_provider", "provider_usage", ["provider"])
    op.create_index("ix_provider_usage_request_class", "provider_usage", ["request_class"])
    op.create_index("ix_provider_usage_requested_at", "provider_usage", ["requested_at"])
    op.create_index("ix_provider_usage_created_at", "provider_usage", ["created_at"])

    # Least-privilege grants (section 72):
    #   - ingest writes usage rows (it makes the outbound requests).
    #   - research reads usage for cost-guard/reporting, never writes it.
    #   - executor gets nothing here in Phase 0; Phase 6 grants it whatever
    #     minimal read access the risk engine's provider-budget check needs.
    op.execute("GRANT SELECT, INSERT, UPDATE ON provider_usage TO argus_ingest;")
    op.execute("GRANT SELECT ON provider_usage TO argus_research;")


def downgrade() -> None:
    op.execute("REVOKE ALL ON provider_usage FROM argus_ingest;")
    op.execute("REVOKE ALL ON provider_usage FROM argus_research;")
    op.drop_index("ix_provider_usage_created_at", table_name="provider_usage")
    op.drop_index("ix_provider_usage_requested_at", table_name="provider_usage")
    op.drop_index("ix_provider_usage_request_class", table_name="provider_usage")
    op.drop_index("ix_provider_usage_provider", table_name="provider_usage")
    op.drop_table("provider_usage")
    for role in _ROLE_NAMES:
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role};")
