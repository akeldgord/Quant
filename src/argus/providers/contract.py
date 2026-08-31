"""Shared response-contract validation helpers (MASTER_SPEC.md section 12;
Phase 1 remediation round 1, finding #6: "a top-level `dict` check is not
response-contract validation").

Every adapter validates a provider's *success* response shape explicitly
-- required keys, types, and numeric-string formats -- before returning it
to callers, and raises :class:`ProviderContractError` (never a bare
``KeyError``/``TypeError``) on anything malformed. Raw provider evidence
is still returned/preserved verbatim on success; validation is a gate, not
a transformation.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


class ProviderContractError(RuntimeError):
    """A provider's response failed explicit contract validation --
    distinct from "unreachable" (network/connection failure) and from a
    well-formed application-level error response."""


def require_dict(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderContractError(f"{context}: expected an object, got {value!r}")
    return value


def require_key(obj: dict[str, Any], key: str, *, context: str) -> Any:
    if key not in obj:
        raise ProviderContractError(f"{context}: missing required key {key!r} in {obj!r}")
    return obj[key]


def require_list(value: Any, *, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProviderContractError(f"{context}: expected a list, got {value!r}")
    return value


def require_str(value: Any, *, context: str) -> str:
    if not isinstance(value, str):
        raise ProviderContractError(f"{context}: expected a string, got {value!r}")
    return value


def require_numeric_string(value: Any, *, context: str) -> str:
    """Validates a provider's numeric-as-string field (the common shape
    for on-chain amounts/prices, which routinely exceed float/JSON-number
    safe precision)."""
    text = require_str(value, context=context)
    try:
        Decimal(text)
    except InvalidOperation as exc:
        raise ProviderContractError(f"{context}: expected a numeric string, got {text!r}") from exc
    return text
