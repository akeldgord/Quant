"""Postgres least-privilege role names (MASTER_SPEC.md section 72).

These are the only three application-facing database roles. Nothing in this
codebase should connect as a Postgres superuser except the migration runner
(``argus_admin`` / the Compose-provisioned superuser used purely for DDL).

- ``argus_ingest``   — writes canonical raw/derived data (chain_events, swaps,
                        provider_usage, ...). Must not have execution
                        permissions it doesn't need.
- ``argus_research`` — reads broadly for research/scoring; must NOT be able to
                        rewrite confirmed execution history.
- ``argus_executor`` — the isolated live-execution process; must NOT be able
                        to rewrite historical wallet scores or research data.
"""

from __future__ import annotations

import enum


class DbRole(enum.StrEnum):
    INGEST = "argus_ingest"
    RESEARCH = "argus_research"
    EXECUTOR = "argus_executor"
