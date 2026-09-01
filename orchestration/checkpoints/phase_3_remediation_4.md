================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Phase 3 fourth, consolidated remediation of the SAME P3-R2
  evidence-binding requirement, per independent focused re-audit
  `argus-phase-3-remediation-audit-003` (`FAIL_REMEDIATION_REQUIRED`) and
  orchestrator instruction `argus-phase-3-remediation-004`
  (`AUTHORIZED_ACTION: ENFORCE_EXISTING_ACQUISITION_EVIDENCE_BINDING_AT_
  LOAD_AND_USE`). Narrowly scoped to the audit's own two-part
  justification table (P3-R2a, P3-R2b): wiring `qualification_service.py`
  to the manifest's own verified derived evidence, and completing
  manifest/load validation to reject the four demonstrated missing/null/
  conflicting cases. No rework of any closed finding, no optional
  hardening, no schema change.
STATUS: Both named manifestations (P3-R2a: reconstruction was not
  actually constrained to the verified run's own evidence; P3-R2b:
  missing evidence/null derived reference/conflicting walk summary passed
  validation) are fixed with real, tested code. Phase 3 remains NOT
  orchestrator-approved -- this checkpoint reports remediation completion
  for independent audit, it does not and cannot itself apply approval.
UTC_TIMESTAMP: 2026-09-01T11:45:00Z
GIT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
TARGET_COMMIT: fb2a3f7d2b75c526d06568ab3708ff85e1c1448d
AUTHORIZED_PHASE: 3
APPROVES_PHASE: NONE

B. Two-finding closure matrix and acceptance criteria (the exact
   seven-part-justification-table blockers from
   `argus-phase-3-remediation-004`, each matched against its own required-
   implementation acceptance criteria)

