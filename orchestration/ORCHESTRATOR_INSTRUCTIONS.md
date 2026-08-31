# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly records an orchestrator
approval, clarification, or change-control decision.

---

INSTRUCTION_ID: argus-phase-1-5-001
ISSUED_AT: 2026-08-31T20:46:38Z
TARGET_COMMIT: 2fbc566af74832bc6523648f60ba8cb60d98eb31
AUTHORIZED_ACTION: EXECUTE_PHASE_1_5_HISTORICAL_DATA_FEASIBILITY_SPIKE_ONLY
AUTHORIZED_PHASE: 1.5
APPROVES_PHASE: 1
STATUS: ACTIVE

## Independent audit disposition

### Phase 1 decision

Phase 1 is **ORCHESTRATOR APPROVED** at TARGET_COMMIT
`2fbc566af74832bc6523648f60ba8cb60d98eb31` with disposition:

`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`

The approval is based on an independent audit against the frozen Phase 1 gate
in `MASTER_SPEC.md`, not on the implementation agent's PASS claim alone.
The audited implementation contains the required provider adapters, continuously
running ingestion composition, per-wallet subscriptions, persistent watermarks,
fast-path plus truth-path reconciliation, stream-gap handling, provider probes
and usage accounting, streaming accounting, central request prioritization,
immutable canonical chain evidence, deterministic generic parsing, required
golden fixture coverage, and no signing/private-key execution path. The
required disconnect/A/B/reconnect reconciliation behavior is exercised through
real persistence integration tests and produces A exactly once and B exactly
once. The completed round-6 evidence reports 547/547 repository tests passing,
86% overall coverage, Ruff and mypy clean, real PostgreSQL-16 integration and
migration checks, and all nine required real-chain golden-fixture categories
independently validated.

This approval does **not** convert environmental checks that were never run into
PASS:

- `LIVE_HELIUS_RPC_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `LIVE_HELIUS_WSS_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`

The implementation sandbox lacks the required live Helius credential/general
chain-data egress and cannot pull the PostgreSQL-17 Docker image. PostgreSQL-16
and fake/injected transport evidence must continue to be labeled honestly.
These deferred checks remain mandatory before ARGUS can be declared live-ready;
they do **not** block the Phase 1.5 historical feasibility spike.

No live trade, mainnet canary, transaction broadcast, signing, private-key or
seed access, credential entry/disclosure, paid-provider upgrade, live arming,
threshold relaxation, or phase skip is approved by this instruction.

### Round-6 commit-trailer disposition

The round-6 checkpoint disclosed that three round-6 commits contain the correct
text `ARGUS-INSTRUCTION-ID: argus-phase-1-remediation-006`, but placed it in a
paragraph that `git interpret-trailers --parse` does not recognize as the final
Git trailer block because a later `Co-Authored-By`/`Claude-Session` paragraph
follows it. This violates the existing orchestration trailer-format contract.

The orchestrator independently reviewed the run commit range, ancestry, changed
paths, handoff, checkpoint, implementation, and representative affected commits.
The affected commits are within the authorized round-6 scope and the defect is
one of trailer formatting, not evidence that unauthorized Phase 1.5/live work
was introduced. Therefore:

- **Do not rewrite or force-push shared history solely to repair these already-
  pushed trailer blocks.** This completed run receives a one-time manual
  orchestrator waiver after independent review.
- This waiver does not weaken the protocol prospectively. Every commit made
  under this and later watcher-launched instructions MUST carry exactly one
  real terminal Git trailer recognized by `git interpret-trailers --parse`.
- To avoid ambiguity, use the following as the **sole final paragraph** of every
  implementation-agent commit in this run:

  `ARGUS-INSTRUCTION-ID: argus-phase-1-5-001`

- Do not put `Co-Authored-By`, `Claude-Session`, or any other paragraph after
  that terminal trailer. If such metadata is desired, place it earlier in the
  message body so the ARGUS trailer remains the final trailer block.
- Do not alter historical checkpoint rows to hide or erase the disclosed defect.

## Audit policy for this phase — frozen gate, no moving goalposts

This is a **feasibility spike**, not a production historical-data build.
The blocking acceptance contract for Phase 1.5 is frozen now and consists of:

1. The Phase 1.5 requirements in `MASTER_SPEC.md`.
2. Existing cross-phase invariants already applicable to this work, especially
   point-in-time truth, immutable evidence, reproducibility, free-first cost
   control, no secret leakage, and no live/signing authority.
3. The explicit evidence/checkpoint requirements in this instruction.

Do not expand the phase into Phase 2 architecture, production-scale historical
archaeology, a new provenance framework, extra provider hardening, or unrelated
watcher/security redesign.

If a useful improvement is discovered that is not required to answer the
Phase 1.5 feasibility question and does not represent a concrete safety or
research-integrity failure in this phase, classify it as `HARDENING_BACKLOG`,
document it, and continue. It MUST NOT become a new Phase 1.5 blocking
criterion.

The expected process is one implementation submission and, if genuinely
necessary, at most one consolidated remediation pass. Do not self-create new
acceptance criteria after seeing results.

## Mandatory session start

Before changing code or running the feasibility study:

1. Run:
   - `git status --porcelain`
   - `git pull --ff-only`
   - `git log -5 --oneline`
2. Read, in this exact order:
   - `MASTER_SPEC.md`
   - `docs/BUILD_STATE.md`
   - `docs/DECISION_LOG.md`
   - `orchestration/PROTOCOL.md`
   - `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
   - `orchestration/AGENT_HANDOFF.md`
