"""Resolve :class:`DbConnectionInfo` for a given role from ArgusConfig/env."""

from __future__ import annotations

from argus.config import ArgusConfig
from argus.db.credentials import ADMIN_PASSWORD_ENV_VAR, PASSWORD_ENV_VARS, require_password
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
    password = require_password(env, PASSWORD_ENV_VARS[role])
    return DbConnectionInfo(
        host=env.get("ARGUS_DB_HOST", "localhost"),
        port=int(env.get("ARGUS_DB_PORT", "5432")),
        database=env.get("ARGUS_DB_NAME", "argus"),
        user=env.get(f"{prefix}_USER", role.value),
        password=password,
    )


def connection_for_admin(config: ArgusConfig) -> DbConnectionInfo:
    """Admin/superuser connection used only for running migrations (DDL,
    role creation/grants). Never used by application code at runtime —
    see MASTER_SPEC.md section 72.
    """
    env = config.env
    password = require_password(env, ADMIN_PASSWORD_ENV_VAR)
    return DbConnectionInfo(
        host=env.get("ARGUS_DB_HOST", "localhost"),
        port=int(env.get("ARGUS_DB_PORT", "5432")),
        database=env.get("ARGUS_DB_NAME", "argus"),
        user=env.get("ARGUS_DB_ADMIN_USER", "argus_admin"),
        password=password,
    )
