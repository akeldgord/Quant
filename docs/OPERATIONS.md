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
  (`IDLE` / `CLAIMED` / `RUNNING` / `COMPLETED` / `FAILED`), which
  instruction ID was last processed, and which one (if any) is in flight.
  Gitignored; written atomically. If you need to reset a `FAILED` state to
  let the watcher retry a specific instruction, that's a deliberate manual
  edit — the watcher never blindly retries on its own (see
  `orchestration/PROTOCOL.md` section 4).
- `runtime/orchestrator_watcher.lock` — flock-based single-instance lock.
  A second watcher process started while one is already running exits
  immediately with a message on stderr. The lock releases automatically if
  the process crashes (kernel-managed, no stale-lock cleanup needed).
- `runtime/logs/orchestrator_watcher.log` — append-only event log
  (`WATCHER_STARTED`, `NEW_INSTRUCTION`, `DIRTY_WORKTREE`,
  `GIT_PULL_FAILED`, `TARGET_COMMIT_MISMATCH`, `CLAUDE_STARTED`,
  `CLAUDE_EXITED`, `HANDOFF_VERIFIED`, `RUN_COMPLETED`, `RUN_FAILED`, ...).
  Never contains API keys, tokens, credentials, or raw environment/command
  dumps — only short structured event lines.

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