3. Verify this ACTIVE instruction was introduced by exactly one commit that
   touches only `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` and whose parent
   is exactly TARGET_COMMIT
   `2fbc566af74832bc6523648f60ba8cb60d98eb31`.
4. Verify the worktree is clean and local HEAD equals freshly fetched remote
   branch HEAD.
5. Verify pre-advance BUILD_STATE still represents completed Phase 1 awaiting
   orchestrator review: `current_phase: 1`, `last_completed_phase: 1`, and
   `awaiting_orchestrator_review: true`.
6. This instruction explicitly approves Phase 1. Update durable build state in
   the ordinary append-only/change-controlled manner as Phase 1.5 begins:
   `last_orchestrator_approved_phase` becomes `1`, and the approved Phase-1
   implementation commit is TARGET_COMMIT above. Do not mark Phase 1.5
   orchestrator-approved.
7. If the watcher/local orchestration state reports a genuine terminal
   `QUARANTINED` trust state, do not bypass it in code. Stop and report the
   exact state for human/orchestrator review. An ordinary prior failed run is
   not permission to rewrite history.

## Phase 1.5 mission

Execute exactly the MASTER_SPEC Phase 1.5 historical-data feasibility spike.

Goal:

Prove whether ARGUS's free-first data architecture can reconstruct the
historical evidence needed for later token/wallet archaeology **before** a
large historical pipeline is built.

This phase answers feasibility, completeness limitations, and scaling cost. It
does not build Phase 2 discovery and does not optimize a trading strategy.

## Required inputs

Attempt to establish automatically, from existing authenticated repository
evidence and/or reachable free/public sources:

- **1 verified historical token**, and
- **1 verified candidate wallet** associated with usable historical on-chain
  evidence.

Rules:

- Use real Solana identities/evidence. Synthetic fixtures do not satisfy the
  two required Phase 1.5 inputs.
- Prefer already-preserved authentic evidence or free/public sources before
  introducing any new dependency.
- Do not enable or require a paid provider.
- Do not request or access private keys, seed phrases, signing credentials, or
  live-arm material.
- A normal provider/API credential may not be entered or disclosed by the
  implementation agent. If an optional source is unavailable without a local
  operator credential, report that fact and evaluate other free paths.
- Do not silently claim a token or wallet is verified when identity/provenance
  cannot actually be established.

