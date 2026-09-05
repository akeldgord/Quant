# ARGUS Orchestrator Clarification

**OWNER: ARGUS ORCHESTRATOR.** This is a clarification of the already-frozen `argus-final-spec-recovery-002` contract. It does **not** add, remove, strengthen, or otherwise change any acceptance requirement.

---

INSTRUCTION_ID: argus-final-spec-recovery-002-clarification-001
CLARIFIES_INSTRUCTION_ID: argus-final-spec-recovery-002
GOVERNING_FROZEN_INSTRUCTION_COMMIT: 053f11de4e16831cbbb8a8a6fbb80a45e15ee1aa
TARGET_COMMIT: 1117d4eda167a203efe6c3d5c6f6248eb84051e8
AUTHORIZED_PHASE: 11
APPROVES_PHASE: NONE
STATUS: ACTIVE
AUTHORIZED_ACTION: COMPLETE_ONLY_THE_ALREADY_FROZEN_R2_01_R2_02_R2_03_REQUIREMENTS_USING_THE_CLARIFICATIONS_BELOW

## 1. No-moving-goalposts statement

The acceptance contract remains exactly the R2-01 through R2-04 requirements frozen in `argus-final-spec-recovery-002` at commit `053f11de4e16831cbbb8a8a6fbb80a45e15ee1aa`.

The independent audit of commit `1117d4eda167a203efe6c3d5c6f6248eb84051e8` found:

- R2-04: CLOSED/PASS. Do not redesign the hermetic integration-test solution or final evidence packaging except for updating final evidence after the fixes below.
- PostgreSQL 17: remains `FINAL_RECOVERY_ENVIRONMENT_BLOCKED`. Do not spend another implementation cycle retrying the same policy-blocked registry/PGDG paths unless the environment has materially changed.
- R2-01, R2-02, R2-03: not yet proven against their already-written frozen wording. The clarifications below explain the intended meaning of those existing requirements only.

Do not reopen FSR-02, FSR-05, FSR-06, FSR-07, FSR-10, FSR-11, or unrelated Phase 0-11 work unless your changes cause a concrete regression.

Phase 6.5 remains forbidden. No real key access, funded wallet, live arming, mainnet signing/broadcast, capital, paid provider, or strategy live trade is authorized.

---

# 2. Clarification of R2-01 / FSR-01 — what “used by the executor process” and “durable before confirmation” mean

The frozen instruction already says the integrated orchestration seam must be **a real callable used by the executor process** and that a later canary must require no new signer/submission/reconciliation plumbing.

Current state at TARGET_COMMIT does not yet satisfy that wording because `src/argus/executor/pipeline.py` exists, but `src/argus/executor/main.py` still performs startup/readiness only and explicitly says a future change will wire an execution path.

### Required interpretation

You do **not** need to build an automatic trading daemon, signal-consumer loop, scheduler, or live strategy engine.

A safe executor-only **single-intent mode** is sufficient. The production executor identity/entry point must have an actual code path that can invoke the existing `execute_intent_pipeline()` using the already-built production-capable signer/submission/confirmation/provider adapters, while remaining impossible to dispatch under repository defaults and without Phase 6.5 human authorization.

The point is simply this: after this repair, a future human canary may require configuration/credentials/arm authorization and an already-authorized intent, but must **not require another code change just to connect `main` -> pipeline -> signer -> submission -> reconciliation**.

### Durability clarification

The frozen step “persist the returned transaction signature and `SUBMITTED` state before confirmation polling” means **durably committed to PostgreSQL**, not merely present in the SQLAlchemy identity map and not merely `session.flush()`ed inside an outer transaction that can still roll back.

Current `execute_intent_pipeline()` submits externally, writes the signature/state, calls `session.flush()`, and then enters confirmation while the surrounding transaction is still open. A process crash at that point can roll back the DB transaction even though the network already accepted the transaction.

Fix the transaction boundary so that, after the submission result/signature is obtained, the canonical signature/fill evidence and `SUBMITTED` state are committed durably before any confirmation provider call begins. Implementation structure is your choice: a pipeline-owned transaction boundary, a dedicated persistence transaction/session, or another equivalent design is acceptable. Do not create a second state machine or second persistence model.

