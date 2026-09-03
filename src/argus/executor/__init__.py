"""Phase 6 (``argus-phase-6-001``): the hardened isolated executor's
software-only safety machinery, MASTER_SPEC.md sections 65-84.

This package builds ONLY the software/state-machine/gate/audit
infrastructure -- no real signing key is ever read, no wallet is ever
funded, no mainnet transaction is ever submitted, and no live arm file
is ever created or modified by this codebase. See each module's own
docstring for the exact MASTER_SPEC.md section/frozen acceptance row it
implements.
"""