If the required token and wallet **cannot** be established automatically, do
not invent substitutes and do not turn this into an open-ended search project.
Produce the exact required result:

`BOOTSTRAP_TOKEN_INPUT_REQUIRED`

Then create the Phase 1.5 checkpoint/bundle/handoff with the evidence showing
what was attempted and **STOP**. This is a spec-defined blocked-input outcome,
not permission to begin Phase 2 or manufacture data.

## Test A — Early-buyer reconstruction

For the verified historical token, attempt to recover early meaningful buyers
using the free-first historical data paths actually available.

Report at minimum exactly what MASTER_SPEC requires:

- provider/source
- venue
- time range
- transactions inspected
- buyers recovered
- earliest recovered activity
- known gaps
- estimated completeness

Important interpretation rules:

- `estimated completeness` must be evidence-based and may be qualitative or a
  bounded estimate when the available source cannot support a defensible exact
  percentage. Do not manufacture precision.
- Preserve failures, missing ranges, provider truncation, and ambiguous events
  as explicit evidence rather than dropping them.
- The purpose is to determine whether the path is usable, not to maximize the
  recovered-buyer count.

## Test B — Candidate-wallet historical reconstruction

For the verified candidate wallet, attempt to reconstruct the MASTER_SPEC
required history dimensions:

- wallet-level signatures
- token-account activity
- swaps
- transfers
- position events
- ambiguous events

Use the existing deterministic Phase 1 parser and canonical raw evidence where
applicable rather than creating a separate ad-hoc interpretation path solely
for this spike.

Report:

- what source(s) were queried/read;
- the time range actually observed;
- counts by major reconstructed event type;
- gaps/truncation/retention limitations;
- which required history dimensions are complete, partial, unavailable, or
  ambiguous under the tested source path.

Do not infer missing history as zero activity.

## Test C — Cross-validation

Validate **at least 20 concrete historical interpretations** against raw
transaction evidence or an independent source, as required by MASTER_SPEC.

A concrete interpretation is one specific reconstructed transaction/event
claim (for example a swap, transfer, token-account event, or ambiguous event)
whose underlying evidence can be independently checked. Do not inflate the
count by treating many fields from one record as 20 separate interpretations.

For each checked interpretation preserve enough evidence to answer:

- what ARGUS interpreted;
- what evidence/source was used to check it;
- whether it agreed, disagreed, or remained ambiguous;
- reason for any disagreement/ambiguity.

If fewer than 20 independently checkable interpretations exist for the chosen
input/source path, report the actual number and treat the required Test C as
not satisfied; do not duplicate observations to reach 20.

## Test D — Cost and scaling feasibility

Measure/report the actual resources consumed by this spike:

- RPC calls
- provider credits
- archive bytes
- BigQuery bytes, if any
- elapsed processing time
- disk usage

Then provide a transparent scaling estimate for:

- 100 wallets
- 1,000 wallets

Scaling estimates must state the assumption used. Linear extrapolation is
acceptable as a simple feasibility estimate if clearly labeled and if the
known provider/source behavior does not make that assumption obviously false.

If BigQuery is used at all, retain the existing MASTER_SPEC BigQuery cost rule:
perform a dry run first, record estimated bytes, enforce the configured maximum
bytes billed, and never make unrestricted `SELECT *` queries against large
historical tables. Do not incur paid BigQuery usage without explicit human/
orchestrator approval.

## Required Phase 1.5 conclusion

After Tests A-D, record **exactly one** of:

- `HISTORICAL_DATA_PATH = PASS`
- `HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`
- `HISTORICAL_DATA_PATH = FAIL`

Interpret them as follows without changing the MASTER_SPEC gate:

- `PASS`: the tested free-first path reconstructs the required evidence well
  enough to justify proceeding to later historical archaeology, with no
  material feasibility limitation found in this spike.
- `PASS_WITH_LIMITATIONS`: the path is usable enough to proceed, but concrete
  source coverage, completeness, cost, retention, ambiguity, or scaling
  limitations must be carried forward explicitly.
