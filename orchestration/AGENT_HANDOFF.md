# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0035-final-spec-recovery-001
UTC_TIMESTAMP: 2026-09-04T21:20:00Z
CURRENT_COMMIT: ffb431394f596107cef3d0ef09c2f810059d42e7
CURRENT_PHASE: 11
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-final-spec-recovery-001
WORKING_TREE: clean
CHECKPOINT_PATH: orchestration/checkpoints/fsr15_16_final_recovery_acceptance_matrix.md
BUNDLE_PATH: orchestration/bundles/fsr15_16_final_recovery_acceptance_matrix.txt
TEST_STATUS: tests/unit + tests/golden + tests/replay (1288 tests): 0 failed. tests/integration on PostgreSQL 16 (PostgreSQL 17 environment-blocked, see below): 384 passed, 21 failed -- all 21 traced to one single disclosed, pre-existing shared-dev-database test-isolation gap (checkpoint section C), none touching this recovery's own FSR-01/02/03 work. ruff check/ruff format --check/mypy clean. Zero-to-head Alembic migration + single head (0037) verified on a fresh PostgreSQL 16 database.
ORCHESTRATOR_REVIEW_REQUIRED: audit the complete `argus-final-spec-recovery-001` contract (FSR-01 through FSR-16) against `TARGET_COMMIT` `ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30` and this handoff's own checkpoint, with particular attention to: (1) whether FSR-01/02's production-capable executor boundary genuinely stays isolated and inert (no live dispatch path, `LIVE_ARMED` unconditionally false) while being structurally real; (2) whether FSR-03's `FINAL_RECOVERY_ENVIRONMENT_BLOCKED` disposition and its supporting evidence are acceptable given this sandbox's Docker/PGDG restrictions; (3) whether FSR-15's disclosed 21-failure test-isolation gap (checkpoint section C) is acceptable to leave open pending a dedicated follow-up, or must be closed before any further approval. This session does not and cannot apply final recovery approval itself.

## Work completed

Executed the complete `argus-final-spec-recovery-001` contract
(FSR-01 through FSR-16), responding to an independent audit that found
the original Phase 6-11 build contaminated/incomplete against
MASTER_SPEC.md v2.0 at `TARGET_COMMIT`
`ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30`.

**FSR-04 through FSR-14** (a reusable point-in-time/knowledge-cutoff
invariant; real Phase 7 forward-information-after-leader evidence; real
Phase 8 point-in-time convergence and outcome comparisons; complete Phase
9 predation inputs; real Phase 10 executable-return backtesting; a
rebuilt, causally-sound Phase 11 dataset with staleness-bounded snapshots,
per-horizon right-censoring, and a purged/embargoed chronological split;
a `contaminated_run_invalidations` registry versioning and explaining the
Phase 8/9/10/11 algorithm-version bumps; retroactive Phase 7-11 recovery
checkpoints) were completed and committed individually earlier in this
same recovery -- see this session's own prior `docs/DECISION_LOG.md`
entries and `orchestration/checkpoints/phase_{7,8,9,10,11}_final_recovery.md`.

