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


class ProviderResponseError(RuntimeError):
    """Base for a failure discovered while turning an already-received HTTP
    response into an adapter's typed result -- a well-formed
    application-level error, a malformed/unexpected shape, or any other
    "the response could not be turned into a valid result" outcome.
    Distinct from a transport-level failure (no response was ever
    received) and from an HTTP error status.

    Every such exception sets ``usage_status`` (either as a plain class
    attribute, for an exception type with one fixed outcome, or as an
    instance attribute set in ``__init__``, for one that can represent more
    than one outcome -- see ``HeliusRpcError``) so
    :func:`argus.providers.http.send_with_usage` records the precise
    terminal usage-accounting outcome for it (Phase 1 remediation round 2,
    finding #8) instead of a generic catch-all."""

    usage_status: str = "processing_error"


class ProviderContractError(ProviderResponseError):
    """A provider's response failed explicit contract validation --
    distinct from "unreachable" (network/connection failure) and from a
    well-formed application-level error response."""

    usage_status: str = "contract_error"


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
