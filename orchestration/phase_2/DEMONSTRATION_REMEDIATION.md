# Phase 2 remediation: corrected real historical-token demonstration

Orchestrator instruction `argus-phase-2-remediation-001`, required remediation
item 3's explicit requirement: "Re-run the real pump.fun fixture: the
signer/dev-buy may remain a tagged buyer; the known bonding-curve reserve PDA
must not be inserted as a buyer wallet or discovery candidate. Update the
demonstration honestly." This is a **new, additional** file, not an edit of
`orchestration/phase_2/DEMONSTRATION.md` -- that file is left unmodified as
immutable historical record of what the pre-remediation build actually did
when run (including its own honestly-disclosed known limitation #2, which
this file's re-run now closes). Run against the same real Postgres 16 dev
database, the same real committed evidence file, and the exact same `argus`
CLI commands as before, at migration head `0009`, after all of P2-R1 through
P2-R8.

## Token and evidence (unchanged from the original demonstration)

Same token: `5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump`. Same real,
committed creation-transaction evidence:
`orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json`. The
mint's rows were fully cleaned from the dev database before this re-run
(`select token_id from tokens where mint = '5dNYcC...' ` returned 0 rows
immediately before the first command below), so this is a clean, from-empty
re-run -- not a replay against pre-existing rows.

## Commands run (in order, this session)

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
  --known-gaps "Only the token's own creation transaction is available in this sandbox; no live getSignaturesForAddress/getTransaction scan was performed." \
  --completeness-statement "PARTIAL: exactly one transaction (the creation transaction) searched for early buyers; this is not a full address-history walk." \
  --source-provider-set "committed_evidence_replay: orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json"

argus discover watch-replay \
  --mint 5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump \
  --snapshots-file orchestration/phase_2/evidence/replay_market_snapshots_demo.json

argus discover run-pending-trigger \
  --mint 5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump \
  --evidence-file orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json \
  --known-gaps "Only the token's own creation transaction is available in this sandbox; no live getSignaturesForAddress/getTransaction scan was performed." \
  --completeness-statement "PARTIAL: exactly one transaction (the creation transaction) searched for early buyers; this is not a full address-history walk." \
  --source-provider-set "committed_evidence_replay: orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json" \
  --partial
```

Note the fourth command: unlike the original demonstration's manual
`argus discover archaeology-run --trigger-id <the trigger_id printed by
watch-replay>`, this is P2-R5's automatic trigger consumer
(`argus discover run-pending-trigger`) -- no trigger ID is read from one
command's output and passed into another's input anywhere in this re-run.

## Results (queried directly from Postgres after all four commands)

**Mint validation** (`token_mint_validations`): `VALID`, source
`committed_transaction_token_balance_evidence`, decimals `6`,
`chain_time=2024-09-29 19:12:25+00:00` (P2-R8: derived from the evidence's own
`blockTime`, no longer `None`), `commitment=None` (honest: this evidence kind
carries no live commitment level to persist).

**Archaeology run 1** (`HISTORICAL_WINNER`, manual evidence-file command):
`run_id=763411df-a0ae-49a1-862f-0d37231ec342` `status=PARTIAL`
`early_buyers_recovered=1` `wallets_discovered=1`
`unresolved_ownership_count=1`.

**Early buyers recovered** (`early_buyers`, queried directly, joined through
`wallets`):

| wallet | amount_raw | decimals | sequence |
|---|---|---|---|
| `6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx` | 34612903225806 | 6 | 1 |

Exactly **one** row -- the transaction's fee payer and sole signer (the
token creator's own genuine dev-buy). This is the direct, queried proof of
the P2-R3 fix: the original demonstration's second row,
`CQrqvWERJtEjw2rCCQV6EqfM6V6jzTuKjhJjKNFmGB7r` (the pump.fun bonding-curve
program's own reserve PDA -- account index 3 in the creation transaction's
"buy" instruction, never a signer), is **not present**. It was not silently
dropped: `unresolved_ownership_count=1` on the run result is the honest,
explicit count of the one raw candidate whose ownership could not be
resolved to a signer wallet (`OWNERSHIP_UNRESOLVED_NON_SIGNER`,
`src/argus/wallets/early_buyer_extraction.py`) and was therefore excluded
from wallet/discovery/buyer promotion -- its raw evidence is preserved
inside `extract_early_buyers()`'s own return value (never erased), only its
promotion into a `wallets`/`early_buyers`/discovery-event row is withheld.

**REPLAY winner milestone** (`token_winner_milestones`, from the same four
REPLAY snapshots as before, now MEDIUM-confidence per P2-R4 --
`replay_market_snapshots_demo.json`'s own `_disclosure` field documents this
change): category `MAJOR_WINNER`, `multiple_x=12.000000`, `milestone_id=
eadbde34-e8c3-409e-af7e-f20eb1f4907a`. `trigger_id=
bbfcfb7e-781d-420b-9056-18a28a348207` created automatically alongside it.

**Automatic trigger consumption** (P2-R5, `archaeology_triggers`, queried
directly): the `PROSPECTIVE_WINNER` trigger created by `watch-replay` has
`source_milestone_id` set (linked to the milestone above) and
`consumed_at` **set** after `run-pending-trigger` -- consumed automatically,
by the token's own pending-trigger lookup, with no trigger ID ever typed or
copied between commands in this re-run.

**Archaeology run 2** (`PROSPECTIVE_WINNER`, automatic consumer):
`run_id=9bc1e7b6-cee7-4af8-93d4-4c522cfaa977` `status=PARTIAL`
`early_buyers_recovered=0` (the one genuine buyer was already recorded by
run 1 -- proves retry/duplicate-trigger idempotency, unchanged from the
original demonstration's own finding) `wallets_discovered=1`
`unresolved_ownership_count=1` (the same reserve PDA candidate is correctly
excluded again on this run too, not merely once).

**Wallet discovery provenance** (`wallet_discovery_events`, queried
directly): exactly one wallet
(`6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx`) with two discovery-event
rows, one per channel (`HISTORICAL_WINNER_ARCHAEOLOGY`,
`PROSPECTIVE_WINNER_ARCHAEOLOGY`) -- the reserve PDA has **zero** discovery-
event rows under either channel, confirmed by the same direct query
returning only one distinct `wallet_address`.

## What changed versus the original demonstration, and why

The original demonstration (`DEMONSTRATION.md`) recorded **two** early-buyer
rows and disclosed, as known limitation #2, that the second row was "very
likely not a human trader" -- the bonding-curve reserve PDA, included only
because the pre-remediation extractor had no evidence-grounded way to
distinguish a program-controlled account from a genuine wallet. P2-R3 adds
exactly that distinction (transaction-signer-set membership,
`_transaction_signers()`/`OWNERSHIP_SIGNER_WALLET`/
`OWNERSHIP_UNRESOLVED_NON_SIGNER` in
`src/argus/wallets/early_buyer_extraction.py`), so this re-run's `early_buyers`
table now contains only the one wallet that was always the honestly-labeled
"genuine signer/dev-buy" in the original disclosure -- the previously-included
reserve PDA is excluded, honestly counted (`unresolved_ownership_count`),
and its raw evidence is still preserved by the pure extraction function,
never silently discarded from the module's own output.

## Known limitations (unchanged from the original demonstration, still honest)

1. **Early-buyer completeness.** Only the token's own creation transaction
   is available to this sandbox's evidence-file path in this specific
   re-run (both archaeology runs above are `PARTIAL` for exactly this
   reason). P2-R2 adds a real, tested, CLI-wired live acquisition path
   (`argus discover acquire-and-run-archaeology`,
   `src/argus/tokens/historical_acquisition.py`) capable of walking an
   address's full signature history via Helius `getSignaturesForAddress`
   pagination -- but exercising it against this specific token still
   requires a live `HELIUS_API_KEY`, which this sandbox does not have
   configured (confirmed via the same exact section-108 `LOCAL CREDENTIAL
   REQUIRED` notice `argus ingest run`'s live path already produces; see
   `orchestration/checkpoints/phase_2_remediation.md` section C). This
   re-run therefore still uses the single-transaction evidence-file path,
   honestly labeled `PARTIAL` throughout, exactly as before.
2. **REPLAY winner category is not evidence of this token's real trading
   outcome.** Unchanged from the original demonstration: the `MAJOR_WINNER`
   milestone exists solely to exercise the watcher's detection/persistence
   and (this re-run) automatic-trigger-consumption code paths against a
   synthetic, disclosed, MEDIUM-confidence-labeled 12x price series; it makes
   no claim about this token's real on-chain trading outcome.