**FSR-01/02** (this handoff's own most recent substantive work): a
production-capable executor process boundary --
`argus.executor.live_signing.FileKeypairSigner` (a real Solana ed25519
signer via the `solders` SDK, loading a keypair only at runtime from an
external operator-controlled path named by `ARGUS_EXECUTOR_SIGNER_KEY_PATH`,
never touched by this coding session), `argus.executor.live_submission.
SolanaSubmissionClient` (a real `sendTransaction` broadcast adapter kept
physically isolated inside `argus.executor` rather than added to the
shared read-only Helius client), the distinct `argus.executor.main`
process entry point (run for real end-to-end this session, acquiring a
genuine `PostgresLeaseStore` singleton lease, correctly reporting no
signer/arm-file configured and never dispatching), and a new `executor`
Compose service gated behind a `profiles: ["executor"]` opt-in so a plain
`docker compose up` never starts it. A new AST-based isolation test
(mirroring the existing P6-02 mechanism) proves no non-executor package,
no other `argus.executor` module, and `cli.py`/`api` can ever import
either live-capable module. Alongside it, real chain-based fill
reconciliation: migration 0037 adds `transaction_signature`/`slot`/
`confirmation_state` to `execution_fills`;
`argus.executor.confirmation.reconcile_submitted_fill` reconstructs
actual fill evidence from confirmed chain data via the SAME Phase 1
balance-delta parser tracked-wallet ingestion already uses (never a
second reimplementation), is crash-safe and idempotent across restarts,
and never regresses already-recorded confirmation evidence. A genuine
pre-existing bug, blocking this work's own crash-recovery tests, was
found and fixed along the way:
`get_or_create_execution_intent`/`get_or_create_execution_fill` returned
a freshly-inserted row that was never attached to the session (the raw
`INSERT` bypassed the ORM unit of work), so a same-transaction
`apply_transition`/evidence mutation was silently lost at flush time.

**FSR-03**: genuine PostgreSQL 17 is not reachable from this
implementation sandbox for a purely external reason, reproduced directly
rather than assumed -- the Docker daemon cannot start (`containerd`
startup times out under this sandbox's own container-isolation
restrictions) and the outbound proxy denies CONNECT to the PGDG package
hosts by policy (confirmed via the proxy's own status endpoint as a
policy denial). The one PyPI-distributed embedded-Postgres package found
(`pgserver`) was installed and its actual bundled binary inspected
directly: PostgreSQL 16.2, not 17. Checkpointed exactly
`FINAL_RECOVERY_ENVIRONMENT_BLOCKED` with the exact failed commands/
errors and the full list of FSR-03's 7 required test categories, none of
which executed on genuine PostgreSQL 17. PostgreSQL 16 is explicitly
NEVER claimed as a substitute PASS anywhere in this recovery.

**FSR-15/16**: as supplementary (not substitute) evidence, ran the full
`tests/integration` suite on PostgreSQL 16 twice -- first pass: 367
passed, 38 failed; every one of the 38 individually root-caused to three
distinct, pre-existing causes, none touching this recovery's own
FSR-01/02 changed files. Two of the three (a stale hardcoded Alembic
revision literal in `tests/integration/test_migrations.py`; a DB-role
misconfiguration in
`tests/integration/test_phase6_persistence_and_concurrency.py`) were
small, safe, clearly-scoped fixes and were applied; the second pass
confirmed both fixed (384 passed, 21 failed, all 21 now the single
remaining disclosed cause: shared long-lived dev-database pollution
across this session's own accumulated test runs, affecting several
Phase 5/7/8/9/10/11 + shadow/reconciliation test files, which requires a
larger repository-wide test-isolation change left as explicit open work
rather than rushed through unsafely -- checkpoint section C). This
recovery does NOT claim `LIVE_READY_SOFTWARE=true` and does NOT claim
unconditional final recovery PASS; the acceptance matrix
(`orchestration/checkpoints/fsr15_16_final_recovery_acceptance_matrix.md`)
maps every FSR-01..16 item to its true status. `docs/BUILD_STATE.md` and
`docs/DECISION_LOG.md` were updated with this recovery's own final
entries; this file replaces the prior Phase 6 handoff per FSR-16's own
"single handoff" requirement.

## Security-state confirmation (FSR-16)

- Phase 6.5 (MAINNET CANARY) has NOT run and was not attempted.
- No mainnet transaction was signed or broadcast.
- No real operator key/seed was accessed, read, printed, logged, or
  exposed -- every signer test used a fresh, ephemeral, in-test-generated
  keypair, never committed.
- No funded wallet was created.
- No arm file was created or modified.
- No capital default was changed from zero.
- No paid provider was enabled.
- No secret was requested and no paid infrastructure was enabled to work
  around FSR-03's PostgreSQL 17 block.

Full itemized evidence for each of the above: checkpoint section D.

## Deferred / open items (explicitly disclosed, not hidden)

- FSR-03: genuine PostgreSQL 17 validation remains blocked in this
  sandbox (Docker daemon, PGDG proxy policy) -- needs either a sandbox
  with a working Docker daemon/unblocked PGDG access, or an operator-run
  `make up && make test` against the repository's own `compose.yaml`.
- FSR-15: 21 `tests/integration` failures remain, all attributable to one
  disclosed shared-dev-database test-isolation gap (checkpoint section
  C) -- needs a dedicated pass giving the affected Phase 5/7/8/9/10/11 +
  shadow/reconciliation test modules their own isolated database (the
  same pattern `tests/integration/test_migrations.py`'s own
  `scratch_database` fixture already uses), out of this recovery's own
  FSR-01/02/03 scope.

## Exact next action requested from orchestrator

Per `orchestration/AUDITOR_POLICY.md`: audit the complete
`argus-final-spec-recovery-001` contract (FSR-01 through FSR-16) against
this handoff's checkpoint and bundle. If satisfied, only the
orchestrator/human operator may apply final recovery approval -- write
the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to
the exact commit named in this handoff) to do so, to authorize the two
disclosed open items (FSR-03/FSR-15) as a follow-up scope, or to require
further remediation. Until a new instruction exists, the watcher (if
running) takes no action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** if you cloned/fetched this branch
before this handoff's own `UTC_TIMESTAMP`, re-fetch to pick up this
recovery's commits.
