"""ORM model registry.

Importing ``argus.domain`` (which Python does automatically whenever any
``argus.domain.<module>`` submodule is imported, since the parent package
always initializes first) eagerly registers every table's SQLAlchemy
metadata. Without this, a process that imports only some domain modules
directly (e.g. a CLI command importing ``argus.domain.tokens`` but never
``argus.domain.token_winner_milestones``) can hit
``sqlalchemy.exc.NoReferencedTableError`` the moment a cross-table foreign
key (``archaeology_triggers.source_milestone_id`` ->
``token_winner_milestones.milestone_id``) is resolved lazily against an
incomplete ``Base.metadata`` -- a real defect this project already fixed
once for Alembic (``migrations/env.py``'s own explicit import block) but
had not yet fixed for every other process entry point.
"""

from __future__ import annotations

from . import (
    archaeology_runs as archaeology_runs,
)
from . import (
    archaeology_triggers as archaeology_triggers,
)
from . import (
    chain_events as chain_events,
)
from . import (
    clock_health as clock_health,
)
from . import (
    commitment as commitment,
)
from . import (
    early_buyers as early_buyers,
)
from . import (
    parse_attempts as parse_attempts,
)
from . import (
    provider_usage as provider_usage,
)
from . import (
    reference_asset_prices as reference_asset_prices,
)
from . import (
    swaps as swaps,
)
from . import (
    token_market_snapshots as token_market_snapshots,
)
from . import (
    token_mint_validations as token_mint_validations,
)
from . import (
    token_negative_controls as token_negative_controls,
)
from . import (
    token_winner_milestones as token_winner_milestones,
)
from . import (
    tokens as tokens,
)
from . import (
    wallet_discovery_events as wallet_discovery_events,
)
from . import (
    wallet_stream_state as wallet_stream_state,
)
from . import (
    wallets as wallets,
)
