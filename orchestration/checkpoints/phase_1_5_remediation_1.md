================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity, instruction ID, target commit, implementation commits, final commit

PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Phase 1.5 remediation round 1, per orchestrator instruction
  `argus-phase-1-5-remediation-001` (`AUTHORIZED_ACTION:
  REMEDIATE_PHASE_1_5_FALSE_COPY_ELIGIBILITY_ONLY`, `AUTHORIZED_PHASE:
  1.5`, `APPROVES_PHASE: NONE`). Fixes exactly the one SPEC_BLOCKING/
  SAFETY_OR_INTEGRITY_BLOCKING finding this instruction named: two
  authentic non-trade transactions (a Solend withdrawal/redemption, an
  xStep stake) were reported `SWAP_SIMPLE`/`is_copy_eligible=true` solely
  because each has one negative and one positive asset delta.
STATUS: HISTORICAL_DATA_PATH_PASS_WITH_LIMITATIONS
UTC_TIMESTAMP: 2026-08-31T22:33:07Z
GIT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
TARGET_COMMIT: b68e37393370c7f9f3eb8860fecdaaa3f9c28696
AUTHORIZED_PHASE: 1.5
APPROVES_PHASE: NONE

B. The frozen finding classification and its disposition

`argus-phase-1-5-remediation-001` classified this as SPEC_BLOCKING and
SAFETY_OR_INTEGRITY_BLOCKING: `wallet_05_solend_withdraw_all.json` (a
real Solend `Withdraw Obligation Collateral and Redeem Reserve
Collateral`) and `suppl_09_xstep_full_stake_ix.json` (a real xStep
`Stake`) were both reported as confident, copy-eligible swaps purely
because a one-negative/one-positive balance shape looked identical to a
genuine trade. Verified directly against the pre-fix parser before
writing this checkpoint: `parse_transaction()` on the real Solend
transaction returned `classification='SWAP_SIMPLE'`,
`is_copy_eligible=True` (confirmed via `git stash` — see section H).
This violated MASTER_SPEC section 21's "no automatic copy trade for
ambiguous interpretations" and created a materially false historical
trade signal. **Disposition: fixed** — see section C for the mechanism,
section D for before/after proof on both named fixtures.

HARDENING_BACKLOG items the instruction explicitly named as non-blocking
(incomplete early-buyer recovery, incomplete candidate-wallet history,
high `UNKNOWN` rate on position events, lack of live-provider cost
measurements, broader per-protocol semantic coverage, production-scale
archaeology) are unchanged from `orchestration/checkpoints/phase_1_5.md`
and are not re-litigated or expanded here, per the instruction's
explicit scope limit.

C. Implementation design and exact positive semantic evidence policy

A deterministic **positive semantic proof gate**, `src/argus/parsing/
generic_parser.py`:

- `_SUPPORTED_SWAP_PROGRAM_IDS: dict[str, str]` — a centralized,
  versioned (via `PARSER_VERSION`/`PARSER_BUILD_HASH`) registry of
  exactly 4 program IDs, each cited against a real mainnet transaction
  **already independently hand-reviewed** in this project's own
  permanent golden-fixture corpus (`tests/golden/fixtures/real/`),
  cross-checked directly against those fixtures' actual raw evidence
  before being added (section H documents the exact verification):
  - `JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4` (Jupiter Aggregator
    V6) — `real_mainnet_token_to_usdc_swap`.
  - `675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8` (Raydium Liquidity
    Pool V4) — `real_mainnet_partial_sell`, `real_mainnet_token_to_sol_swap`.
  - `whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc` (Orca Whirlpool) —
    `real_mainnet_orca_close_position_multi_account`.
  - `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` (pump.fun bonding
    curve) — `real_mainnet_sol_to_token_swap`.
- `_instruction_program_ids(raw)` — deterministically extracts every
  program ID invoked by a top-level or inner instruction, handling both
  raw-RPC encodings this project's own real evidence actually uses:
  index-based (`programIdIndex` resolved against `accountKeys`) and
  `jsonParsed`-style (`programId` given directly). Never assumes only
  one shape (the two named false-positive fixtures use the second
  shape; the permanent golden-fixture corpus uses the first).