### Existing mandatory test semantics

The already-frozen `crash_after_submission_restart_reconciles_same_signature_without_second_submit` test must simulate a **real database crash boundary**, not “first pipeline call returns normally, context manager commits, then open a second session.”

A valid test must prove all of the following:

1. the fake external submission seam is called exactly once and returns signature S;
2. S + `SUBMITTED` become visible from a separate fresh DB connection/session **before confirmation is allowed to run**;
3. inject an exception/process-abort equivalent immediately after that durable boundary and before confirmation completes;
4. restart from a fresh session/process-equivalent;
5. the restart loads S and reconciles S;
6. quote/build/sign/submit are not called again;
7. total submission count across both runs remains exactly 1.

This is not a new test requirement; it is the meaning of the already-frozen crash-after-submit test and “durable before confirmation” wording.

---

# 3. Clarification of R2-02 / FSR-04 + FSR-09 — provenance is not the derived row’s `created_at`

The frozen instruction deliberately distinguishes:

- historical decision cutoff `as_of=T`;
- physical time the derived row was reconstructed/written;
- the knowledge time of the **source evidence used to construct it**.

The current `DirectionalEdge.created_at <= cutoff` / `ExpectedConfirmationEvent.created_at <= cutoff` filters are useful and should remain, but they are only the source-selection half of the frozen requirement.

### Required interpretation

A `WalletSpecialistScore` reconstructed today for historical cutoff T may be perfectly valid even though the specialist-score row itself has `created_at=today`. Therefore **do not** fix this by simply adding `WalletSpecialistScore.created_at <= T` to Phase 10/11 loaders.

Instead, the reconstructed score must carry machine-checkable provenance proving that every source row which contributed to it was eligible under the knowledge cutoff at T.

Use the simplest reusable implementation that satisfies the already-frozen section 4.1 model. For example, it is acceptable to add persisted fields such as:

- `source_knowledge_max_at` (maximum creation/first-seen/knowledge timestamp among contributing source evidence, after applying the canonical knowledge rule);
- and, if needed for auditability, a deterministic source-evidence/provenance hash or manifest reference.

The exact schema/names are not prescribed. What matters is that Phase 10 and Phase 11 can mechanically distinguish:

- a score physically reconstructed later **from evidence that was all known by T** -> eligible at T;
- a score whose reconstruction used even one source item only known after T -> ineligible at T.

Algorithm/config identity must remain part of the proof as already required.

### Loader interpretation

`load_specialist_scores_as_of()` and `load_discovery_effect_size_by_wallet()` may not accept a score solely because `as_of == T` and version/config match. They must require the persisted provenance/knowledge proof to demonstrate source eligibility at T.

Do the same only on the actual affected Phase 10/11 specialist/classification path. Do not turn this into a repository-wide provenance redesign.

### Mandatory section 4.3 mutation test means exactly what it says

This was explicitly marked **mandatory** in the frozen instruction and must be implemented end-to-end, not replaced by only a Phase 9 unit/mechanism test.

One test (or one tightly-coupled test case covering both downstream consumers) must:

1. seed source evidence E1 known by T;
2. reconstruct the Phase 9 specialist state for T;
3. capture the semantic Phase 10 decision input and Phase 11 specialist feature at T;
4. append a new source row with economic/effective time <= T but `created_at`/knowledge time > T;
5. rebuild the same historical state under a fresh identity if idempotency would otherwise reuse cached rows;
6. prove the Phase 10 decision input and Phase 11 feature remain semantically identical;
7. move the cutoff forward beyond the new row’s real knowledge time and prove the new evidence can then legitimately affect the result.

Also retain/add the direct loader test already required by the frozen instruction: a `WalletSpecialistScore` physically written after T with `as_of=T` cannot be accepted **merely** because its `as_of` matches; it must carry valid source-knowledge provenance.

Do not weaken this to “the score row must have been created before T”; historical reconstruction performed later is allowed when its sources prove they were known by T.

---

# 4. Clarification of R2-03 / FSR-08 — “contemporaneous” applies to BOTH sides and tolerance is versioned configuration

