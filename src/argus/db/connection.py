"""Resolve :class:`DbConnectionInfo` for a given role from ArgusConfig/env."""

from __future__ import annotations

from argus.config import ArgusConfig
from argus.db.roles import DbRole
from argus.db.session import DbConnectionInfo

_ROLE_ENV_PREFIX = {
    DbRole.INGEST: "ARGUS_DB_INGEST",
    DbRole.RESEARCH: "ARGUS_DB_RESEARCH",
    DbRole.EXECUTOR: "ARGUS_DB_EXECUTOR",
}


def connection_for_role(config: ArgusConfig, role: DbRole) -> DbConnectionInfo:
    env = config.env
    prefix = _ROLE_ENV_PREFIX[role]
    return DbConnectionInfo(
        host=env.get("ARGUS_DB_HOST", "localhost"),
        port=int(env.get("ARGUS_DB_PORT", "5432")),
        database=env.get("ARGUS_DB_NAME", "argus"),
        user=env.get(f"{prefix}_USER", role.value),
        password=env.get(f"{prefix}_PASSWORD", ""),
    )


def connection_for_admin(config: ArgusConfig) -> DbConnectionInfo:
    """Admin/superuser connection used only for running migrations (DDL,
    role creation/grants). Never used by application code at runtime —
    see MASTER_SPEC.md section 72.
    """
    env = config.env
    return DbConnectionInfo(
        host=env.get("ARGUS_DB_HOST", "localhost"),
        port=int(env.get("ARGUS_DB_PORT", "5432")),
        database=env.get("ARGUS_DB_NAME", "argus"),
        user=env.get("ARGUS_DB_ADMIN_USER", "argus_admin"),
        password=env.get("ARGUS_DB_ADMIN_PASSWORD", "REDACTED_FORMER_DEV_PLACEHOLDER"),
    )
