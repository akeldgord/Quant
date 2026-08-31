================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity/scope and exact commit

PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Phase 1.5 historical-data feasibility spike, per orchestrator
  instruction `argus-phase-1-5-001` (`AUTHORIZED_ACTION:
  EXECUTE_PHASE_1_5_HISTORICAL_DATA_FEASIBILITY_SPIKE_ONLY`,
  `AUTHORIZED_PHASE: 1.5`, `APPROVES_PHASE: 1`). Phase 1 is ORCHESTRATOR
  APPROVED per this instruction at TARGET_COMMIT
  `2fbc566af74832bc6523648f60ba8cb60d98eb31`
  (`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`). This checkpoint
  covers only the Phase 1.5 spike; it does not approve Phase 1.5 itself
  (only the orchestrator may do that) and does not begin Phase 2.
STATUS: HISTORICAL_DATA_PATH_PASS_WITH_LIMITATIONS
UTC_TIMESTAMP: 2026-08-31T21:28:18Z
GIT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
TARGET_COMMIT: 2fbc566af74832bc6523648f60ba8cb60d98eb31
AUTHORIZED_PHASE: 1.5
APPROVES_PHASE: NONE

B. Verified token and wallet inputs (Section 2 of the required contract)

Both required inputs were established automatically from already-reachable
free/public sources -- `BOOTSTRAP_TOKEN_INPUT_REQUIRED` was not needed.
Full citation detail (repository, exact commit, file path, license,
signature, slot) is in `orchestration/phase_1_5/evidence/PROVENANCE.md`;
raw evidence bytes are committed verbatim in
`orchestration/phase_1_5/evidence/raw/`.

- **Verified historical token:** `5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump`
  -- a real pump.fun token whose own creation transaction (slot
  `292743221`, 2024-09-29) is preserved as real evidence, sourced from
  `0xjeffro/tx-parser` (commit `475b1ebff79a2f41ec966919fdefa01f11f6c5d7`,
  path `solana/data/pumpfun_create_0.json`, MPL-2.0). Already reused by
  this project for `real_mainnet_sol_to_token_swap` (round 2), so this
  repository's provenance/license reasoning was already established.
- **Verified candidate wallet:** `JAMESC37CTVoFEt7TAEcqBjdjAfAWZiPR1YdWotAFjeQ`
  -- 14 real transactions spanning openbook_v2/solend/lulo/meteora_dlmm
  across slots `280407888`-`357908000` (2024-07-29 to 2025-08-04, ~1
  year), sourced from `quellen-sol/ingestooor` (commit
  `74e2039ec8dbc61bc5df1e08540ec5a3f3cd991e`, GPL-3.0 -- the same
  upstream repository/commit already reused for
  `real_mainnet_orca_close_position_multi_account` in round 6, so the
  GPL-3.0 "reused as one immutable verbatim data file, not linked code"
  compatibility decision already stands and is not re-litigated here).

Discovery method: `mcp__github__` API tools are session-scoped to
`akeldgord/quant` only and GitHub's public search API is rejected by
this session's proxy ("sessions are bound to their configured
repositories"); plain `git clone`/raw-content fetches against arbitrary
public GitHub repositories are unrestricted and confirmed working
(unchanged from every prior round). With no open-ended repository search
available, discovery was limited to the repositories already named/used
in this project's own `SEARCH_LOG.md`. Their full raw-transaction test
corpora (156 files in `ingestooor`, 27 in `tx-parser`) were parsed and
cross-indexed by fee-payer wallet and token mint to find genuine
multi-transaction overlaps -- see section H for the full method and its
limits.

C. Test A -- Early-buyer reconstruction

- **provider/source:** offline, GitHub-embedded real transaction
  (`0xjeffro/tx-parser`, see section B); no live RPC/indexer query was
  possible (see section M).
- **venue:** pump.fun (Solana bonding-curve launch program).
- **time range:** a single instant -- the token's creation transaction
  itself, 2024-09-29T19:52:25Z (blockTime `1727637145`).
