"""Typed unsellable/capacity outcomes for shadow quote probes
(MASTER_SPEC.md section 48: UNSELLABLE IS A REAL OUTCOME).

A provider adapter used by ``argus.shadow.quote_jobs`` raises one of
these to report a specific, real, never-dropped negative outcome rather
than an opaque generic exception -- ``QUOTE_FAILED`` is reserved for a
genuinely unclassified failure, never a catch-all for these five cases.
"""

from __future__ import annotations


class ShadowQuoteError(Exception):
    """Base for every typed shadow-quote failure."""


class NoRouteError(ShadowQuoteError):
    pass


class InsufficientLiquidityError(ShadowQuoteError):
    pass


class TokenRestrictedError(ShadowQuoteError):
    pass


class ProviderCapacityMissError(ShadowQuoteError):
    """Provider capacity (rate limit / budget) prevented this probe from
    even being attempted -- an explicit missing observation (section 46:
    "Provider capacity may prevent every probe"), never a fabricated
    zero return."""
