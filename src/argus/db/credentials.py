"""Required, non-defaulted database credential resolution.

MASTER_SPEC.md SEC-005 / section 108: no credential value is ever hardcoded
or silently substituted anywhere in this repository — not even a "dev only"
placeholder. Every DB role password must come from an external environment
variable (typically supplied via a local, gitignored ``.env`` file). If a
required variable is missing at the point a real connection/migration is
about to be attempted, this module fails loudly and immediately with a
``LOCAL CREDENTIAL REQUIRED`` message (section 108 format) rather than
falling back to a working default.
"""

from __future__ import annotations

from collections.abc import Mapping

from argus.db.roles import DbRole

PASSWORD_ENV_VARS: dict[DbRole, str] = {
    DbRole.INGEST: "ARGUS_DB_INGEST_PASSWORD",
    DbRole.RESEARCH: "ARGUS_DB_RESEARCH_PASSWORD",
    DbRole.EXECUTOR: "ARGUS_DB_EXECUTOR_PASSWORD",
}
ADMIN_PASSWORD_ENV_VAR = "ARGUS_DB_ADMIN_PASSWORD"


class MissingCredentialError(RuntimeError):
    """Raised instead of silently substituting a password.

    Never caught-and-defaulted anywhere in application code: a missing DB
    credential must stop the operation, not proceed with a guessed value.
    """


def require_password(env: Mapping[str, str], var_name: str) -> str:
    value = env.get(var_name)
    if not value:
        raise MissingCredentialError(
            f"LOCAL CREDENTIAL REQUIRED:\n{var_name}\n"
            "Place it locally in your .env file (gitignored; see .env.example) "
            "or process environment before running migrations or connecting "
            "to Postgres. DO NOT paste its value into chat. No fallback "
            "password exists — this is intentional (MASTER_SPEC.md SEC-005)."
        )
    return value
