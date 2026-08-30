from __future__ import annotations

import pytest

from argus.config import ArgusConfig
from argus.db.connection import connection_for_admin, connection_for_role
from argus.db.credentials import (
    ADMIN_PASSWORD_ENV_VAR,
    PASSWORD_ENV_VARS,
    MissingCredentialError,
    require_password,
)
from argus.db.roles import DbRole


def test_require_password_raises_clearly_when_missing() -> None:
    with pytest.raises(MissingCredentialError) as exc_info:
        require_password({}, "ARGUS_DB_INGEST_PASSWORD")

    message = str(exc_info.value)
    assert "LOCAL CREDENTIAL REQUIRED" in message
    assert "ARGUS_DB_INGEST_PASSWORD" in message
    assert "DO NOT paste its value into chat" in message


def test_require_password_rejects_empty_string() -> None:
    # An empty-string env value must not be treated as "present" — that
    # would be an unauthenticatable but silently-substituted password.
    with pytest.raises(MissingCredentialError):
        require_password({"ARGUS_DB_INGEST_PASSWORD": ""}, "ARGUS_DB_INGEST_PASSWORD")


def test_require_password_returns_value_when_present() -> None:
    value = require_password({"ARGUS_DB_INGEST_PASSWORD": "s3cret"}, "ARGUS_DB_INGEST_PASSWORD")
    assert value == "s3cret"


@pytest.mark.parametrize("role", list(DbRole))
def test_connection_for_role_fails_closed_without_password(role: DbRole) -> None:
    config = ArgusConfig(values={}, sources=(), env={})
    with pytest.raises(MissingCredentialError) as exc_info:
        connection_for_role(config, role)
    assert PASSWORD_ENV_VARS[role] in str(exc_info.value)


@pytest.mark.parametrize("role", list(DbRole))
def test_connection_for_role_succeeds_with_password_from_env(role: DbRole) -> None:
    var_name = PASSWORD_ENV_VARS[role]
    config = ArgusConfig(values={}, sources=(), env={var_name: "disposable-test-password"})
    info = connection_for_role(config, role)
    assert info.password == "disposable-test-password"
    assert info.user == role.value  # default username derived from role, not a secret


def test_connection_for_admin_fails_closed_without_password() -> None:
    config = ArgusConfig(values={}, sources=(), env={})
    with pytest.raises(MissingCredentialError) as exc_info:
        connection_for_admin(config)
    assert ADMIN_PASSWORD_ENV_VAR in str(exc_info.value)


def test_connection_for_admin_succeeds_with_password_from_env() -> None:
    config = ArgusConfig(
        values={}, sources=(), env={ADMIN_PASSWORD_ENV_VAR: "disposable-admin-password"}
    )
    info = connection_for_admin(config)
    assert info.password == "disposable-admin-password"


def test_no_hardcoded_dev_only_password_fallback_exists() -> None:
    # Regression guard for the remediation: no module in the connection path
    # should contain a working fallback password literal.
    import inspect

    import argus.db.connection as connection_module

    source = inspect.getsource(connection_module)
    assert "dev_only" not in source
    assert "REDACTED_FORMER_DEV_PLACEHOLDER" not in source