The current repair correctly removed the universal fixed 5-minute exit lookup and correctly added special confirmation-entry handling for Strategies C/D. Preserve that work.

Two parts of the already-frozen wording still need to be applied literally.

## 4.1 Strategy A/B source-entry timing

The frozen instruction says:

> Strategy A/B source-entry: the original shadow entry fill may be used only when its actual entry timing is the strategy entry timing represented by the trigger.

Therefore A/B cannot automatically use `opportunity.entry_fill` without checking its actual execution/probe timing against the strategy entry trigger.

Use the existing Phase 4/5 actual timing evidence. If the current `WalletOpportunity` object does not expose enough actual entry timing to prove the match, expose the relevant persisted probe/fill timing through the loader. Do not treat `first_seen_at` as the execution time unless the underlying model actually defines it that way.

If no executable entry evidence is contemporaneous with the strategy’s A/B entry trigger, return the existing no-executable-evidence/insufficient result. Do not use mark price or a distant fill to preserve sample size.

## 4.2 Configured timing tolerance

The frozen wording says “within the configured staleness/tolerance.” A hardcoded source constant such as `0.5x .. 2.0x` is not a configured/versioned tolerance.

Use the existing `Phase10RunConfig.entry_exit_price_max_staleness` as the absolute timing tolerance if that field is semantically suitable for executable-evidence matching; otherwise add one explicit Phase10 config value for executable-evidence timing tolerance and include it in `config_hash()`.

Do not invent a second unversioned magic threshold.

For entry and exit matching, compute the absolute delta between the strategy trigger time and the executable evidence’s actual observed execution/terminal time. The evidence is eligible only when `delta <= configured_tolerance`. Choose the nearest eligible item deterministically; ties must have a deterministic tiebreak. If none qualifies, report no executable evidence.

This clarification does **not** prescribe a new numerical tolerance. Use an already-frozen/existing config value where semantically correct, or expose the prior implementation choice as explicit versioned configuration rather than silently hardcoding it.

## 4.3 Existing mandatory tests

Keep the already-written one-hour and confirmation-entry traps, and add/adjust only what is necessary to prove the already-frozen semantics:

- A/B source entry whose actual fill/probe time falls outside configured tolerance -> no executable evidence;
- same fixture within tolerance -> eligible;
- quote/probe just outside configured exit tolerance -> ineligible;
- nearest quote/probe inside tolerance -> selected deterministically;
- changing the versioned tolerance changes eligibility and therefore changes `config_hash()`.

Do not tune the tolerance to improve Phase 10 performance. Poor/insufficient v3/vNext results remain valid.

---

# 5. Version/evidence handling

Do not delete or rewrite any old research rows.

If durable Phase 9/10/11 v3 rows were produced under the still-incomplete semantics above, apply the already-frozen version/invalidation rules before presenting corrected results as current. If v3 existed only in disposable isolated test databases and no durable derived result requires invalidation, do not manufacture an unnecessary version bump solely for cosmetics; document the determination in the final checkpoint.

Update the existing exact final evidence files after the repair:

- `orchestration/checkpoints/final_spec_recovery.md`
- `orchestration/bundles/final_spec_recovery.txt`
- `orchestration/AGENT_HANDOFF.md`
- append-only `docs/BUILD_STATE.md` / `docs/DECISION_LOG.md`

Run the focused R2-01/R2-02/R2-03 tests plus the existing frozen full regression/quality matrix needed to keep FSR-15 truthful. R2-04 itself is closed; do not redesign it.

If PostgreSQL 17 remains externally blocked, final status remains `FINAL_RECOVERY_ENVIRONMENT_BLOCKED` and `LIVE_READY_SOFTWARE=false` even if all software requirements pass.

---

# 6. Commit and handoff discipline

All implementation commits made in response to this clarification must end with exactly:

`ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-002-clarification-001`

with nothing after it.

Do not modify this file. Do not self-approve. Do not perform Phase 6.5.

When the three clarified already-frozen items are complete, update the exact final checkpoint/bundle/handoff, push a clean worktree, and **STOP FOR INDEPENDENT FINAL AUDIT**.