- `FAIL`: the tested free-first architecture cannot support the needed
  historical evidence under the observed constraints. **STOP**; do not rescue
  the result by silently switching to paid data or beginning Phase 2 anyway.

Do not fake completeness. A limitation is not a failure merely because it would
be nice to have better data; judge whether it prevents the historical evidence
ARGUS actually needs.

## Existing Phase 1 environmental deferrals during this spike

Do not spend Phase 1.5 repeatedly trying to close environmental items that the
current sandbox is known to block unless the environment has actually changed
and the check can be run normally.

Carry forward, honestly:

- `LIVE_HELIUS_RPC_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `LIVE_HELIUS_WSS_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`

If the environment unexpectedly permits one of these checks, it MAY be run and
recorded, but it is not the mission of Phase 1.5 and must not delay the
historical feasibility work. All three remain mandatory before live readiness.

## Mandatory evidence and tests

This is a data-feasibility phase. Prefer tests that prove the exact transformations
and interpretations actually used; do not create hundreds of unrelated unit
tests to inflate counts.

Before handoff:

1. Run the new/relevant Phase 1.5 tests.
2. Run the existing full repository suite and report pass/fail honestly.
3. Run Ruff and mypy under the repository's established commands.
4. Run relevant migration checks only if this phase changes persistent schema.
   Do not create a schema migration merely to have one.
5. Run the tracked-file secret scan and verify no credential or secret was
   committed.
6. Re-run/replay Phase 1 parser/golden tests if the spike changes any parsing
   or provider-normalization code. Any unexpected existing golden change must
   fail until reviewed.
7. Record exact input identities, source paths/endpoints, time ranges, and
   reproducibility metadata sufficient for the orchestrator to reproduce the
   conclusion from the committed evidence where practical.

A network/source limitation should be reported as a limitation or blocker, not
masked with mocks and called historical validation. Mocks may test code paths;
they do not satisfy Tests A-C.

## Required checkpoint/handoff contract

At completion create **new** immutable evidence files:

- `orchestration/checkpoints/phase_1_5.md`
- `orchestration/bundles/phase_1_5.txt`

Do not overwrite any prior checkpoint or bundle.

The checkpoint must include, clearly separated:

1. identity/scope and exact commit;
2. verified token and wallet inputs, or `BOOTSTRAP_TOKEN_INPUT_REQUIRED`;
3. Test A result and evidence;
4. Test B result and evidence;
5. Test C count/results and disagreements;
6. Test D measured usage plus 100/1,000-wallet scaling estimates;
7. exact `HISTORICAL_DATA_PATH` conclusion when the spike reaches that gate;
8. source/completeness limitations;
9. commands/tests actually run;
10. deviations from this instruction, if any;
11. known bugs/debt split into blocking vs `HARDENING_BACKLOG`;
12. security/secret state;
13. environmental deferrals carried forward;
14. explicit STOP / next action requiring orchestrator review.

Update `docs/BUILD_STATE.md`, append a new `docs/DECISION_LOG.md` entry for the
Phase 1 approval/Phase 1.5 outcome as appropriate, and update
`orchestration/AGENT_HANDOFF.md`.

The handoff must use a new `HANDOFF_ID` and exactly:

`LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-5-001`

At end of a completed Phase 1.5 implementation/spike, durable state may report
Phase 1.5 as implementation-agent-complete and awaiting orchestrator review,
but MUST keep `last_orchestrator_approved_phase: 1` until a later orchestrator
instruction explicitly approves Phase 1.5.

Every commit created during this run must use the sole final trailer paragraph:

`ARGUS-INSTRUCTION-ID: argus-phase-1-5-001`

Do not place any paragraph after it.

Push all authorized work, verify remote/local HEAD agreement and a clean worktree,
then **STOP**. Do not begin Phase 2, even if
`HISTORICAL_DATA_PATH = PASS` or `PASS_WITH_LIMITATIONS`.