- **transactions inspected:** 1 (the creation transaction).
- **buyers recovered:** 1 -- the token creator's own initial dev-buy,
  bundled into the same creation transaction (`postTokenBalances` shows
  account index 6, owner `6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx`
  -- the same address as the transaction's fee payer/signer -- receiving
  `34612903.225806` of the newly-minted token in the same instruction
  that creates it). Independently verified: `argus.parsing.generic_parser`
  classifies this transaction `SWAP_SIMPLE` with a positive token delta
  for that wallet (`tests/phase_1_5/test_historical_feasibility.py::
  test_token_creator_initial_buy_is_a_real_recoverable_early_buyer_event`).
- **earliest recovered activity:** the creation transaction itself (no
  earlier activity exists by definition for a token's own genesis).
- **known gaps:** every subsequent buyer beyond the creator's own bundled
  dev-buy is unrecoverable from this sandbox. Discovering them requires
  either a live RPC `getSignaturesForAddress`/`getTransaction` scan
  against the mint's associated bonding-curve/pool accounts, or an
  indexed dataset (e.g. a BigQuery Solana public dataset query) -- both
  are blocked in this specific sandbox (see section M); no GitHub-
  embedded dataset of a single token's full buyer history was found or
  is expected to exist (upstream test-fixture repositories capture
  isolated illustrative transactions for parser-code-path coverage, not
  per-token trading history archives -- confirmed by direct inspection:
  no two files in either searched repository's data corpus share a
  non-major token mint; see section H).
- **estimated completeness:** qualitative, not a fabricated percentage --
  severely incomplete. Exactly 1 of an unknown, likely much larger,
  total early-buyer cohort is recovered. This reflects a hard data-
  acquisition ceiling in this sandbox, not a parser or methodology
  limitation: the one buyer that *is* present was correctly identified.

D. Test B -- Candidate-wallet historical reconstruction

Reconstructed via `argus.parsing.generic_parser.parse_transaction`/
`compute_account_level_deltas` (the existing Phase 1 parser, unmodified)
against the 14 real transactions in section B. Full per-transaction
results: `orchestration/phase_1_5/evidence/PROVENANCE.md` and
`orchestration/phase_1_5/evidence/analysis_results.json`.

- **source(s) queried/read:** the 14 committed raw transaction files
  (offline; no live query).
- **time range actually observed:** slot `280407888` to `357908000`
  (2024-07-29T20:33:43Z to 2025-08-04T05:19:26Z, ~370 days) -- note this
  is the range *spanned by the 14 available transactions*, not a claim
  that the wallet's full signature history over that period was
  enumerated (it was not; see known gaps below).
- **counts by major reconstructed event type** (parser classification of
  the 14 transactions): `TRANSFER_IN` 2, `TRANSFER_OUT` 5, `SWAP_SIMPLE`
  1, `UNKNOWN` 6.
- **which required history dimensions are complete, partial,
  unavailable, or ambiguous:**
  - *wallet-level signatures* -- PARTIAL: 14 real, distinct signatures
    recovered and verified (`test_candidate_wallet_history_spans_
    multiple_required_dimensions`), but this is 14 of an unknown total
    signature count for this wallet (no `getSignaturesForAddress`
    enumeration was possible; these 14 are exactly the transactions this
    upstream repository happened to embed as parser test fixtures, not
    a complete or even randomly-sampled slice of the wallet's history).
  - *token-account activity* -- COMPLETE for the 14 available
    transactions: every token-account balance change present in each
    transaction was captured by `compute_account_level_deltas`.
  - *swaps* -- AMBIGUOUS/PARTIAL: only 1 of 14 classifies `SWAP_SIMPLE`
    (a Solend `withdraw_all`, which is balance-delta-shaped like a swap
    but is not semantically a DEX trade -- a known, disclosed limitation
    of a purely balance-delta parser with no protocol-instruction
    awareness, already documented in `generic_parser.py`'s own
    module docstring).
  - *transfers* -- COMPLETE for the 14 available transactions (7 of 14
    classify as a directional transfer).
  - *position events* -- PARTIAL/AMBIGUOUS: the wallet's actual activity
    is overwhelmingly lending/yield-position management (Solend
    deposit/borrow/repay/withdraw, Lulo boosted-vault deposit/withdraw/
    claim, Meteora DLMM deposit/claim/withdraw), but `generic_parser` has
    no dedicated position-lifecycle classification distinct from
    `TRANSFER_IN`/`OUT`/`UNKNOWN` -- it correctly computes the balance
    deltas (Test C confirms this) but cannot semantically label "this is
    a lending-position deposit" versus "this is a plain transfer". This
    is a genuine, concrete parser-completeness gap, not a data
    availability gap.
  - *ambiguous events* -- 6 of 14 (43%) classify `UNKNOWN` -- multi-leg
    position transactions (new-obligation-account deposits, DLMM
    liquidity claims/withdrawals) whose balance-delta shape does not fit
    any of the parser's 6 confident classification branches. Correctly
    preserved as `UNKNOWN` (never silently guessed), per the parser's
    documented fail-closed design -- but this is a high rate on real,
    diverse wallet activity and should be tracked as a concrete Phase 2
    consideration, not smoothed over.
- **known gaps:** no full signature enumeration; only the 14 transactions
  already embedded in the source repository's own test suite are
  available. Real wallet history reconstruction at any meaningful scale
  requires live RPC signature enumeration, which is blocked here.

E. Test C -- Cross-validation

**28 concrete historical interpretations validated against raw
transaction evidence** (exceeds the required minimum of 20; not achieved
by decomposing any single record into multiple sub-claims -- one real,
distinct transaction, each with its own real signature, is exactly one
interpretation: "this wallet's net raw balance delta(s) in this specific
real transaction equal X, classified as Y").

Method (`scripts/phase_1_5_feasibility.py`,
`tests/phase_1_5/test_historical_feasibility.py`): for each of the 28
real transactions (the token creation transaction, the 14 candidate-
wallet transactions, and 13 supplementary transactions from a second
real wallet -- `qUeL7JzC52V1DvvPkqnMd74QjThWtSJY5G1PkKv1ur7`, same
upstream repo/commit, used only to clear the required interpretation
count honestly, never claimed as the Test B candidate wallet), an
independent, from-scratch recomputation of the tracked wallet's net raw
SOL/token deltas was written directly against
`meta.preBalances`/`postBalances`/`preTokenBalances`/`postTokenBalances`
-- calling no `argus.parsing` code -- and compared against
`compute_account_level_deltas()`'s actual output for the same raw
transaction.

- **Total interpretations checked:** 28.
- **Agreements:** 28. **Disagreements:** 0.
- Reproducible via `uv run python scripts/phase_1_5_feasibility.py` or
  `uv run pytest tests/phase_1_5/ -v`
  (`test_independent_recomputation_agrees_with_the_parser_for_every_
  transaction` asserts the empty-disagreement-list directly).
- This proves the parser's core balance-delta arithmetic is correct
  against real, previously-unseen transaction shapes across 6 different
  DeFi protocols (openbook_v2, solend, lulo, meteora_dlmm, meteora_farms,
  flash, defituna, kamino, spl, jupiter, xstep, titan, dflow) it was
  never specifically written against -- exactly the generic,
  protocol-agnostic design MASTER_SPEC section 21 requires. It does
  *not* by itself prove classification-label correctness beyond what
  section D already reports (43% `UNKNOWN` on real position activity).

F. Test D -- Cost and scaling feasibility

**Measured (this spike, entirely offline):**

- RPC calls: 0 (all 28 transactions were pre-captured by the two
  upstream open-source repositories; no live Helius/RPC call was made).
- Provider credits: 0.
- Archive bytes: 926,336 bytes (28 raw transaction JSON files,
  `orchestration/phase_1_5/evidence/raw/`).
- BigQuery bytes: 0 (BigQuery was not used -- see section M; reachable
  at the network layer but not usable without a GCP project/credential
  this implementation agent may not create or enter).
- Elapsed processing time: 0.006s (parsing + classification + cross-
  validation of all 28 transactions; excludes the manual repository-
  discovery/inspection time, which is not a repeatable machine cost).
- Disk usage: ~1.0 MB total for `orchestration/phase_1_5/` (raw evidence
  + provenance + analysis results).

**Scaling estimate to 100 / 1,000 wallets -- explicitly theoretical, not
empirically measured** (this spike made zero live RPC calls, so no
empirical per-wallet acquisition cost exists to extrapolate from
directly):

- Assumption: a live acquisition path would need, per wallet, one or
  more `getSignaturesForAddress` calls (paginated at up to 1,000
  signatures per call) followed by one `getTransaction` call per
  signature to obtain full raw evidence. Using a labeled, low-confidence
  placeholder of **500 historical transactions per wallet** (this
  spike's own sample wallet had only 14-28 transactions visible across
  ~1 year in an upstream test-fixture corpus, which is almost certainly
  *not* representative of a real active wallet's true transaction count
  and is not used as the basis for this estimate; 500 is a round,
  clearly-labeled placeholder pending real data): ~1 signature-page call
  + ~500 `getTransaction` calls = **~501 RPC calls per wallet**.
- **100 wallets:** ~50,100 RPC calls (linear extrapolation).
- **1,000 wallets:** ~501,000 RPC calls (linear extrapolation).
- Linear extrapolation is used per the instruction's explicit allowance;
  it is very likely an underestimate for popular/high-activity wallets
  and an overestimate for dormant ones -- no per-wallet activity
  distribution is known in this sandbox.
- Dollar/credit cost is deliberately **not** estimated: this project's
  own `config/providers.yaml` records only a conservative rate limit
  (`conservative_rate_limit_per_sec: 5` for Helius) and
  `paid_historical_api_enabled: false` (PROV-001) -- no per-call credit
  price table exists anywhere in this repository to convert a call count
  into a credit/dollar figure, and this implementation agent will not
  invent one from memory with false precision. Converting the call-count
  estimate above into a credit/dollar cost requires Helius's current
  published pricing, to be obtained and recorded by the orchestrator/
  operator, not fabricated here.
- Token-level early-buyer discovery (Test A) has no comparable estimate
  at all: unlike a wallet's signature list, discovering *all* buyers of
  an arbitrary token requires enumerating activity against the token's
  bonding-curve/pool/associated-token accounts, whose transaction volume
  for a popular token can be orders of magnitude larger and highly
  non-uniform; no defensible placeholder assumption is offered here
  rather than inventing one.

G. Required conclusion

`HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`

Rationale: the interpretation/parsing layer of the free-first
architecture is demonstrated sound against real, diverse, previously-
unseen historical evidence (Test C: 28/28 agreements; Test B: the
parser correctly computes every balance delta it is given, section D).
The path is usable enough to proceed to later historical archaeology,
but two concrete limitations must be carried forward explicitly, per
the instruction's own definition of this disposition, rather than
smoothed over:

1. **Data-acquisition breadth is unproven in this sandbox.** Test A
   recovered exactly 1 real early buyer (not fabricated, not zero, but
   far short of a usable buyer cohort) because this sandbox has no
   working live RPC or indexed-dataset path (section M) -- this is an
   environmental/credential limitation tracked separately as
   `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/
   `PG17_COMPOSE_VALIDATION`, not a claim that the RPC-signature-
   enumeration architecture itself is unsound -- but it is genuinely
   *unproven* here, not merely inconvenient, and must not be read as
   closed.
2. **Classification completeness has a real, measured gap for non-
   trivial DeFi activity.** 43% of a real wallet's real lending/yield-
   position transactions classify `UNKNOWN` under the current
   balance-delta-only parser (section D) -- correctly fail-closed, never
   fabricated, but a concrete scope item for Phase 2 if position-level
   (not just swap/transfer-level) history is required.

`FAIL` was considered and rejected: Test A did produce one genuine,
non-fabricated recovered buyer (not a hard zero), and Test B/C
positively demonstrate the downstream interpretation architecture is
correct against real data spanning many protocols -- the honest
disposition is that the path is usable with named, unresolved gaps, not
that it cannot support the needed evidence at all. This is not treated
as an unconditional PASS precisely because of limitation 1 above.

H. Discovery method and its limits (source/completeness limitations,
   contract item 8, continued)

- Repository discovery was limited to names already known to this
  project (`SEARCH_LOG.md`'s prior rounds) -- no open-ended GitHub
  search was available this session (`api.github.com`'s search
  endpoints are rejected: "sessions are bound to their configured
  repositories", confirmed directly via `curl`). A network-enabled host
  with real GitHub search access, or a live Solana RPC/indexer
  credential, would very likely surface materially better historical
  datasets than what two already-known parser-test repositories happen
  to embed.
- Both source repositories are protocol/instruction **parser test
  suites**, not historical-data archives: their fixtures are chosen by
  their own maintainers to exercise distinct code paths, not to capture
  one wallet's or token's continuous history. The two multi-transaction
  wallets used here (14 and 13 transactions respectively) were found by
  systematically indexing all 156 + 27 embedded transactions in both
  repositories' full data corpora by fee-payer wallet and token mint
  and selecting the wallets with the most repeated appearances -- not
  because either repository intentionally documents a wallet history.
  This is disclosed, not presented as a designed dataset.
- No two files in either full corpus share a non-major token mint
  (checked directly, all pump.fun/photon-labeled fixtures reference 8
  distinct token mints, no repeats) -- confirming no GitHub-embedded
  multi-buyer-per-token dataset exists in the sources available here.

I. Commands actually run, and test results (contract item 9)

Test results summary: 4 new Phase 1.5 tests passed, 0 failed; full
repository suite 551 passed, 0 failed, 0 unexplained skipped. Each Test
A-D's own acceptance criteria (as this instruction defines them) and its
result is scored individually in sections C-G above; the commands below
are what actually produced those results.

- `uv run python scripts/phase_1_5_feasibility.py` -- 28/28 transactions
  cross-validated, 0 disagreements (this checkpoint's section E).
- `uv run pytest tests/phase_1_5/ -v` -- 4 passed
  (`test_at_least_20_real_transactions_are_available_for_cross_
  validation`, `test_independent_recomputation_agrees_with_the_parser_
  for_every_transaction`, `test_token_creator_initial_buy_is_a_real_
  recoverable_early_buyer_event`, `test_candidate_wallet_history_spans_
  multiple_required_dimensions`).
- `uv run pytest -q` (full repository suite, including the 4 new tests
  above) -- 551 passed, 0 failed, 0 unexplained skipped (real local
  PostgreSQL 16, confirmed reachable this session).
- `uv run ruff check .` -- All checks passed.
- `uv run ruff format --check .` -- clean (2 new files formatted before
  commit).
- `uv run mypy` -- Success: no issues found in 75 source files (the new
  spike script/test are outside `[tool.mypy]`'s `packages = ["argus"]`
  scope, matching every prior round's script/test-file convention --
  `scripts/argus_orchestrator_watch.py` and its test file are handled
  identically).
- No schema migration was created (this spike changes no persistent
  schema; the instruction explicitly says not to create one merely to
  have one).
- No existing golden/real-chain fixture changed: `git diff --stat
  2fbc566..HEAD -- tests/golden` is empty (confirmed before this
  checkpoint was written); `uv run argus fixtures validate-real-chain`
  still reports all 12 fixtures `ok` (unchanged from round 6).
- `git ls-files`-based secret scan across all tracked files, including
  this spike's new evidence directory -- clean, no matches. `.env`
  confirmed untracked and gitignored.

J. Deviations from this instruction (contract item 10)

None. Work stayed within `AUTHORIZED_ACTION:
EXECUTE_PHASE_1_5_HISTORICAL_DATA_FEASIBILITY_SPIKE_ONLY`: no Phase 2
discovery pipeline, no production-scale historical archaeology, no new
provenance framework beyond what this spike's own evidence needed, no
unrelated watcher/security redesign, no paid-provider enablement, no
signing/credential/live-arm work. The generic-parser completeness gap
noted in section D/G is disclosed as a `HARDENING_BACKLOG`-eligible
finding (section K), not adopted as a new Phase 1.5 blocking criterion,
per the instruction's own explicit "no moving goalposts" policy.

K. Known bugs/debt (contract item 11) -- split blocking vs
   HARDENING_BACKLOG

**Blocking (must be resolved before Phase 2 can rely on this path):**
none identified this spike beyond the two limitations already carried
in section G's `PASS_WITH_LIMITATIONS` rationale, which are themselves
the explicit output of this feasibility test, not a separate bug.

**HARDENING_BACKLOG (useful, not required to close this spike):**

- The generic balance-delta parser has no dedicated classification for
  lending/yield-position lifecycle events (deposit/borrow/repay/
  withdraw/claim), causing a 43% `UNKNOWN` rate on real position-
  management activity (section D). A future protocol-aware or
  heuristic extension (distinct from the existing `LP_ACTION`
  AMM-liquidity heuristic) could reduce this, but is explicitly out of
  this spike's scope per the instruction's "do not expand the phase
  into ... extra provider hardening" rule.
- `scripts/phase_1_5_feasibility.py`'s repository-discovery method
  (index an entire known repository's embedded fixtures by fee-payer/
  mint) is a one-off manual technique, not integrated into any CLI
  command -- reusable as a future Phase 2 building block if GitHub
  search access is ever restored, but not generalized here.

L. Security state (contract item 12)

- `LIVE_READY_SOFTWARE=false`, `LIVE_CANARY_PASSED=false`,
  `LIVE_ARMED=false` -- unaffected by this spike.
- No signing, signer, private-key, seed-phrase, live-arm, or broadcast
  path was added or touched.
- No provider/API credential was entered, disclosed, or committed
  (BigQuery's `bigquery.googleapis.com` was probed for reachability
  only -- a bare unauthenticated GET returning HTTP 401 -- no
  credential was supplied, requested, or exists in this sandbox for it;
  `.env`'s `BIGQUERY_PROJECT_ID`/`BIGQUERY_CREDENTIALS_JSON_PATH` remain
  empty).
- Secret scan clean across all tracked files including the new evidence
  directory (section I).
- No paid-provider feature enabled; `config/providers.yaml` unchanged.

M. Environmental deferrals carried forward (contract item 13)

Unchanged, per the instruction's explicit "do not spend Phase 1.5
repeatedly trying to close environmental items" rule -- each was
re-confirmed exactly once this session, not repeatedly probed:

- `LIVE_HELIUS_RPC_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` -- no
  `HELIUS_API_KEY` configured; general Solana RPC egress remains
  proxy-blocked regardless (`curl` to `api.mainnet-beta.solana.com`,
  `rpc.ankr.com`, `solana-mainnet.g.alchemy.com`, and
  `public-api.solscan.io` all fail with `CONNECT tunnel failed,
  response 403` -- an organization egress-policy denial, confirmed once
  this session, not retried).
- `LIVE_HELIUS_WSS_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` -- same
  credential/network blocker.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` -- unchanged;
  not exercised this spike (no schema change).
- **New this session, not previously tracked:** BigQuery
  (`bigquery.googleapis.com`) is reachable at the network/proxy layer
  (unlike the RPC/market-data hosts above), but requires a GCP
  project + credential this sandbox does not have and this
  implementation agent may not create or enter --
  `BQ_PUBLIC_DATASET_ACCESS = DEFERRED_ENVIRONMENTAL_CHECK` (new
  disposition label; not previously named because no prior round
  attempted a BigQuery-dependent path). Closing this requires an
  operator-supplied `BIGQUERY_PROJECT_ID`/service-account credential in
  `.env`, per the existing PG17/Helius pattern -- never entered by the
  implementation agent.

None of these is claimed as PASS, and none is silently converted to
closed by this checkpoint.

N. STOP / next action requiring orchestrator review (contract item 14)

Per this instruction: "Push all authorized work, verify remote/local
HEAD agreement and a clean worktree, then STOP. Do not begin Phase 2,
even if HISTORICAL_DATA_PATH = PASS or PASS_WITH_LIMITATIONS." No Phase
2 work was started. `docs/BUILD_STATE.md`'s `last_orchestrator_approved_
phase` is set to `1` per this instruction's explicit direction (section
A), and is **not** advanced to `1.5` -- Phase 1.5 is reported
implementation-agent-complete and awaiting orchestrator review only.
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified.

Open items for orchestrator review:

1. Whether `HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS` (section G) is
   an acceptable disposition to authorize Phase 2 discovery work, or
   whether the two named limitations (unproven data-acquisition
   breadth; 43% parser `UNKNOWN` rate on position activity) require
   further spike work first.
2. Whether closing `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_
   VALIDATION` (a real credential) or `BQ_PUBLIC_DATASET_ACCESS` (a
   GCP project/credential) should be prioritized before Phase 2, since
   Test A's core limitation traces directly to both being closed.
3. The round-6 commit-trailer waiver (this instruction's own
   disposition) is not re-litigated here; all commits in this run carry
   the sole final trailer paragraph `ARGUS-INSTRUCTION-ID:
   argus-phase-1-5-001`, verified via `git interpret-trailers --parse`
   before push.

STOP. Await orchestrator review of this checkpoint before any Phase 2
work.

================ END ARGUS CHECKPOINT =========================
