# Phase 3 sample report

Orchestrator instruction `argus-phase-3-001`, "Required Phase 3 sample
report." Result: **`PHASE_3_CANDIDATE_SAMPLE_BLOCKED`** -- exactly 1 genuine
candidate wallet exists in this sandbox from already-authorized authentic
evidence, not 5. Per the instruction's own explicit fallback ("If fewer
than five genuine candidates can be established with the currently
authorized free evidence paths, output exactly
`PHASE_3_CANDIDATE_SAMPLE_BLOCKED` in the checkpoint, report the actual
count and missing evidence, and STOP for orchestrator review rather than
inventing data or using a paid source"), this report documents the actual
count and the missing evidence rather than fabricating wallet history.

## Why only 1 genuine candidate wallet exists

This sandbox has exactly one independently-verified real evidence source
across the whole project (unchanged since Phase 1.5/2): the creation
transaction of pump.fun token
`5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump`
(`orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json`, real
provenance documented in `orchestration/phase_1_5/evidence/PROVENANCE.md`).
No live Helius/Solana RPC, no indexed historical dataset, and no other
authentic transaction evidence is reachable in this sandbox (unchanged
environmental limitation, `LIVE_HELIUS_RPC_VALIDATION =
DEFERRED_ENVIRONMENTAL_CHECK`, per `docs/BUILD_STATE.md`).

Reproducing this project's own established Phase 2 demonstration
(`orchestration/phase_2/DEMONSTRATION.md`) end-to-end via the real
production CLI (`argus tokens import-bootstrap`, `argus discover
archaeology-run --run-type HISTORICAL_WINNER`) against that one real
transaction, using the `argus_ingest` role exactly as production code
does:

```
argus tokens import-bootstrap --mint 5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump \
  --evidence-file orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json \
  --evidence-kind token_balance
  -> status=VALID source=committed_transaction_token_balance_evidence decimals=6 mint_validated=True

argus discover archaeology-run --mint 5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump \
  --run-type HISTORICAL_WINNER \
  --evidence-file orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json \
  --partial --known-gaps "..." --completeness-statement "..." --source-provider-set "..."
  -> status=PARTIAL early_buyers_recovered=1 wallets_discovered=1 unresolved_ownership_count=1
```

produces exactly **1** discovered wallet:
`6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx` -- the transaction's own
fee payer/signer, i.e. the token creator's genuine bundled dev-buy
(`sequence_number=1`, `amount_raw=34612903225806`, decimals `6`). This is
one fewer than the two wallets Phase 2's own original demonstration
recorded: the second candidate from that run
(`CQrqvWERJtEjw2rCCQV6EqfM6V6jzTuKjhJjKNFmGB7r`) was the pump.fun bonding
curve's own program-derived reserve account, not a trader -- disclosed as
a known limitation in `DEMONSTRATION.md` at the time, and correctly
excluded automatically since Phase 2 remediation round 1 (P2-R3,
evidence-grounded `ownership_classification` via transaction-signer-set
membership) without needing any new Phase 3 code. `wallets_discovered=1`,
`unresolved_ownership_count=1` above is that same correct exclusion,
verified directly against this sandbox's real code, not merely cited from
an earlier round's report.

## The single genuine candidate's Phase 3 reconstruction/scoring result

Run via the real production CLI (`argus wallets reconstruct-and-score`,
`argus.wallets.qualification_service.reconstruct_and_score_wallet`, the
same `argus_ingest`-role path production code uses):

```
argus wallets reconstruct-and-score --wallet 6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx \
  --evidence-source STREAM_FORWARD_ONLY
  -> wallet_id=93cc056c-8af1-4c32-9090-e04b91784deb history_completeness=UNKNOWN
     positions_reconstructed=0 positions_written=0 positions_unchanged=0
     positions_skipped_untracked_token=0
     qualification_score=50.00 descriptive_score=50.00
     eligible_for_qualification=False score_written=True
     tier_transition: -> DISCOVERED (first tier assignment: no prior score exists)
```

