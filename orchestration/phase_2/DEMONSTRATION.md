# Phase 2 real historical-token demonstration

Orchestrator instruction `argus-phase-2-001`, required-implementation item 8
and the instruction's demonstration requirement. Run against real Postgres
16 via the actual `argus` CLI (`argus tokens import-bootstrap`,
`argus discover archaeology-run`, `argus discover watch-replay`) at
migration head `0008`, using the `argus_ingest` DB role exactly as
production code paths do (`_phase2_engine_and_sessionmaker()`).

## Token

`5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump` -- the same real pump.fun
token verified in the Phase 1.5 feasibility spike
(`orchestration/checkpoints/phase_1_5.md` section B), reused here because
its provenance was already independently established: a real creation
transaction (slot `292743221`, 2024-09-29T19:52:25Z) preserved verbatim at
`orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json`,
sourced from `0xjeffro/tx-parser` (commit
`475b1ebff79a2f41ec966919fdefa01f11f6c5d7`, path
`solana/data/pumpfun_create_0.json`, MPL-2.0; full citation in
`orchestration/phase_1_5/evidence/PROVENANCE.md`).

## Data source and honesty disclosure

Two distinct evidence classes are used, and are never conflated in the
data recorded:

1. **Real evidence** -- the token's own genuine, committed creation
   transaction. Used for mint validation and both early-buyer archaeology
   runs below. Every row produced from it is recorded with
   `evidence_reference = "orchestration/phase_1_5/evidence/raw/
   token_00_pumpfun_create.json"` and, for mint validation,
   `validation_source = "committed_transaction_token_balance_evidence"`
   (never the live-`getAccountInfo` label) since no live Helius/RPC access
   exists in this sandbox.
