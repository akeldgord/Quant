# ARGUS Orchestrator Final Clarification

**OWNER: ARGUS ORCHESTRATOR.** This is the final clarification of the already-frozen `argus-final-spec-recovery-002` acceptance contract. It does **not** add, remove, strengthen, or otherwise change any requirement.

---

INSTRUCTION_ID: argus-final-spec-recovery-002-clarification-002
CLARIFIES_INSTRUCTION_ID: argus-final-spec-recovery-002
GOVERNING_FROZEN_INSTRUCTION_COMMIT: 053f11de4e16831cbbb8a8a6fbb80a45e15ee1aa
PRIOR_CLARIFICATION_COMMIT: 72c69c0b7fcbe2497a8745f562cfd1c6480469fc
TARGET_COMMIT: 821409951f4bddf92fcf7ba8ee83b3c72636d3e7
AUTHORIZED_PHASE: 11
APPROVES_PHASE: NONE
STATUS: ACTIVE
AUTHORIZED_ACTION: COMPLETE_ONLY_THE_THREE_REMAINING_ALREADY_FROZEN_ACCEPTANCE_GAPS_BELOW_AND_RETURN_FOR_FINAL_AUDIT

## 1. Scope lock / no moving goalposts

The independent audit of `TARGET_COMMIT` found that the clarification-001 round closed most of the prior defects. Treat the following as **CLOSED/PASS** unless your changes create a concrete regression:

- R2-01 durable signature + `SUBMITTED` commit before confirmation;
- R2-01 crash/restart no-resubmit behavior;
- R2-01 production `main.py` -> `execute_intent_pipeline()` wiring exists;
- R2-02 persisted `source_knowledge_max_at` schema and Phase 10/11 loader enforcement;
- R2-03 configured/versioned absolute timing tolerance and deterministic nearest matching;
- R2-04 hermetic integration tests and final evidence packaging;
- FSR-02, FSR-05, FSR-06, FSR-07, FSR-10, FSR-11;
- PostgreSQL 17 remains external `FINAL_RECOVERY_ENVIRONMENT_BLOCKED` and is not part of this software correction round.

Do **not** reopen unrelated work. Do **not** redesign completed phases. Do **not** run Phase 6.5. No real operator key, funded wallet, live arming, mainnet signing/broadcast, paid provider, or live trade is authorized.

Exactly three software acceptance gaps remain. Fix only these.

---

# 2. Remaining R2-01 gap — the human canary must be executable without another code change

The frozen contract says a future Phase 6.5 human canary may require operator authorization/configuration/credentials, but must **not require new executor plumbing**.

At `TARGET_COMMIT`, `src/argus/executor/main.py` now reaches the real pipeline, which is correct. However `build_live_risk_inputs_from_params_file()` hardcodes `canary_passed=False`, and `risk_gates.build_gates()` requires `canary_passed=True` before any signing/submission can occur. Therefore the very first authorized canary is impossible: it cannot pass before it runs, and it cannot run before it passes.

This is the remaining R2-01 defect.

## Required interpretation

Keep `canary_passed` impossible for ordinary live operation before Phase 6.5 succeeds. Do **not** make the operator params JSON able to spoof it.

Add one explicit, machine-checkable **human-canary execution mode/state** to the executor path that permits exactly the first authorized Phase 6.5 canary without pretending the canary has already passed. The exact implementation is your choice, but it must satisfy all of these existing safety semantics:

1. ordinary execution still requires `LIVE_CANARY_PASSED=true`;
2. the special pre-pass canary path is reachable only under explicit human Phase 6.5 authorization evidence, never repository defaults and never a generic params-file boolean;
3. that path remains subject to all other existing risk gates, approved build/config identity, valid arm authorization, singleton fencing, transaction attestation, signer isolation, capital/size limits, and exact execution pipeline;
4. successful completion of the canary may produce the persisted evidence later used to set/derive `LIVE_CANARY_PASSED=true` for ordinary live execution; failure must not do so;
5. no code change is required after this repair merely to run the first canary.

Use the existing human authorization/arm/control-plane architecture where possible. Do not invent an automatic live loop or weaken any ordinary risk gate.

## Mandatory focused tests

Add focused tests proving:

- ordinary single-intent mode with no prior canary PASS is rejected;
- a generic/operator params file cannot spoof canary authorization;
- explicit test-only representation of a valid human Phase 6.5 canary authorization can reach the existing pipeline while all other gates still apply;
- missing/expired/mismatched canary authorization fails closed before signing/submission;
- after a simulated successful canary, ordinary execution may consume the persisted canary-PASS evidence; a failed canary cannot create that evidence.

No real canary is authorized or run in this remediation.

---

# 3. Remaining R2-02 gap — entry-specialist provenance must track source evidence knowledge time, not a newly-created derived estimate

The new `WalletSpecialistScore.source_knowledge_max_at` architecture is correct and must remain.

The remaining problem is specifically the **entry-specialist** contribution path.

At `TARGET_COMMIT`, `_compute_and_persist_counterfactual_alpha()` creates/loads `CounterfactualAlphaEstimate` and then passes `estimate.created_at` forward as the entry-specialist contribution's knowledge time. That is the physical creation time of a derived estimate, not necessarily the maximum knowledge time of the raw/intermediate evidence used to calculate the estimate.

In addition, the Phase 9 market-state functions used to compute those residuals select `TokenMarketSnapshot` rows by `observed_at` around the historical target but do not consistently enforce the row's separate `created_at` knowledge timestamp against the historical cutoff. A later-backfilled market snapshot with an old `observed_at` can therefore still contaminate a historical reconstruction.

