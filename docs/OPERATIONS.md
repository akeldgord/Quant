# ARGUS Operations

This document is populated incrementally as operational tooling actually
gets built (MASTER_SPEC.md section 101 / CORE-011 — no content ahead of
what exists). Currently covers: the local orchestrator watcher.

## Local orchestrator watcher

`scripts/argus_orchestrator_watch.py` lets the human operator stop manually
starting Claude for each ARGUS phase. It polls this repository for a new
`ACTIVE` instruction in `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` and,
when one appears (and passes the checks in `orchestration/PROTOCOL.md`
sections 6-7), launches the local Claude CLI non-interactively to execute
exactly that instruction. Full behavior is documented in
`orchestration/PROTOCOL.md`; this page is about running it.

It is stdlib-only Python — no Celery/Redis/Kafka, no systemd dependency in
the code itself, no Docker daemon dependency, no new external service. Just
`git` subprocess calls, a JSON state file, an flock-based single-instance
lock, and a subprocess launch of the Claude CLI.

### Run in the foreground

```bash
make orchestrator-watch
```

equivalent to:

```bash
uv run python scripts/argus_orchestrator_watch.py
```

Stop it with Ctrl-C (SIGINT) — it finishes the current tick, releases its
lock, and exits cleanly. `SIGTERM` behaves the same way.

### Configuration

All flags have environment-variable equivalents so background-start options
below don't need a wrapper script just to set them:

| Flag | Env var | Default |
|---|---|---|
| `--interval SECONDS` | `ARGUS_WATCHER_INTERVAL_SECONDS` | `60` |
| `--branch NAME` | `ARGUS_WATCHER_BRANCH` | `claude/argus-folder-setup-77ahrk` |
| `--claude-bin PATH` | `ARGUS_WATCHER_CLAUDE_BIN` | `claude` |
| `--claude-timeout-seconds N` | `ARGUS_WATCHER_CLAUDE_TIMEOUT_SECONDS` | `3600` |
| `--claude-arg ARG` (repeatable) | — | none |