2. **REPLAY / synthetic evidence** -- four fabricated market-snapshot
   observations
   (`orchestration/phase_2/evidence/replay_market_snapshots_demo.json`),
   used only to demonstrate the prospective winner-milestone watcher's
   real detection/persistence code path end-to-end. This is explicitly
   allowed by the orchestrator instruction ("The watcher may be
   demonstrated with deterministic REPLAY data when live provider access
   remains environmentally unavailable ... must be labeled as replay") and
   every one of these rows carries `source = "replay_synthetic_demo"` in
   `token_market_snapshots`, a value that can never appear from any real
   provider adapter. **These four price/liquidity points are not a
   recovered price history for this token** -- no live market-data
   provider (Helius, DexScreener, GeckoTerminal, Jupiter) or historical
   price archive is reachable in this sandbox.

## Commands run (in order)

```
argus tokens import-bootstrap \
  --mint 5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump \
  --evidence-file orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json \
  --evidence-kind token_balance

argus discover archaeology-run \
  --mint 5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump \
  --run-type HISTORICAL_WINNER \
  --evidence-file orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json \
  --partial \
  --known-gaps "..." --completeness-statement "..." --source-provider-set "..."

argus discover watch-replay \
  --mint 5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump \
  --snapshots-file orchestration/phase_2/evidence/replay_market_snapshots_demo.json

argus discover archaeology-run \
  --mint 5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump \
  --run-type PROSPECTIVE_WINNER \
  --evidence-file orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json \
  --trigger-id <the trigger_id printed by watch-replay> \
  --partial \
  --known-gaps "..." --completeness-statement "..." --source-provider-set "..."
```

Full option text (the required honest disclosures for each run) is in the
git history of this file's authoring commit and in `AGENT_HANDOFF.md`; it
is elided here only for brevity.

## Results (queried directly from Postgres after all four commands)

**Mint validation** (`token_mint_validations`): `VALID`, source
`committed_transaction_token_balance_evidence`, decimals `6`, evidence
`.../token_00_pumpfun_create.json`. Never claims live `getAccountInfo`
validation.

**Market snapshots** (`token_market_snapshots`, all `source =
replay_synthetic_demo`):

| observed_at | lifecycle_stage | price_usd | liquidity_usd |
|---|---|---|---|
| 2024-09-29T19:52:26Z | TOKEN_CREATION | NULL | 0 |
| 2024-09-29T19:55:00Z | BONDING_CURVE | 0.00003 | 5000 |
| 2024-09-30T06:00:00Z | BONDING_CURVE | 0.00015 | 18000 |
| 2024-09-30T12:00:00Z | LAUNCHPAD_TRADING | 0.00036 | 40000 |

**Winner milestone** (`token_winner_milestones`, from the REPLAY
snapshots only): category `MAJOR_WINNER`, `multiple_x = 12.000000`,
baseline price `0.00003` (the 19:55:00 snapshot -- **not** the 19:52:26
zero-liquidity launch-instant snapshot), peak price `0.00036`, reason code
`ZERO_LIQUIDITY_SNAPSHOTS_EXCLUDED_FROM_BASELINE`. This confirms
MASTER_SPEC.md section 32's baseline rule fired correctly: the untradeable
launch instant was correctly excluded rather than used to inflate the
multiple.

**Archaeology trigger** (`archaeology_triggers`): one `PROSPECTIVE_WINNER`
row, `source_milestone_id` set (linked to the milestone above),
`consumed_at` set (consumed by the second archaeology run below) --
demonstrates the automatic archaeology-trigger requirement end-to-end, not
just its schema.

**Archaeology runs** (`archaeology_runs`): two rows, both `PARTIAL` (a
caller-asserted disclosure, since only the creation transaction's own
evidence is available -- never inferred from the result count alone):
one `HISTORICAL_WINNER`, one `PROSPECTIVE_WINNER` consuming the trigger
above.

**Early buyers recovered** (`early_buyers`, from the real creation-
transaction evidence, identical across both runs -- the second run
recovered 0 *new* rows because both wallets were already recorded, proving
retry/duplicate-trigger idempotency rather than re-deriving different
data):

| wallet | amount_raw | decimals | sequence |
|---|---|---|---|
| `6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx` | 34612903225806 | 6 | 1 |
| `CQrqvWERJtEjw2rCCQV6EqfM6V6jzTuKjhJjKNFmGB7r` | 965387096774194 | 6 | 2 |

**Wallet discovery provenance** (`wallet_discovery_events`): both wallets
above have two independent discovery-event rows each -- one per channel
(`HISTORICAL_WINNER_ARCHAEOLOGY`, `PROSPECTIVE_WINNER_ARCHAEOLOGY`) -- even
though the underlying `early_buyers` row was created only once. This is
the intended MASTER_SPEC.md section 28/29 behavior: provenance is
per-discovery-channel, while the economic fact ("this wallet received this
mint at this slot") is recorded exactly once.

## Known limitations (honest disclosure, not resolved by this demonstration)

1. **Early-buyer completeness.** Only the token's own creation transaction
   is available in this sandbox (no live `getSignaturesForAddress`/
   `getTransaction` scan, no indexed dataset). Both archaeology runs are
   marked `PARTIAL` for exactly this reason -- this matches the Phase 1.5
   feasibility-spike finding for this same token verbatim.
2. **One of the two "early buyer" candidates is very likely not a human
   trader.** Cross-referencing the creation transaction's own instruction
   accounts (the final `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`
   "buy" instruction: accounts `[global, feeRecipient, mint, bondingCurve,
   associatedBondingCurve, associatedUser, user, ...]`) against its
   `postTokenBalances` shows that wallet
   `CQrqvWERJtEjw2rCCQV6EqfM6V6jzTuKjhJjKNFmGB7r` (holding 965M of the
   ~1B token supply -- the majority) is account index 3, the bonding
   curve's own program-derived state account, i.e. the **program's own
   reserve**, not a trader wallet. Wallet
   `6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx` (holding 34.6M) is
   account index 0, the transaction's fee payer and sole signer -- the
   token creator's own genuine dev-buy, consistent with the Phase 1.5
   finding. `argus.wallets.early_buyer_extraction` deliberately never
   excludes a wallet from its result (MASTER_SPEC.md section 33's explicit
   "tag, do not delete" rule, and its own docstring/tests, e.g. required
   test P2-T5, depend on this), and the raw
   `preTokenBalances`/`postTokenBalances` delta technique has no way to
   distinguish a program-controlled reserve account from a genuine trader
   wallet on its own -- doing so would require either transaction-signer-
   set membership or program-account classification, neither of which
   this module currently consults. This is disclosed here rather than
   silently reported as "2 real human early buyers," and is left as a
   known extraction-methodology limitation for a later phase rather than
   an undisclosed defect in this one. `--deployer-wallet` was not passed
   on either archaeology run in this demonstration, so neither
   `early_buyers` row is DB-tagged `possible_deployer` -- the creator
   identification above is evidence-based narrative only, not a stored
   tag, in this specific run.
3. **REPLAY winner category is not evidence of this token's real trading
   outcome.** The `MAJOR_WINNER` milestone above exists solely to exercise
   the watcher's detection/persistence code path against a synthetic
   12x price series chosen for that purpose; it makes no claim about
   whether this token ever actually reached any winner category on-chain.
