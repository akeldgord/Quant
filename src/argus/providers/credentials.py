"""Required, non-defaulted provider credential resolution.

Mirrors ``argus.db.credentials``'s fail-closed pattern (MASTER_SPEC.md
SEC-005 / section 108) for provider API keys rather than DB passwords: no
value is ever hardcoded or silently substituted. If a required provider
credential is missing, this raises immediately with the exact
``LOCAL CREDENTIAL REQUIRED`` message format instead of proceeding with a
mocked/degraded live probe.
"""

from __future__ import annotations

from collections.abc import Mapping


class MissingProviderCredentialError(RuntimeError):
    """Raised instead of silently proceeding without a required provider
    credential. Callers must surface this as PARTIAL/NOT TESTED, never
    catch-and-substitute a mocked response while claiming live acceptance."""


def require_env_credential(env: Mapping[str, str], var_name: str) -> str:
    value = env.get(var_name)
    if not value:
        raise MissingProviderCredentialError(
            f"LOCAL CREDENTIAL REQUIRED:\n{var_name}\n"
            "Place it locally in your .env file (gitignored; see .env.example) "
            "before probing or connecting to this provider. DO NOT paste its "
            "value into chat. No fallback value exists -- this is intentional "
            "(MASTER_SPEC.md SEC-005 / section 108)."
        )
    return value
