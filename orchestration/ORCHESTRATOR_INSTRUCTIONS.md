# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except for the explicit operational-protocol decisions stated
here.

---

INSTRUCTION_ID: argus-watcher-remediation-003
ISSUED_AT: 2026-08-31T03:24:15Z
TARGET_COMMIT: 34930bfa78cd7f667527b40f7d006c923c7c9ba6
AUTHORIZED_ACTION: REMEDIATE_ORCHESTRATION_WATCHER_ONLY
AUTHORIZED_PHASE: 0
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

- Phase 0 remains acceptable as
  `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` remains open and
  must be completed against real PostgreSQL 17 before live readiness.
- Watcher remediation round 2 at the audited target commit is REJECTED.
  Many requested protections are real and useful, but several fail-open and
  replay paths remain. The implementation does not yet satisfy the required
  deterministic, restart-safe, idempotent, fail-closed standard.
- Phase 1 is NOT authorized.
- Do not change `last_orchestrator_approved_phase`, `approved_commit`, or
  begin Phase 1 work.

## Scope

Remediate only the GitHub orchestration protocol, local watcher, watcher
tests, and directly related operational documentation/evidence. Do not
change MASTER_SPEC.md or ARGUS application architecture. Allowed files are:

- `scripts/argus_orchestrator_watch.py`
- `tests/unit/test_orchestrator_watch.py`
- `orchestration/PROTOCOL.md`
- `docs/OPERATIONS.md`
- `docs/DECISION_LOG.md`
- the operational-tooling note in `docs/BUILD_STATE.md`
- a new checkpoint, bundle, and `orchestration/AGENT_HANDOFF.md`

If a required safety fix cannot be completed in this scope, return
`STATUS: PARTIAL` and stop. Do not broaden scope silently.

## Defects independently reproduced

### 1. A self-authored next instruction can launch on the next tick

The round-2 regression test is not adversarial enough. It gives the
self-authored instruction an old target, while also changing another file.
That fails target-diff scope, but a realistic bypass remains:

1. During an authorized run, the implementation agent commits its work and
   evidence.
2. It then makes a final commit that changes only the orchestrator
   instruction file.
3. That self-authored instruction targets the immediately preceding
   implementation commit and contains otherwise valid next-phase metadata.
4. The current run correctly fails because the instruction bytes changed.
5. On the next tick, the new instruction ID differs from the failed run's
   ID; its target is an ancestor and only the instruction file differs.
   Current target and phase checks therefore allow it to launch.

This violates the requirement that a self-authored instruction can never
launch.

Implement both protections:

- A detected implementation-agent modification of the instruction file is a
  terminal trust breach, not an ordinary retryable failure. Persist a
  distinct fail-closed/quarantined state. No later ACTIVE instruction,
  regardless of ID or target, may launch automatically from that state.
  Recovery requires explicit human/operator restoration and a deliberate
  local reset procedure documented in OPERATIONS.md.
- Tighten ordinary target provenance: an ACTIVE instruction must be
  introduced by exactly one instruction-only commit whose parent is the
  exact `TARGET_COMMIT`. Reject target-equals-HEAD, multiple commits between
  target and HEAD, merge commits, or any changed path other than the
  instruction file.

Do not claim that unsigned Git commits authenticate the orchestrator.
Document the remaining file-trust boundary honestly. Do not add a new API,
service, or paid system.

### 2. Safety-critical Git command errors still fail open

Several helpers collapse Git errors into empty results. Examples:

- a failed commit-body/log read becomes an empty list, so commit attribution
  can pass without checking any commit;
- a failed merge-query can pass as “no merges”;
- a failed status command can look like a clean worktree;
- a failed diff can look like “no unexpected paths”;
- a failed range enumeration can still allow the final head to count as the
  only run commit.

Refactor safety-critical Git reads to return explicit success/error results
or raise a controlled verification error. Every nonzero exit, timeout,
unparseable result, missing expected record, or ambiguous condition must
fail the current check. Never treat command failure as empty/clean/absent.

### 3. Commit-message attribution does not require a real trailer

The code accepts the expected text on any line anywhere in a commit body.
A prose paragraph can contain the exact line and pass without a Git trailer.

Require exactly one parsed terminal trailer with key
`ARGUS-INSTRUCTION-ID` and exact value equal to the active instruction ID.
Use `git interpret-trailers --parse` or an equivalently strict parser.
Reject a matching line in ordinary body prose, duplicate trailers,
conflicting trailers, extra whitespace/value text, or an absent trailer.

### 4. Launch failures and diagnostics are not fully safe

Only timeout and `OSError` are converted immediately to FAILED. An
unexpected `Exception` from the launch wrapper leaves the state RUNNING
until a later tick, and an interactive `--once` run can exit without
persisting FAILED. Catch all ordinary launch exceptions, persist FAILED
immediately, and never run success verification afterward.