`--claude-arg` appends raw arguments to the Claude CLI invocation — use it
for whatever permission-mode flag your local Claude CLI needs to run
non-interactively and unattended (this varies by CLI version, so the
watcher doesn't hardcode one). Run `--once` to execute a single tick and
exit, useful for manually testing configuration before leaving it running.

### Pausing

Create `runtime/ORCHESTRATION_PAUSED` (any content, even empty) to pause the
watcher — it will not fetch, pull, or launch Claude while that file exists,
just sleep and check again next tick. Delete the file to resume. This is
the normal way to stop automation without killing the process.

```bash
touch runtime/ORCHESTRATION_PAUSED   # pause
rm runtime/ORCHESTRATION_PAUSED      # resume
```

### State, locking, and logs

- `runtime/orchestrator_watcher_state.json` — current watcher state
  (`IDLE` / `CLAIMED` / `RUNNING` / `COMPLETED` / `FAILED` / `QUARANTINED`
  — see "Terminal trust-breach quarantine" below for the last one), which
  instruction ID was last processed, and which one (if any) is in flight.
  Gitignored; written atomically (with `fsync` on the file and its parent
  directory) so a crash never leaves a half-written state file. Reading is
  strict: a missing, unreadable, corrupt, or schema-invalid state file is
  **never** silently treated as "fresh" while an `ACTIVE` instruction is
  outstanding — see the state-loss handling below. If you need to reset a
  `FAILED` state to let the watcher retry a specific instruction, that's a
  deliberate manual edit — the watcher never blindly retries on its own
  (a retry requires the orchestrator to issue a new `INSTRUCTION_ID`; see
  `orchestration/PROTOCOL.md` section 4).
- **State-loss handling.** If `runtime/orchestrator_watcher_state.json` is
  missing (e.g. `runtime/` was wiped) while
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` has an `ACTIVE` instruction,
  the watcher does not assume this is a first execution. It cross-checks
  `orchestration/AGENT_HANDOFF.md` (tracked in git, so it survives a local
  `runtime/` wipe): if that instruction is already recorded as complete
  there, the watcher marks it processed without relaunching
  (`STATE_REBUILT_FROM_HANDOFF`); otherwise it fails closed
  (`STATE_MISSING_FAIL_CLOSED`) and requires a new `INSTRUCTION_ID` to
  proceed, rather than risk replaying or duplicating a run whose outcome is
  unknown.
- `runtime/orchestrator_watcher.lock` — flock-based single-instance lock.
  A second watcher process started while one is already running exits
  immediately with a message on stderr. The lock releases automatically if
  the process crashes (kernel-managed, no stale-lock cleanup needed).
- `runtime/logs/orchestrator_watcher.log` — append-only event log
  (`WATCHER_STARTED`, `NEW_INSTRUCTION`, `DIRTY_WORKTREE`, `GIT_STATUS_FAILED`,
  `GIT_PULL_FAILED`, `TARGET_COMMIT_MISMATCH`, `PHASE_AUTHORIZATION_INVALID`,
  `STATE_INVALID`, `STATE_MISSING_FAIL_CLOSED`, `STATE_REBUILT_FROM_HANDOFF`,
  `INSTRUCTIONS_INVALID`, `CLAUDE_STARTED`, `CLAUDE_EXITED`,
  `HANDOFF_VERIFIED`, `RUN_COMPLETED`, `RUN_FAILED`,
  `INSTRUCTION_FILE_TRUST_BREACH`, `WATCHER_QUARANTINED`,
  `WATCHER_QUARANTINE_RESET`, `TICK_EXCEPTION`, `WATCHER_PAUSED`,
  `WATCHER_STOPPED`, ...).
  Never contains API keys, tokens, credentials, or raw environment/command
  dumps. Only short, whitelisted, structured event lines are ever written —
  **Claude's own subprocess stdout/stderr is never logged, full stop** (not
  even truncated: truncation bounds length but does not redact a credential
  that happens to appear in the first few hundred characters). A launch
  failure logs only exit code, timeout duration, or the raised exception's
  *class name* — never its message text, and never captured process output.
  Every log detail is additionally sanitized (control characters and
  newlines stripped) so nothing, including a malicious Claude subprocess,
  can forge a fake log line.
- A single bad tick (an unexpected exception anywhere in `tick()`) is caught
  at the `run_forever` loop level and logged as `TICK_EXCEPTION` rather than
  crashing the whole watcher process; `--once` runs let such an exception
  propagate normally, since an operator is watching interactively. (An
  exception specifically from the Claude launch wrapper is different: `tick()`
  itself catches that and persists `FAILED` before returning, in both
  `--once` and `run_forever`, so it never has to rely on this outer
  `run_forever`-only safety net.)

### Terminal trust-breach quarantine

If the watcher ever detects that `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
was modified during a run — by the implementation agent, committed or not —
it does not mark that run an ordinary retryable `FAILED`. It persists a
`QUARANTINED` state (logging `INSTRUCTION_FILE_TRUST_BREACH` then
`WATCHER_QUARANTINED`) and, from then on, **every subsequent tick refuses to
even read `ORCHESTRATOR_INSTRUCTIONS.md`, let alone launch anything** —
regardless of what `INSTRUCTION_ID` or `TARGET_COMMIT` later appears there.
This is deliberate: a self-authored instruction must never be able to
recover automation merely by looking legitimate on a later tick.

Recovery is manual and deliberate:

1. Stop the watcher if it's running in the background.
2. Inspect what actually happened: `git log`, the run's commits, and
   `runtime/logs/orchestrator_watcher.log`'s `INSTRUCTION_FILE_TRUST_BREACH`
   entry (which names the reason). Confirm
   `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` on the remote branch is in
   the state a human orchestrator actually intends.
3. Run:

   ```bash
   uv run python scripts/argus_orchestrator_watch.py --reset-quarantine
   ```

   This refuses to do anything (exit code 1, no state change) unless the
   current state is actually `QUARANTINED`. On success it resets local
   state to fresh `IDLE` and logs `WATCHER_QUARANTINE_RESET` — it does not
   touch `ORCHESTRATOR_INSTRUCTIONS.md`, `AGENT_HANDOFF.md`, or any
   repository content.
4. Restart the watcher normally.

### Running in the background

Two options; neither is installed or enabled automatically — that's a
deliberate choice you make.

**Option A — `nohup` (works everywhere, including plain WSL without a
running systemd):**

```bash
nohup uv run python scripts/argus_orchestrator_watch.py \
  >> runtime/logs/orchestrator_watcher.log 2>&1 &
disown
```

Check it's running: `pgrep -f argus_orchestrator_watch.py`. Stop it:
`pkill -f argus_orchestrator_watch.py` (sends SIGTERM, which the watcher
handles cleanly).

**Option B — user-level systemd** (if systemd is available in your WSL2
distro — check with `systemctl --user status`; not all WSL setups have it).
Example unit, adjust the paths for your machine:

```ini
# ~/.config/systemd/user/argus-orchestrator-watch.service
[Unit]
Description=ARGUS orchestrator watcher

[Service]
WorkingDirectory=%h/path/to/Quant
ExecStart=%h/.local/bin/uv run python scripts/argus_orchestrator_watch.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now argus-orchestrator-watch.service
systemctl --user status argus-orchestrator-watch.service
journalctl --user -u argus-orchestrator-watch.service -f
```

This example is documentation only — nothing in this repository installs
or enables a system service on its own. Set it up yourself if you want it,
and remember `runtime/ORCHESTRATION_PAUSED` still works to pause a
systemd-managed instance without stopping the unit.