| Field | Value |
|---|---|
| usable trades/positions | **0** -- Phase 2's real-evidence extraction recovers this wallet's economic fact (it received tokens in the creation transaction) via a raw balance-delta technique that writes directly to `early_buyers`, never through the Phase 1 `swaps` table; no live ingestion stream or historical acquisition walk has ever run against this wallet's own transaction history in this sandbox, so `swaps` (queried directly: `SELECT COUNT(*) FROM swaps` → `0`) has zero rows for it and `reconstruct_positions_for_wallet` correctly reconstructs zero positions from zero evidence |
| history completeness and reason | `UNKNOWN` -- "zero swaps rows found for this wallet -- genuinely missing evidence, never assumed to mean zero on-chain activity" (`assess_wallet_history`'s own no-evidence path; `STREAM_FORWARD_ONLY` was used since no `LIVE_ACQUISITION_WALK` with a real terminal status exists for this wallet) |
| discovery-trigger token(s) | `5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump` (`wallet_discovery_events.trigger_token_id`, channel `HISTORICAL_WINNER_ARCHAEOLOGY`) |
| excluded observations | none -- zero positions exist to exclude; the discovery-contamination firewall has no positions to act on for this wallet (correctly a no-op, not a false claim of exclusion) |
| descriptive score | `50.00` (the neutral prior for every one of the 8 frozen component weights, since none is computable from zero positions -- `_weighted_score` imputing `_NEUTRAL_PRIOR=50` throughout, never fabricated positive evidence) |
| qualification score | `50.00` (identical, for the identical reason; `eligible_for_qualification=False`) |
| selection skill | not computable (`None`) -- no closed positions |
| entry skill | not computable (`None`) -- no `early_buyer_sequence_number` evidence was cross-referenced for a *position* (the `early_buyers` row exists, but reconstructing 0 positions means `PositionForScoring` was never built for this token) |
| exit skill | not computable (`None`) |
| consistency | not computable (`None`) -- `stats.hit_rate is None` with 0 closed positions |
| risk metrics | not computable (`max_drawdown=None`, `lottery_dominated=False` on an empty set) |
| penalties/flags | none applied (`insider_penalty=0`, `lottery_dominance_penalty=0`, `data_quality_penalty=0`, `cluster_uncertainty_penalty=0`, `predation_penalty=0`) -- no evidence to penalize |
| resulting tier and confidence | `DISCOVERED` (first tier assignment; `determine_tier_transition`'s own `current_tier is None` branch), `confidence=LOW` (more than 2 of the 8 required components are `None`) |

This is the honest, correct Phase 3 output for a wallet with real
discovery provenance but zero real trading-history evidence -- not a
defect in the Phase 3 code (independently verified against 15 dedicated
unit/integration tests plus the full 721-test repository suite, see
`orchestration/checkpoints/phase_3.md`), and not evidence that Phase 3's
qualification pipeline itself is broken. It falls enormously short of the
frozen V1 sample-size gate (≥20 usable closed positions, ≥10 distinct
tokens, `history_completeness` not `LOW`/`UNKNOWN`) by every dimension at
once.

## Missing evidence required to reach 5 genuine candidates

To produce even one genuine wallet with `history_completeness` other than
`UNKNOWN`, at minimum this sandbox would need:

1. A live Solana RPC/WebSocket credential (`HELIUS_API_KEY` or
   equivalent) or a reachable indexed historical dataset, to run
   `argus discover acquire-and-run-archaeology`/live streaming against a
   real wallet's own transaction history and populate `swaps` with real
   evidence (currently `DEFERRED_ENVIRONMENTAL_CHECK`, unchanged since
   Phase 1/Phase 2).
2. Several such wallets, each with at least 20 real closed positions
   across at least 10 distinct tokens, to clear the frozen V1 sample-size
   gate at all -- let alone 5 of them, as this report requires.

Neither exists in this sandbox today. Per the instruction's own explicit
rule ("A poor score, low completeness, or zero A/S wallets is a valid
Phase 3 result. Do not retune the score or eligibility rules to force
attractive candidates."), this is reported as-is rather than worked
around by loosening the frozen thresholds, reusing Phase 1.5's separate
14-transaction candidate wallet (`JAMESC37CTVoFEt7TAEcqBjdjAfAWZiPR1YdWotAFjeQ`,
which has no `wallets`/`wallet_discovery_events` row at all -- it was
never run through Phase 2 discovery, so it is not an "already-discovered
wallet" Phase 3's own service scope requires), or fabricating synthetic
wallet history and passing it off as a genuine candidate.