Do not log Claude stdout/stderr. Truncation is not credential redaction.
A secret in the first 300 characters is still leaked. Log only safe,
whitelisted metadata such as exit code, timeout duration, and exception
class. Sanitize control characters/newlines in every log detail so process
output cannot forge watcher log entries.

### 5. Timestamp validation is only a shape check

The regular expression accepts impossible values such as month 99, hour 99,
or invalid calendar dates. Parse the timestamp with a real UTC datetime
parser and require canonical `YYYY-MM-DDTHH:MM:SSZ` round-trip form.

Apply real timestamp validation to ACTIVE instructions and new handoffs.

### 6. Evidence linkage is too weak

The bundle validator checks only that some checkpoint markers and a few
words occur. It does not prove the bundle contains the exact checkpoint
named by the handoff. Require exact embedded checkpoint bytes or an
unambiguous cryptographic digest/linkage and reject a bundle containing a
different valid checkpoint.

Tighten semantic validation without turning Markdown into a large parser:

- checkpoint `STATUS` and `GIT_COMMIT` must each occur exactly once;
- checkpoint commit must be a full SHA and a run commit;
- handoff `CURRENT_PHASE` must be a recognized exact phase token and match
  the authorized scope;
- handoff timestamp must be real canonical UTC;
- handoff `WORKING_TREE` must state clean and the mechanical Git check must
  independently confirm it;
- required handoff section headings from PROTOCOL section 5 must each exist;
- reject contradictory duplicate checkpoint identity/status fields.

## Mandatory adversarial regression tests

Retain all useful existing tests and add tests proving at least:

1. A run writes a self-authored next instruction in a final instruction-only
   commit, targets the immediately preceding implementation commit, uses
   valid predecessor approval, and exits. The first tick enters terminal
   trust-breach state and the second and all later ticks never launch it.
2. Terminal trust-breach recovery cannot happen merely because a new
   instruction ID appears.
3. Target equal to HEAD is rejected for ACTIVE instructions.
4. More than one commit between target and instruction HEAD is rejected.
5. The exact valid case—one instruction-only commit directly atop target—is
   accepted as a negative control.
6. A failed `git log`/commit-body read fails attribution.
7. A failed merge enumeration fails attribution.
8. A failed `git status` never counts as clean.
9. A failed `git diff` never counts as no drift.
10. A failed run-range enumeration fails handoff verification.
11. The exact instruction text in ordinary commit-body prose but not as a
    terminal trailer is rejected.
12. Duplicate or conflicting instruction trailers are rejected.
13. One exact terminal trailer is accepted.
14. A launch wrapper raising `RuntimeError` immediately persists FAILED,
    including in `--once` behavior.
15. Claude stdout/stderr containing a fake credential and embedded newline
    never appears in the watcher log.
16. Impossible but shape-matching instruction timestamps are rejected.
17. Impossible but shape-matching handoff timestamps are rejected.
18. A bundle containing a different structurally valid checkpoint is
    rejected.
19. Missing required handoff section headings are rejected.
20. Invalid/contradictory checkpoint status or commit fields are rejected.
21. All prior mandatory regression categories remain passing.
22. A complete valid same-phase remediation run still reaches COMPLETED.

Use real temporary Git repositories for Git behavior. The Claude subprocess
must remain mocked. Where command-failure injection is required, inject a
narrow deterministic failing command result while retaining a real
temporary repository for the surrounding scenario.

## Required validation and evidence

Run and record exact results for:

- `uv run pytest tests/unit/test_orchestrator_watch.py -v`
- `uv run pytest --cov --cov-report=term-missing`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- `uv run mypy scripts/argus_orchestrator_watch.py --ignore-missing-imports`

Create new immutable evidence:

- `orchestration/checkpoints/watcher_remediation_3.md`
- `orchestration/bundles/watcher_remediation_3.txt`

Update the handoff with:

- a new unique handoff ID;
- exact last-instruction ID `argus-watcher-remediation-003`;
- the new evidence paths;
- honest failures, limitations, and deferred checks;
- Phase 1 still blocked;
- the real Claude CLI launch limitation and PG17 validation listed
  separately.

Every commit created for this run must contain exactly one valid terminal
trailer whose value is `argus-watcher-remediation-003`.

Commit and push to `claude/argus-folder-setup-77ahrk`. Verify remote HEAD
equals local HEAD and the worktree is clean. Then STOP. Do not begin Phase 1.
Do not modify this instruction file. Do not perform or authorize any live
trade, mainnet canary, credential entry, paid-provider upgrade, live arming,
threshold relaxation, or phase skip.