- `_matched_swap_program_id(raw)` — the first registry entry the
  transaction's own instructions positively demonstrate were invoked,
  or `None`.
- `ParsedTransaction.matched_swap_program_id: str | None` — a new field,
  always computed from raw evidence at parse time (never inferred from
  classification), defaulting to `None` so pre-existing direct-
  construction call sites for non-swap classifications remain valid.
- `ParsedTransaction.is_copy_eligible` — unchanged existing gates
  (classification, confidence floor, nonzero decimals) plus one new
  requirement: `matched_swap_program_id is not None`.

This is a narrow allowlist/proof gate, not a Solend/xStep denylist and
not a full per-program instruction parser (both explicitly prohibited by
the instruction): an unmatched program is never treated as *disproven*,
it simply supplies no positive evidence, so any current or future
unsupported program (lending, staking, LP, redemption, position, or
otherwise) correctly stays research-only rather than requiring a new
denylist entry.

`PARSER_VERSION` bumped `generic_balance_delta_v1` → `_v2` (observable
eligibility output changed for real evidence, per the instruction's
explicit requirement). `PARSER_BUILD_HASH` changes automatically (a
SHA-256 of this file's own bytes, recomputed at import time). No raw
evidence is rewritten; append-only derived-output semantics and
deterministic reparse are preserved (section G).

D. Before/after results for both authentic false-positive fixtures

Verified directly against real evidence (`orchestration/phase_1_5/
evidence/raw/`), not merely asserted:

| Fixture | Classification (before/after) | is_copy_eligible (before) | is_copy_eligible (after) | matched_swap_program_id (after) |
|---|---|---|---|---|
| `wallet_05_solend_withdraw_all.json` (real Solend withdrawal, wallet `JAMESC37CTVoFEt7TAEcqBjdjAfAWZiPR1YdWotAFjeQ`) | `SWAP_SIMPLE` / `SWAP_SIMPLE` (unchanged research classification, per the instruction's explicit item 7 allowance) | `True` (confirmed via `git stash` against pre-fix code) | `False` | `None` (Solend's real program `So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo` is not in the registry) |
| `suppl_09_xstep_full_stake_ix.json` (real xStep stake, wallet `qUeL7JzC52V1DvvPkqnMd74QjThWtSJY5G1PkKv1ur7`) | `SWAP_SIMPLE` / `SWAP_SIMPLE` | `True` (confirmed via `git stash`) | `False` | `None` |

Both are proven by dedicated tests
(`tests/golden/test_generic_parser.py::test_authentic_solend_withdrawal_is_not_copy_eligible`,
`::test_authentic_xstep_stake_is_not_copy_eligible`) that load the
actual committed real evidence files directly (not a synthetic
stand-in) and by
`tests/phase_1_5/test_historical_feasibility.py::test_solend_and_xstep_false_positives_are_now_ineligible`,
which exercises the same real evidence through the Phase 1.5 rerun
pipeline.

E. Complete copy-eligible-row semantic oracle and raw evidence basis

Every row this round's rerun reports as copy eligible, with its
independent semantic evidence basis (never derived from the
classification/confidence output — see
`orchestration/phase_1_5/evidence/analysis_results.json`):

| File | Signature (truncated) | matched_swap_program_id | Venue |
|---|---|---|---|
| `token_00_pumpfun_create.json` | `2s393PSYYxJJJfGiwHf...` | `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` | pump.fun |
| `suppl_08_jupiter_no_dooot.json` | `BMRnQSJSdTPgD2A4sLcW...` | `JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4` | Jupiter V6 |
| `suppl_11_dflow_swap_with_fee.json` | `627zjqXdMpkogJFCxhcn...` | `whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc` | Orca Whirlpool (dflow's route touches Orca) |
| `suppl_13_titan_swap_with_fees_2.json` | `5T4vmMjpZDRuVGKu4GHB...` | `675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8` | Raydium LP V4 (titan's route touches Raydium) |

4 of the 28 real transactions analyzed are copy eligible under the new
gate (down from 6 before this fix — the 2 named false positives removed,
0 new false negatives among the previously-correct 4). 2 further
`SWAP_SIMPLE`-shaped rows (`suppl_02_flash_swap2.json`,
`suppl_10_titan_swap_with_fees.json`) remain honestly ineligible: their
own instructions do not invoke any of the 4 registered programs, so no
positive evidence exists for them either — not claimed as a regression,
since neither was independently verified as a genuine swap by this
project before this round (they are net-new Phase 1.5 evidence, not
previously-eligible fixtures).

Required test #4 (`tests/golden/test_generic_parser.py::
test_genuine_swap_fixtures_remain_eligible_with_positive_evidence`,
parametrized) additionally proves all 4 permanent golden real-chain
fixtures already marked eligible before this round
(`real_mainnet_sol_to_token_swap`, `real_mainnet_token_to_sol_swap`,
`real_mainnet_token_to_usdc_swap`, `real_mainnet_partial_sell`) still
satisfy the new gate — cross-checked directly against their own raw
evidence before this fix was written (section H), not assumed.

F. Corrected separation of delta arithmetic validation from semantic validation

`scripts/phase_1_5_feasibility.py` and its report
(`orchestration/phase_1_5/evidence/analysis_results.json`) now report
two distinct claims, never conflated (the instruction's explicit
requirement):

1. **`delta_arithmetic_agrees`** (per row) / **`delta_arithmetic_agreements`**
   (aggregate): does an independent, from-scratch recomputation of net
   raw balance deltas — written without calling any `argus.parsing`
   code — match what the parser's `compute_account_level_deltas()`
   actually reports. **28/28 agree.** This proves the balance-delta
   arithmetic is correct; it proves nothing about semantic
   classification or eligibility.
2. **`matched_swap_program_id`** (per row) / **`copy_eligible_rows`**
   (aggregate): the independent instruction-level semantic evidence
   basis for `is_copy_eligible`. **4/28 rows are copy eligible**, each
   with its cited program (section E); the report's
   `swap_simple_but_not_copy_eligible` field explicitly lists every
   `SWAP_SIMPLE`-classified row that is *not* eligible, including the 2
   named false positives.

No text in the checkpoint, bundle, script output, or evidence JSON
claims that the 28 delta-arithmetic agreements prove 28 semantic
classifications — the two counts (28 arithmetic agreements vs. 4
eligible rows) are reported side by side specifically so they cannot be
conflated by a reader.

G. Rerun Tests A-D and exact HISTORICAL_DATA_PATH conclusion

Rerun via `uv run python scripts/phase_1_5_feasibility.py` against the
corrected parser (`PARSER_VERSION=generic_balance_delta_v2`). No
reproducible value changed from `orchestration/checkpoints/phase_1_5.md`
except where the parser fix itself changes an eligibility outcome
(section E); Test A/B/D's own measurements are otherwise identical
since they do not depend on the eligibility gate:

- **Test A** (early-buyer reconstruction): unchanged — 1 real buyer
  recovered (the pump.fun token creator's own bundled dev-buy), still
  `SWAP_SIMPLE`/eligible under the new gate (pump.fun is a registered
  venue). Same severe known-gaps disclosure as before (no live RPC/
  BigQuery access in this sandbox).
- **Test B** (candidate-wallet history): unchanged transaction set (14
  real `JAMESC37...` transactions); the one classification change
  within this set is `wallet_05_solend_withdraw_all.json`'s
  `is_copy_eligible` flipping `True → False` — the fix itself, not a
  new limitation. The previously-disclosed 43% `UNKNOWN` rate on
  position-management activity is unchanged (`HARDENING_BACKLOG`, not
  re-litigated per the instruction).
- **Test C** (cross-validation): 28 transactions, 28/28 delta-
  arithmetic agreements (unchanged); semantic eligibility separately
  validated for all 4 currently-eligible rows (section E, new this
  round) and all `SWAP_SIMPLE`-but-ineligible rows (section D/F).
- **Test D** (cost/scaling): unchanged measured values (0 RPC calls, 0
  provider credits, 926,336 bytes raw evidence, ~6ms processing) and
  unchanged theoretical linear-extrapolation scaling estimate (~501
  calls/wallet placeholder → ~50,100 for 100 wallets, ~501,000 for
  1,000) — this remediation touched no acquisition-cost-relevant code.

**`HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`** — unchanged
disposition value, now resting on a corrected semantic-eligibility
foundation rather than a false one. The same two limitations from
`phase_1_5.md` remain carried forward explicitly: unproven data-
acquisition breadth beyond 1 recovered buyer, and the disclosed 43%
parser `UNKNOWN` rate on real position activity.

H. Commands actually run and their test results, full-suite counts and skips

All commands run against this exact commit
(`PLACEHOLDER_FILLED_IN_SECOND_COMMIT`) after the fix was complete:

1. **Targeted positive-semantic-eligibility-gate tests:**
   `uv run pytest tests/golden/test_generic_parser.py -k "solend or
   xstep or unsupported_program or genuine_swap_fixtures_remain or
   reparse_of_identical" -q` — 9 passed.
2. **All Phase 1 parser/golden-fixture tests:**
   `uv run pytest tests/golden -q` — 46 passed (up from 36 before this
   round: 8 new dedicated tests + 2 new fixtures added to 2 existing
   parametrized lists).
3. **All Phase 1.5 tests + rerun analysis:**
   `uv run pytest tests/phase_1_5 -q` — 6 passed (up from 4: 2 new
   tests proving the false positives are now ineligible and that every
   eligible row carries independent semantic evidence);
   `uv run python scripts/phase_1_5_feasibility.py` — 28 analyzed,
   0 delta-arithmetic disagreements, 4 copy-eligible (section E/F output
   reproduced above).
4. **Full repository test suite:** `uv run pytest -q` — 563 passed, 0
   failed, 0 unexplained skipped (real PostgreSQL 16, confirmed
   reachable and restarted this session after an idle-session restart
   dropped the local cluster — the same substitute local server used
   throughout this project, per `PG17_COMPOSE_VALIDATION`'s standing
   deferral). unit 458, integration 43, golden 46, replay 10, phase_1_5
   6 = 563.
5. **Ruff lint and format:** `uv run ruff check .` — All checks passed.
   `uv run ruff format --check .` — 158 files already formatted (2 files
   reformatted once during this round before commit).
6. **mypy:** `uv run mypy` — Success: no issues found in 75 source
   files.
7. **Secret scan:** `git ls-files`-based scan across all tracked files
   for AWS-style keys and PEM private-key headers — clean, no matches.
   `.env` confirmed untracked and gitignored.
8. **Migration/integration checks:** not run beyond the standing
   integration suite (item 4) — this remediation changes no persistent
   schema or persistence behavior, per the instruction's own explicit
   statement ("no schema change is requested").
9. **Regression proof (`git stash`):** stashed only
   `src/argus/parsing/generic_parser.py` and re-ran the 8 new golden
   tests targeting this fix — all 8 genuinely fail against the pre-fix
   parser. Critically, `test_authentic_solend_withdrawal_is_not_copy_eligible`
   and `test_authentic_xstep_stake_is_not_copy_eligible` fail with
   `assert True is False` on `result.is_copy_eligible` — direct,
   reproducible proof the pre-fix parser genuinely reported the real
   Solend withdrawal as copy eligible, not an assumption. Popped the
   stash to restore the fix before this checkpoint was written.
10. **Positive-registry evidence cross-check:** every one of the 4
    `_SUPPORTED_SWAP_PROGRAM_IDS` entries and the 4 currently-eligible
    permanent golden fixtures' own program IDs were independently
    extracted directly from `tests/golden/fixtures/real/sources/*.source.json`
    and `provenance.json` (not from memory) before being written into
    the registry or cited in this checkpoint — confirmed to match
    exactly (section C's citation table).

Environmental skips: none this round (Postgres was reachable throughout
once restarted; no live Helius/BigQuery/PG17 check was attempted or
represented as run).

I. Parser version/build identity and deterministic reparse evidence

`PARSER_VERSION = "generic_balance_delta_v2"` (was `_v1`);
`PARSER_BUILD_HASH` recomputed automatically from this file's own bytes.
Two existing hardcoded version-string test literals were updated to
avoid an incidental collision with this bump (`tests/unit/
test_reconciliation.py`'s literal `"generic_balance_delta_v1"` →
`"generic_balance_delta_v2"`; `tests/replay/test_replay.py`'s
hypothetical-future-version placeholder `"generic_balance_delta_v2"` →
`"generic_balance_delta_v9"`, since it would otherwise have collided
with the real, now-current `PARSER_VERSION` and silently stopped testing
what it claims to test) — mechanical renames only, no logic change, both
still pass.
`test_reparse_of_identical_canonical_input_is_deterministic`
(`tests/golden/test_generic_parser.py`) proves reparsing the exact same
raw evidence twice under the same parser version produces byte-identical
`ParsedTransaction` output, including the new
`matched_swap_program_id`/`is_copy_eligible` fields — no hidden
nondeterminism (e.g. set iteration order in
`_instruction_program_ids()`) in the new positive-evidence lookup.
Immutable raw evidence was not rewritten; append-only derived-output
semantics are unchanged (only future reparse runs under the new
`parser_version` would produce a new, additional `swaps` row per
MASTER_SPEC's append-only versioning contract — no historical row was
touched by this round, since no live database reparse was run against
persisted Phase 1 data).

J. Remaining limitations, environmental deferrals, and HARDENING_BACKLOG

No known bug remains open in the specific mechanism this round targeted
(the false-eligibility gap); every other known bug/limitation is
unchanged from `orchestration/checkpoints/phase_1_5.md`, not
re-litigated or expanded per the instruction's explicit scope limit:

- `LIVE_HELIUS_RPC_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `LIVE_HELIUS_WSS_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `BQ_PUBLIC_DATASET_ACCESS = DEFERRED_ENVIRONMENTAL_CHECK`
- HARDENING_BACKLOG: incomplete early-buyer recovery; incomplete
  candidate-wallet history and the isolated-fixture nature of the
  available sample; the 43% `UNKNOWN` rate for position events (which
  already fail closed); lack of live acquisition-cost measurements;
  broader per-protocol semantic coverage beyond the 4 currently
  supported venues (explicitly not expanded this round, per the
  instruction's "narrow allowlist ... not a production historical
  parser expansion" rule); production-scale historical archaeology.
- New this round (`HARDENING_BACKLOG`, not blocking): 2 real
  `SWAP_SIMPLE`-shaped Phase 1.5 transactions (`suppl_02_flash_swap2.json`,
  `suppl_10_titan_swap_with_fees.json`) remain honestly ineligible for
  lack of positive evidence for their specific venues (Flash, Titan) —
  a future round could extend the registry with cited evidence for
  either if a use case requires it; not required to close this
  remediation.

K. Secret/security state (and acceptance criteria disposition)

Every acceptance criteria item this instruction's "Required tests" and
"Mandatory validation" sections name is scored directly in sections
D/E/F/G/H above, each against cited, reproducible evidence rather than
bare assertion; none is scored PASS by weakening an existing check.

- `LIVE_READY_SOFTWARE=false`, `LIVE_CANARY_PASSED=false`,
  `LIVE_ARMED=false` — unaffected.
- No signing, signer, private-key, seed-phrase, live-arm, or broadcast
  path was added or touched.
- No credential was entered, disclosed, or used; no live/paid provider
  was used to improve or influence this round's result.
- Secret scan clean (section H, item 7).
- The false-positive-swap safety issue named by this instruction is
  closed: a lending withdrawal or staking deposit can no longer
  automatically generate a copy-trade signal from balance shape alone.

L. Deviations

None. Work was strictly limited to
`AUTHORIZED_ACTION: REMEDIATE_PHASE_1_5_FALSE_COPY_ELIGIBILITY_ONLY`: no
unrelated hardening, no new providers, no new historical-data
architecture, no Phase 2 work, no confidence-threshold/ambiguity-
handling/decimal-check/provider-gate weakening anywhere in the existing
parser. `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified;
`docs/BUILD_STATE.md`'s `last_orchestrator_approved_phase` remains `1`.

M. STOP pending independent orchestrator audit

Per this instruction: "Push all authorized work, verify remote/local
HEAD agreement and a clean worktree, then STOP. Do not modify this
instruction file, self-authorize Phase 1.5, begin Phase 2, or perform
any other phase." No Phase 1.5 self-approval was performed; no Phase 2
work was started. `orchestration/checkpoints/phase_1_5.md` and
`orchestration/bundles/phase_1_5.txt` are preserved unmodified as
immutable history of what round 1 claimed at the time; this is a new,
separate checkpoint/bundle pair.

STOP. Await independent orchestrator audit of this remediation before
any further phase work.

================ END ARGUS CHECKPOINT =========================
