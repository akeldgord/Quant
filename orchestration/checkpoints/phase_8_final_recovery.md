================ ARGUS ORCHESTRATOR CHECKPOINT ================

RETROACTIVE_POST_BUILD_RECOVERY_CHECKPOINT — NOT A CONTEMPORANEOUS PHASE STOP

A. Identity

PROJECT: ARGUS
SCOPE: Phase 8 (CONVERGENCE + NEGATIVE EVIDENCE), MASTER_SPEC.md section
63 region (convergence surprisal, expected-confirmation "dog that didn't
bark" evidence). This document is NOT a contemporaneous per-phase
orchestrator STOP -- Phase 8 was originally built, and is here
corrected, under the human's explicit authorization for Claude to carry
Phases 7-11 through to completion without the normal per-phase
orchestrator STOP/audit cycle. This checkpoint does NOT claim a
contemporaneous STOP, independent audit, or approval occurred for Phase
8 at build time. It exists solely to satisfy FSR-14
(`argus-final-spec-recovery-001`, instruction section F).
STATUS: RETROACTIVE_RECOVERY_RECORDED (not an orchestrator PASS/approval)
GIT_COMMIT (this checkpoint's own HEAD at authoring time):
50d96933b5ecde421300e96ce7694dfcc3b7ca62

Recovery authority: `argus-final-spec-recovery-001`, item FSR-06 (Phase
8's own fix) plus the shared FSR-04 point-in-time invariant. `TARGET_
COMMIT` audited as contaminated: `ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30`.

B. What Phase 8 originally built (unchanged by this recovery)

`src/argus/convergence/` -- convergence-surprisal scoring (multiple
independent wallets entering the same token within a window, scored
against an unknown-independence-weighted base rate) and expected-
confirmation "negative evidence" (a leader's entry that a specific
follower was expected, but failed, to confirm). This structural build
(the surprisal statistic, `convergence_events`/
`expected_confirmation_events` persistence, the CLI `argus convergence
report` command) is UNCHANGED by this recovery.

C. The historical leak/omission this recovery repaired (FSR-06)

Phase 8's convergence-episode and confirmation-event computation did not
consistently apply the shared point-in-time knowledge-cutoff invariant
(FSR-04's `argus.copyability.identity.known_by_cutoff`) to every input it
read -- a wallet entry or confirmation observation recorded AFTER the
fact but describing an EARLIER moment could leak into a convergence
episode or confirmation evaluation computed as of that earlier moment.
Separately, MASTER_SPEC's own required "outcome comparison" layer
(comparing a convergence episode's real forward outcome against what an
uninformed baseline would have produced) did not exist as a persisted,
queryable evidence family at all.

D. The corrected implementation

- `src/argus/convergence/loaders.py`/`service.py`: every entry/exit
  observation Phase 8 reads is now filtered through `known_by_cutoff`
  before it can contribute to a convergence episode or a confirmation
  evaluation -- an observation recorded after `cutoff` but effective
  before it is excluded, never silently included.
- `src/argus/convergence/outcome_comparison.py` (NEW): computes each
  convergence episode's real forward executable-return outcome (reusing
  the same Phase 5 executable-return evidence population every later
  phase's own FSR fix reuses) against an uninformed baseline, persisted
  via `get_or_create_convergence_outcome_comparison`.
- `src/argus/domain/convergence_outcome_comparisons.py` (NEW table,
  migration `0032`): one row per convergence episode's own outcome
  comparison, append-only, `(episode identity, algorithm_version,
  config_hash)`-keyed per the F5-05 idempotent-persistence pattern every
  phase since Phase 5 reuses.
- Migration `0031` (`fsr05_fix_phase7_11_ingest_write_grants`, applied
  ahead of Phase 8's own FSR-06 fix in this recovery's commit sequence)
  corrected a grant-direction defect discovered during this recovery:
  migrations `0025`-`0029` had granted `INSERT` on all Phase 7-11 tables
  to `argus_research` instead of `argus_ingest`, while every production
  CLI report command actually connects as `argus_ingest` -- meaning
  every Phase 7-11 write would have failed under real database role
  enforcement. Fixed by granting `argus_ingest` (and keeping
  `argus_research`) `INSERT` on all affected tables.
- FSR-13 (this same recovery, tracked separately) subsequently bumped
  Phase 8's own `ALGORITHM_VERSION` from
  `convergence_negative_evidence_v1` to `convergence_negative_evidence_v2`
  and registered the old version in the new
  `contaminated_run_invalidations` registry (migration `0036`) -- any
  `convergence_events`/`expected_confirmation_events`/
  `convergence_outcome_comparisons` row persisted under the OLD version
  is excluded from a default `argus convergence report` (which queries
  by the current constant) while remaining fully queryable by its own
  unaltered `algorithm_version` for audit.
- `src/argus/cli.py`'s convergence report was separately found, during
  this same recovery, to hardcode the literal string
  `"convergence_negative_evidence_v1"` in its own report dict instead of
  importing the real `ALGORITHM_VERSION` constant -- fixed so the report
  can never silently print a stale version label again.

E. Actual tests run against the corrected implementation

- `tests/integration/test_phase8_convergence_persistence_and_report.py`
  (full file, including this recovery's new point-in-time-cutoff and
  outcome-comparison coverage): passed in isolation against a fresh,
  migrated-to-head throwaway PostgreSQL 16 database.
- Full repository unit suite (`uv run pytest tests/unit -q`): 1124
  passed, 0 failed, at this recovery's final commit.
- `uv run ruff format --check`, `uv run ruff check`, `uv run mypy src`:
  clean across the full repository at this recovery's final commit.
- Migration round-trip (`alembic upgrade head` / `downgrade -1` /
  `upgrade head`) verified against a fresh throwaway PostgreSQL 16
  database through migration `0036`.
- `tests/integration/test_fsr13_contaminated_run_invalidations.py`
  (this recovery's own FSR-13 coverage) independently confirms Phase 8's
  contaminated version is registered with a real reason and superseding
  version, and that a default report excludes it while an explicit
  archival query retrieves it.

F. Environmental limitations (disclosed, not a builder failure)

Same disclosed class as every other phase in this recovery (see the
companion `phase_7_final_recovery.md` section F, not repeated verbatim
here): real local PostgreSQL 16 reachable, PostgreSQL 17 not available
(no Docker daemon; tracked separately under FSR-03); the shared
long-lived `argus` development database accumulated cross-test pollution
over this long session, so every DB-backed assertion above was
independently re-validated against a fresh, isolated, migrated-to-head
throwaway database rather than relying on that shared database's state.

G. Changed/new files (Phase 8 portion of this recovery, FSR-06 + the
   FSR-05-adjacent grant fix + FSR-13's version bump)

Modified: `src/argus/convergence/loaders.py`, `service.py`,
`persistence.py`, `src/argus/cli.py` (convergence report section).
New: `src/argus/convergence/outcome_comparison.py`,
`src/argus/domain/convergence_outcome_comparisons.py`,
`migrations/versions/0031_fsr05_fix_phase7_11_ingest_write_grants.py`,
`migrations/versions/0032_fsr06_convergence_outcome_comparisons.py`.

Untouched (preserved byte-for-byte): all Phase 0-6 checkpoint/bundle
files; `MASTER_SPEC.md`; `orchestration/AUDITOR_POLICY.md`;
`orchestration/PROTOCOL.md`; migrations `0001` through `0030` (never
rewritten).

H. Acceptance statement

This document records that the Phase 8 point-in-time leak and missing
outcome-comparison layer (FSR-06), the Phase 7-11 grant-direction defect
(discovered and fixed alongside FSR-05), and the algorithm-version
invalidation (FSR-13) were identified and repaired, with real tests
passing against the corrected implementation, as part of the
`argus-final-spec-recovery-001` authorized recovery. It does NOT assert
a contemporaneous orchestrator STOP/independent audit occurred for
original Phase 8 or for this recovery. Final acceptance of the full
recovery contract is recorded separately, per FSR-15/16.

I. Next action

No STOP is issued by this document. Historical-record-keeping only, per
FSR-14. Recovery work on the remaining FSR-01..16 items continues.

================ END ARGUS CHECKPOINT =========================