This is exactly the already-frozen distinction between event/effective time, observation time, record creation/knowledge time, and research cutoff.

## Required correction

For the actual Phase 9 entry-specialist/counterfactual-alpha path:

1. every `TokenMarketSnapshot` (and any other actual source record used on that path) must satisfy the canonical knowledge cutoff appropriate to the historical computation: its effective/observation time must be eligible **and** its `created_at`/knowledge time must be <= the decision/research cutoff;
2. the counterfactual-alpha computation must retain or derive the maximum knowledge time of the source records actually used for each residual estimate;
3. the entry-specialist contribution forwarded into `WalletSpecialistScore.source_knowledge_max_at` must use that source-evidence maximum, **not** `CounterfactualAlphaEstimate.created_at` merely because that derived row was physically written during the replay;
4. a historical replay executed today from source evidence that was all known by T remains eligible at T;
5. a source row inserted later with `observed_at <= T` but `created_at > T` must not affect the T reconstruction.

Use the existing `known_by_cutoff` / provenance architecture. Keep scope limited to the actual affected Phase 9 -> Phase 10/11 specialist path.

## Mandatory mutation proof

The existing seven-step mutation test must be extended/corrected so the mutated row exercises the **entry-specialist market-evidence path** and the downstream affected consumers, not only `WalletScoreSnapshot`/exit-skill or a generic Phase 11 wallet fingerprint.

At minimum prove:

1. seed market/source evidence E1 known by T sufficient to produce an entry-specialist result;
2. reconstruct Phase 9 at T;
3. capture the Phase 10 specialist decision input and the Phase 11 `wallet_discovery_effect_size`/specialist-derived feature at T;
4. append E2 after T with an economic/`observed_at` timestamp <= T but `created_at` > T and values that would materially change the entry-specialist result if leaked;
5. rebuild the same historical state under a fresh identity/config/version where needed;
6. prove the Phase 10 specialist input and Phase 11 specialist-derived feature at T are semantically unchanged;
7. move the legitimate cutoff beyond E2's knowledge time and prove E2 can then affect the reconstruction.

Retain the existing direct loader/provenance tests; this test closes the one source-chain hole they do not cover.

---

# 4. Remaining R2-03 gap — Strategy A/B entry timing must compare actual evidence time to the strategy entry trigger

The configured/versioned `Phase10RunConfig.contemporaneous_match_max_delta` is correct and stays.

The remaining issue is only Strategy A/B entry matching.

At `TARGET_COMMIT`, `_select_own_entry_fill_if_contemporaneous()` compares the entry probe's real elapsed time against `opportunity.entry_target_seconds`. That proves the fill executed near its configured probe target. It does **not** prove the executable entry evidence is contemporaneous with the **strategy's own entry trigger time**, which is what the frozen requirement says.

## Required correction

For every Strategy A/B `MatchedTrade`:

1. derive the actual timestamp of the executable entry evidence from the existing persisted Phase 4/5 timing evidence (`first_seen_at + actual_elapsed_seconds_from_first_seen`, or an equivalent real observed/terminal timestamp already present in the loader);
2. compare that actual evidence timestamp to `matched.entry.at`, the strategy's own entry trigger time;
3. compute `abs(actual_entry_evidence_time - matched.entry.at)`;
4. require that delta <= `config.contemporaneous_match_max_delta`;
5. if no actual executable timestamp is available, or it falls outside tolerance, return `FAILURE_NO_EXECUTABLE_EVIDENCE`/insufficient; never substitute mark price or a distant fill;
6. deterministic selection/tiebreak remains required if more than one eligible real entry observation exists.

Do not substitute “actual delay versus configured target delay” for “actual evidence timestamp versus strategy trigger timestamp.” The former may remain a diagnostic consistency check, but it is not the frozen acceptance test.

## Mandatory focused tests

At minimum prove:

- A/B strategy trigger at time T, actual entry evidence timestamp within configured tolerance -> eligible;
- same trigger, actual entry evidence timestamp just outside tolerance -> ineligible;
- a fill that perfectly matches its configured `entry_target_seconds` but is far from the strategy trigger -> ineligible;
- deterministic nearest/tiebreak behavior if multiple entry observations qualify;
- no mark-price fallback;
- `config_hash()` continues to include the timing tolerance.

---

# 5. Final evidence and stop condition

This is the final software clarification round. Do not expand scope beyond sections 2-4.

After implementation:

1. run the focused R2-01/R2-02/R2-03 tests above;
2. run the existing complete unit/golden/replay matrix;
3. run the full hermetic integration suite with `0 failed`;
4. run ruff, format check, mypy, migration-head checks, secret scan, and the existing checkpoint/bundle validators;
5. do not retry PostgreSQL 17 unless the environment has materially changed; retain exact `FINAL_RECOVERY_ENVIRONMENT_BLOCKED` and `LIVE_READY_SOFTWARE=false` if it remains unavailable;
6. update the exact existing evidence files:
   - `orchestration/checkpoints/final_spec_recovery.md`
   - `orchestration/bundles/final_spec_recovery.txt`
   - `orchestration/AGENT_HANDOFF.md`
   - append-only `docs/BUILD_STATE.md`
   - append-only `docs/DECISION_LOG.md`;
7. final handoff must identify `LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-final-spec-recovery-002-clarification-002` and must not claim final project approval itself;
8. **STOP FOR INDEPENDENT FINAL AUDIT**.

Every new implementation/evidence commit under this instruction must end with exactly one terminal paragraph:

`ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-002-clarification-002`

Nothing may follow it.

Do not modify this file. Do not self-approve. Do not perform Phase 6.5.