| Finding | Frozen defect | Fix location | Test proof | Result |
|---|---|---|---|---|
| P3-R2a | `qualification_service.reconstruct_and_score_wallet`'s LIVE_ACQUISITION_WALK branch queried EVERY `Swap` row for `wallet_address` with `first_seen_at <= now`, never restricted to the verified run's own `acquired_evidence` -- a successful, fully-verified run could therefore be "blessed" by unrelated or differently-scoped swap rows already sitting in the database for the same wallet | The manifest is now loaded FIRST (before any swap query). For `LIVE_ACQUISITION_WALK`, `bound_swap_ids` is computed as exactly the manifest's own genuine (`PARSED`/`ALREADY_KNOWN_VERIFIED`) `derived_swap_id` set, and the swap query is restricted to `Swap.swap_id.in_(bound_swap_ids)`; a genuinely empty bound set short-circuits to `[]` rather than an unbounded `IN ()`, correctly falling through to the pre-existing zero-evidence UNKNOWN behavior. `STREAM_FORWARD_ONLY` is completely unchanged | `tests/integration/test_phase3_wallet_qualification.py`: `test_p3r2a_reconstruction_bound_only_to_named_acquisition_evidence` (an unrelated, genuinely real closed position for a second mint is proven absent from the reconstructed positions), `test_p3r2a_empty_acquired_evidence_does_not_promote_unrelated_swaps_to_usable_history` (unrelated real rows exist; empty acquired_evidence still yields UNKNOWN, zero positions), `test_p3r2a_rebinding_to_a_different_parser_artifact_yields_new_history_identity` (two parser-artifact rows for one raw event; binding one vs. the other yields two distinct history/position rows, neither rewritten) | FIXED |
| P3-R2b | `manifest_from_dict` defaulted MISSING `acquired_evidence`/`associated_token_accounts` keys to `[]` via `data.get(..., [])` (probe 2); genuine-evidence entries could carry a `derived_swap_id: None` and still decode/load successfully, since the loader only re-verified a swap reference `if ev.derived_swap_id is not None` (probe 4); `wallet_walk_status` and the structured `wallet_walk.status` could disagree, and a walk could claim `COMPLETE` while also recording a fetch failure or an unsatisfied boundary (probe 3) | `manifest_from_dict` now requires the `acquired_evidence`/`associated_token_accounts` KEYS to be explicitly present (an explicit `[]` remains legitimate; a missing key raises `ManifestDecodeError`). `PARSED`/`ALREADY_KNOWN_VERIFIED` evidence must name a non-null, real-typed `derived_swap_id`/`parser_version`/`build_hash` at decode time. `wallet_walk_status` is reconciled against `wallet_walk.status` (and each account's own `status` against its own `walk.status`); `_check_walk_internal_consistency` rejects `COMPLETE` alongside `transaction_fetch_failures != 0` or `boundary_satisfied is False`. At load time, `load_verified_acquisition_manifest` additionally verifies the manifest's own `wallet_address` against the caller's authoritative wallet row, and verifies the referenced swap's actual `parser_version`/`build_hash` match what the evidence entry claims (never "a swap for this event exists," which could name a different artifact than the one actually used) | `tests/integration/test_wallet_acquisition.py`: `test_manifest_decode_accepts_explicit_empty_arrays`, `test_manifest_decode_rejects_missing_acquired_evidence_key`, `test_manifest_decode_rejects_missing_associated_token_accounts_key`, `test_manifest_decode_rejects_null_derived_swap_for_parsed_outcome`, `test_manifest_decode_rejects_null_parser_version_for_already_known_verified`, `test_manifest_decode_rejects_wallet_walk_status_disagreement`, `test_manifest_decode_rejects_account_status_disagreement_with_its_walk`, `test_manifest_decode_rejects_complete_status_with_fetch_failure`, `test_manifest_decode_rejects_complete_status_with_unsatisfied_boundary`, `test_load_rejects_nonexistent_derived_swap_id`, `test_load_rejects_derived_swap_belonging_to_a_different_event`, `test_load_rejects_conflicting_parser_artifact_identity` | FIXED |

No previously-closed finding (P3-R1, P3-R3, P3-R4, P3-R5, P3-R6a, P3-R6b,
P3-R7, E1, or the original `bool("false")` defect closed in round 3) is
reopened or reworked this round, per this instruction's own explicit
scope lock. The accepted `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` result is
unchanged.

C. Reconstruction-binding matrix (P3-R2a)

| Evidence source | Swap query scope |
|---|---|
| `STREAM_FORWARD_ONLY` | Unchanged: every `Swap` row for `wallet_address` with `first_seen_at <= now` |
| `LIVE_ACQUISITION_WALK` | Restricted to `Swap.swap_id IN (manifest.acquired_evidence's own genuine derived_swap_id set)`, additionally bounded by the pre-existing `first_seen_at <= now` filter; a genuinely empty bound set yields `[]`, never an unbounded query |

The shared `_filter_swaps_by_as_of` future-economic-time filter (P3-R1
remediation round 2) is applied identically after this scoping, so
history assessment, position reconstruction, and scoring all still see
one common usable-evidence set -- only its INPUT is now correctly bound
for `LIVE_ACQUISITION_WALK`.

D. Fail-closed manifest/load validation matrix (P3-R2b)

| Adversarial probe (audit `argus-phase-3-remediation-audit-003`) | Prior behavior | Fixed behavior |
|---|---|---|
| 1: empty `acquired_evidence` + unrelated nonempty swaps list -> HIGH | The production service supplied every swap row regardless | Reconstruction bound to the manifest's own (here: empty) evidence set (section C) -- zero usable swaps, UNKNOWN |
| 2: delete `acquired_evidence` entirely -> decodes, HIGH | `data.get("acquired_evidence", [])` silently defaulted a MISSING key to legitimate emptiness | `manifest_from_dict` raises `ManifestDecodeError` when the key itself is absent |
| 3: `wallet_walk.status=PARTIAL` + `transaction_fetch_failures=1`, `wallet_walk_status=COMPLETE` -> decodes, HIGH | No reconciliation between the two status fields or between COMPLETE and a recorded fault | `manifest_from_dict` rejects `wallet_walk_status != wallet_walk.status` and rejects `COMPLETE` co-occurring with a fetch failure or unsatisfied boundary |
| 4: `PARSED` evidence with `derived_swap_id=None` -> loads without any Swap query, HIGH | `load_verified_acquisition_manifest` only re-verified `if ev.derived_swap_id is not None` | `manifest_from_dict` now REQUIRES a non-null `derived_swap_id`/`parser_version`/`build_hash` for every genuine-outcome entry at decode time -- a null reference can no longer reach the loader at all |

E. Commands actually run this round (raw output embedded verbatim, with
   exit status, in the paired bundle `orchestration/bundles/
   phase_3_remediation_4.txt` -- this section is the index; do not treat
   this table alone as the required raw evidence)

- `uv run pytest tests/unit/test_phase3_wallet_qualification.py -q` -- 27
  passed (exit 0, unchanged regression).
- `uv run pytest tests/unit/test_orchestrator_watch.py -q` -- 79 passed
  (exit 0, unchanged regression).
- `uv run pytest tests/integration/test_wallet_acquisition.py -v` -- 36
  passed (exit 0; was 24, +12 new focused P3-R2-round-4 tests).
- `uv run pytest tests/integration/test_phase3_wallet_qualification.py -q`
  -- 17 passed (exit 0; was 14, +3 new focused P3-R2a full-path tests).
- `uv run pytest tests/integration/test_migrations.py -q` -- 17 passed
  (exit 0, unchanged regression -- no new migration this round).
- `uv run pytest tests/golden tests/replay tests/phase_1_5 -q` -- 112
  passed (exit 0, unchanged regression).
- `uv run pytest tests/integration -q` -- 128 passed (exit 0; was 113).
- `uv run pytest -q` (full repository suite) -- 792 passed, 0 failed, 0
  unexplained skipped (exit 0; up from 777).
- `uv run ruff check .` -- All checks passed (exit 0).
- `uv run ruff format --check .` -- 221 files already formatted (exit 0).
- `uv run mypy` -- Success: no issues found in 112 source files (exit 0).
- `uv run alembic current` -- `0015 (head)` (exit 0, unchanged -- this
  round is software wiring only, no new migration).
- Database migration preservation regression re-confirmed as part of the
  17-passed `tests/integration/test_migrations.py` run above (no new
  migration, no schema touched this round).
- `uv run argus fixtures validate-real-chain` -- all 12 real-chain
  fixtures ok (exit 0, unaffected -- regression-confirmed).
- Changed-file secret scan (AWS-style keys, PEM headers, inline
  password/api-key/secret/token literals) across all 5 files this round
  touched (per `git status --porcelain`) -- clean, no matches, no secret
  values emitted.
- `git diff --stat` against `TARGET_COMMIT` -- 5 files changed, 1050
  insertions(+), 79 deletions(-).

PostgreSQL 16 remains the explicit functional substitute for PostgreSQL
17; none of the above is described as PostgreSQL 17 validation.

F. Test results summary

- unit `test_phase3_wallet_qualification.py`: 27/27 (unchanged)
- unit `test_orchestrator_watch.py`: 79/79 (unchanged)
- integration `test_wallet_acquisition.py`: 36/36 (was 24/24; +12 new)
- integration `test_phase3_wallet_qualification.py`: 17/17 (was 14/14; +3 new)
- integration `test_migrations.py`: 17/17 (unchanged)
- golden + replay + phase_1_5: 112 passed (unchanged)
- integration full suite: 128 passed (was 113)
- full repository suite: 792 passed, 0 failed, 0 unexplained skipped (up
  from 777)
- ruff check: clean
- ruff format --check: clean (221 files)
- mypy: clean, 112 source files
- real-chain fixtures: 12/12 ok
- alembic head: 0015 (unchanged)
- secret scan: clean

G. Deviation from the audit instruction

None. Work was strictly limited to (1) wiring `qualification_service.py`'s
LIVE_ACQUISITION_WALK branch to the verified run's own named genuine
derived swap rows, and (2) completing `history_reconstruction.py`/
`acquisition.py`'s manifest/load validation to reject the four
demonstrated missing/null/conflicting cases -- exactly the audit's own
two-part justification table. No previously-closed finding was reworked.
No `HARDENING_BACKLOG` item was pulled into scope. No Phase 4 work was
begun. No new migration, no schema change -- the existing
`wallet_acquisition_runs.manifest` JSONB column already represents every
field this round validates more strictly.
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified. No live
trade, signing, credential disclosure, paid-provider upgrade, threshold
relaxation, or candidate-sample expansion was performed or attempted.

H. Known bugs / debt

- No new known bugs are introduced by this round's changes.
- All debt items disclosed in prior checkpoints not superseded by this
  remediation remain unchanged and not reopened.

I. Security state

- `LIVE_READY_SOFTWARE=false`, `LIVE_CANARY_PASSED=false`,
  `LIVE_ARMED=false` -- unaffected.
- No signing, signer, private-key, seed-phrase, live-arm, or broadcast
  path exists anywhere in this round's changed files.
- Credential handling for `HELIUS_API_KEY` is unchanged; every new test
  this round uses the existing deterministic `AddressKeyedChainProvider`
  fake or directly-inserted real rows, never a real/paid provider.
- Secret scan clean on this round's 5 changed files (section E).
- No paid-provider feature enabled; no Phase 4 or later-phase code
  started; `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` not modified.

J. Cost confirmation

No real provider call was made anywhere in this round: every new test
reuses the existing deterministic `AddressKeyedChainProvider` fake or
directly-inserted rows against real-but-local-only Postgres via
`connection_for_role(..., DbRole.INGEST)`. Zero new usage-recorder rows
this round.

K. Environmental deferrals (unchanged, none reopened this round)

- `LIVE_HELIUS_RPC_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
- `LIVE_HELIUS_WSS_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
- `PG17_COMPOSE_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
  PostgreSQL 16 remains the explicit functional substitute; every
  Postgres-backed command in section E ran against it.
- `BQ_PUBLIC_DATASET_ACCESS` -- unchanged deferral.

None of these deferrals is claimed as PASS, and none authorizes live
readiness by itself. The accepted `PHASE_3_CANDIDATE_SAMPLE_BLOCKED`
result (`orchestration/phase_3/SAMPLE_REPORT.md`) is unchanged, per this
instruction's own explicit statement that it "remains accepted."

L. Next specified phase

Per orchestrator instruction `argus-phase-3-remediation-004`, this
instruction approves no phase (`APPROVES_PHASE: NONE`) and authorizes
closing exactly the two named manifestations of the same P3-R2
requirement. `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not
modified. `docs/BUILD_STATE.md`'s `last_orchestrator_approved_phase`
(`2`) and `approved_commit` are left unchanged -- this session does not
and cannot self-approve Phase 3. Per this project's established
two-commit convention, this checkpoint, the paired bundle,
`docs/BUILD_STATE.md`, `docs/DECISION_LOG.md`, and
`orchestration/AGENT_HANDOFF.md` are committed once with every
commit-hash-bearing field set to the literal placeholder
`PLACEHOLDER_FILLED_IN_SECOND_COMMIT`, then a second, immediately
following commit fills in that first commit's own real hash in every one
of those fields -- both commits carry the sole terminal trailer
`ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-004` with no paragraph
after it, verified via `git interpret-trailers --parse` before push.

STOP. Await independent audit of this remediation before any further
phase work. Passing these builder tests does not approve Phase 3. When
these two exact manifestations pass with regressions, the instruction
itself states the orchestrator should approve Phase 3 and authorize
immediate Phase 4 -- that determination belongs to the orchestrator's own
independent review, never to this builder session.

================ END ARGUS CHECKPOINT =========================
