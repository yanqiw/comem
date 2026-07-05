# Local Codex Loop Detailed Design

## Status

Implementation started. Fake adapter and run binding API are the first
milestone.

## Related records

- [Agent Coordinator Loop Design Principles](agent-coordinator-loop-principles.md)
- [Concepts and governance model](../concepts.md)
- [Tool reference](../tools.md)

## Purpose

This design turns the local-only coordination loop principle into an
implementation shape. The first release should prove that Coordination Memory
can schedule first-class local Codex conversations, keep those runs visible in
the ledger, and prevent review handoffs from being forgotten.

The design is intentionally local-only, but the internal boundaries match a
future cloud control plane plus local connector. The transport can change later;
the assignment contract, run binding, command envelope, and prompt envelope
should not.

## Codex Conversation Interaction

When Codex creates a Coordination Memory workspace, team, and assignments from a
plan, it should ask the user to choose an execution mode before starting work:

```text
已创建 <N> 个 comem tasks。请选择执行模式：

A. Codex subagent 模式（默认）
当前 Codex 作为 Integrator，启动 Codex subagents 执行任务；comem 记录
task/run/handoff/review，并在 dashboard 展示看板。

B. comem loop 模式
Codex 自动执行 comem loop；由 loop claim task 并启动 worker conversation。
```

The default mode is `codex_subagent`, because it preserves the fastest Codex
user experience. In this mode, claim metadata records the parent Codex thread
and subagent name when available:

```json
{
  "session_kind": "codex_subagent",
  "session_ref": "<parent-codex-thread-id>",
  "metadata": {
    "execution_mode": "codex_subagent",
    "parent_thread_id": "<parent-codex-thread-id>",
    "subagent_name": "<codex-worker-nickname>",
    "managed_by": "codex_goal"
  }
}
```

The explicit loop mode is `comem_loop`. Codex should start with a dry-run using
the same database as the MCP server and dashboard:

```bash
COORDINATION_MEMORY_DB=<stable-db-path> \
comem loop --workspace <workspace_id> --team <team_id> --adapter <adapter> --dry-run --once
```

If the dry-run selects the expected tasks, Codex may start one pass or a polling
loop:

```bash
COORDINATION_MEMORY_DB=<stable-db-path> \
comem loop --workspace <workspace_id> --team <team_id> --adapter <adapter> --once

COORDINATION_MEMORY_DB=<stable-db-path> \
comem loop --workspace <workspace_id> --team <team_id> --adapter <adapter> --poll-interval 30
```

Use `fake` for deterministic local validation and `codex-app-server` only when
the local Codex app-server bridge is available. Run at most one active loop per
team/database unless the Integrator deliberately shards work.

## Goals

- Run a local `comem loop` process against the existing SQLite-backed
  Coordination Memory store.
- Select eligible assignments and start or resume first-class Codex threads.
- Preserve the current governance model: workers propose; integrators accept,
  reject, or request fixes.
- Store enough run binding data for the loop to find and message the right
  Codex thread after restart.
- Use append-only events for observed progress, handoffs, review nudges, and
  recovery evidence.
- Keep durable project context in repository Markdown; store only pointers and
  lifecycle state in Coordination Memory.
- Shape the local interfaces so a later cloud service can replace the scheduler
  transport without changing worker prompts.

## Non-goals

- Do not build a cloud service in the first release.
- Do not build a remote connector or network transport in the first release.
- Do not expose Codex app-server directly to the network.
- Do not make the dashboard an execution engine.
- Do not auto-accept worker handoffs.
- Do not store full plans, design documents, secrets, auth tokens, or
  credential-bearing logs in Coordination Memory.
- Do not force all work through `comem loop`. Codex subagent mode is the default
  interaction path; loop mode is an explicit scheduling path.
- Do not pretend Codex subagents are independently addressable first-class
  Codex threads when only the parent thread and subagent nickname are known.

## Architecture

```text
comem loop
  Scheduler
    reads boards, pending reviews, active runs
    emits local command envelopes

  Command journal
    records command ids and outcomes as ledger events
    provides idempotency across loop restarts

  Codex adapter
    talks to local Codex app-server
    creates/resumes threads and starts/steers turns

  Prompt builder
    renders assignment and review prompt envelopes
    references project Markdown instead of copying it

  Run observer
    converts Codex notifications and polling results into heartbeats/events

  Review nudge worker
    finds pending review events
    nudges or starts an integrator Codex thread

Coordination Memory ledger
  stores workspace/team/assignment/run/event state
  remains the source of coordination truth

Project repository
  stores design, plan, context, and accepted artifacts
```

The local scheduler and local adapter can live in one process for the first
release. They should still communicate through explicit command envelopes so a
future cloud gateway can reuse the same adapter contract.

## Components

### Loop CLI

Add a local execution command:

```bash
comem loop --workspace example-workspace --team coordination-memory-loop --adapter codex-app-server
```

Initial flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--workspace` | none | Limit scheduling to one workspace. |
| `--team` | none | Limit scheduling to one team. |
| `--adapter` | `codex-app-server` | Choose the local agent adapter. |
| `--poll-interval` | `10` | Seconds between scheduler passes. |
| `--max-concurrent-runs` | `1` | Local Codex worker concurrency. |
| `--review-nudge-interval` | `60` | Seconds between review queue checks. |
| `--dry-run` | `false` | Print selected commands without invoking Codex. |

The CLI should refuse to run unless the configured database is reachable and
the Codex adapter reports the required capabilities.

### Scheduler

The scheduler is a deterministic planner over ledger state. It does not run
shell commands directly and does not mutate project files.

Responsibilities:

- Read eligible assignments from the selected team board.
- Skip assignments with terminal status.
- Skip assignments leased by another live actor.
- Re-read assignment detail before every claim to get the current revision.
- Emit a `start_assignment` command for unclaimed work.
- Emit a `resume_assignment` command for runs that are still owned by this loop
  but have no recent heartbeat.
- Emit a `nudge_review` command for pending handoffs that lack a review.
- Emit an `interrupt_run` command only for explicit cancellation, supersede, or
  human-approved stop flows.

The scheduler should use stable ordering: priority first, then oldest updated
time, then assignment id. This makes behavior explainable and testable.

### Command Journal

Every loop action gets a stable `command_id`:

```text
cmd_<command_type>_<assignment_id>_<revision_or_event_id>_<attempt>
```

The loop records command dispatch and completion as events. The event payload
must include the command id, command type, target assignment or event, adapter
kind, and result summary. It must not include secrets.

Example:

```json
{
  "command_id": "cmd_start_assignment_task_abc_rev7_attempt1",
  "command_type": "start_assignment",
  "adapter_kind": "codex_app_server",
  "result": "thread_started",
  "thread_id": "019f2093-3b06-7310-bc1f-08ccc3e4f917"
}
```

This journal gives the later cloud service a clean replay model. If the loop
crashes after creating a Codex thread but before starting the turn, the next
pass can inspect the command event and continue instead of creating duplicate
threads.

### Codex Adapter

The first adapter targets local Codex app-server.

Required capabilities:

- Start an empty thread.
- Resume an existing thread by id.
- Start a turn with text input.
- Steer an active turn with a precondition on the expected turn id.
- Interrupt a turn by thread id and turn id.
- Read thread status and recent turns.
- Stream or poll turn completion.

Codex app-server JSON-RPC mapping:

| Adapter method | App-server method |
| --- | --- |
| `start_thread` | `thread/start` |
| `resume_thread` | `thread/resume` |
| `read_thread` | `thread/read` |
| `list_turns` | `thread/turns/list` |
| `list_turn_items` | `thread/turns/items/list` |
| `start_turn` | `turn/start` |
| `steer_turn` | `turn/steer` |
| `interrupt_turn` | `turn/interrupt` |

The adapter should prefer stdio or a local Unix socket. WebSocket can be
considered later for connector mode, but the local loop should not expose it to
remote callers.

### Prompt Builder

The prompt builder renders a compact assignment envelope:

```text
You are Codex worker actor codex-worker-7.
Your assignment is task_abc in workspace example-workspace.

Read context in this order:
1. docs/design/local-codex-loop-detailed-design.md#Assignment Contract
2. docs/design/agent-coordinator-loop-principles.md#Core principle

Use Coordination Memory:
- Register actor codex-worker-7 if needed.
- Confirm assignment detail and current revision.
- Heartbeat while working.
- Submit a handoff when complete.
- Do not accept your own work.

Allowed paths:
- coordination-memory-mcp/**

Acceptance criteria:
- The loop starts a first-class Codex thread.
- The run stores Codex session binding.
- Pending review work is nudged to an integrator.
```

The prompt must include enough detail for the worker to execute without copying
full design or plan content into the ledger.

### Run Observer

The observer translates adapter state into ledger state.

Minimum behavior:

- When a turn starts, record the turn id in the run communication cursor.
- While a turn is active, emit heartbeat evidence on a bounded interval.
- When a turn completes, inspect the ledger. If the worker submitted a handoff,
  stop sending worker prompts. If the worker completed without handoff, nudge
  the same thread to submit a proper handoff.
- If the adapter reports an error, append an observed event and leave the
  assignment claim intact until the lease expires or an integrator supersedes
  it.

The observer should not infer accepted state from Codex output. Acceptance still
comes only from integrator review events.

### Review Nudge Worker

The review nudge worker prevents the `awaiting_review` lane from becoming a
dead end.

Behavior:

- Poll `list_pending_reviews`.
- Group pending handoffs by workspace and team.
- For each team, find or create an integrator Codex thread.
- Send a review prompt that points at pending event ids and asks for an
  explicit decision: accept, needs_fix, reject, follow-up assignment, or human
  intervention.
- Do not send a duplicate nudge for the same event while an active integrator
  turn is already reviewing it.

The integrator thread performs the review through existing Coordination Memory
tools. The loop only nudges; it does not decide.

## Data Contracts

### Assignment Contract

Assignment metadata should carry task contract fields that the worker needs to
begin:

```yaml
metadata:
  context_refs:
    - path: docs/design/local-codex-loop-detailed-design.md
      read:
        - Purpose
        - Assignment Contract
  requested_capabilities:
    - codex_thread
    - repository_edit
  preferred_provider: codex
  session_bind:
    target_actor_id: codex-worker-7
    status: pending
    session_kind: codex_thread
  execution:
    key_files:
      - src/coordination_memory_mcp/cli.py
      - src/coordination_memory_mcp/store.py
    risk_notes:
      - Do not store Codex auth tokens in the ledger.
```

The assignment contract is durable intent. `session_bind` names the intended
worker target before any run exists; it should not store runtime thread ids or
adapter cursors.

### Actor Profile

The loop registers local actors for the node and for each worker or integrator
identity it manages:

```yaml
actor_id: codex-worker-7
actor_kind: ai
provider: codex
status: active
capabilities:
  adapter_kind: codex_app_server
  can_start_thread: true
  can_resume_thread: true
  can_steer_turn: true
  local_only: true
```

Actor profiles describe long-lived capability. They do not claim work by
themselves.

### Run Binding

The run binding describes one execution attempt.

Existing run columns should be used first:

```yaml
run_id: run_123
assignment_id: task_abc
actor_id: codex-worker-7
session_kind: codex_thread
session_ref: 019f2093-3b06-7310-bc1f-08ccc3e4f917
interactive_url: codex://threads/019f2093-3b06-7310-bc1f-08ccc3e4f917
worktree_path: /workspaces/coordination-memory-mcp
branch: dev
base_commit: a63a2bd3dbb3787b52b3cc644449d76979191f63
```

Run metadata should carry adapter details and the communication cursor:

```yaml
metadata:
  adapter:
    kind: codex_app_server
    version: 0.142.5
    transport: stdio
  communication_cursor:
    last_command_id: cmd_start_assignment_task_abc_rev7_attempt1
    last_client_user_message_id: msg_task_abc_rev7_start
    last_seen_turn_id: turn_456
    last_completed_turn_id: turn_456
    last_loop_check_at: "2026-07-02T10:30:00+08:00"
```

Current storage already has `runs.metadata_json`, but `claim_assignment` does
not expose a way to populate or update it. The implementation should add a
small run-binding update path rather than overloading assignment metadata.

Recommended tool shape:

```text
record_run_binding(
  run_id,
  actor_id,
  actor_role,
  binding_patch,
  event_payload
)
```

Rules:

- The caller must own the active run or act as integrator.
- The method updates only run metadata and appends an observed event.
- It never changes accepted state.
- It rejects terminal runs.
- It redacts or rejects secrets.

### Command Envelope

Command envelopes are the boundary between scheduling and execution.

```yaml
command:
  command_id: cmd_start_assignment_task_abc_rev7_attempt1
  command_type: start_assignment
  workspace_id: example-workspace
  team_id: coordination-memory-loop
  assignment_id: task_abc
  assignment_revision: 7
  target_actor_id: codex-worker-7
  adapter_kind: codex_app_server
  idempotency_key: task_abc:7:start:1
  prompt_kind: worker_assignment
```

Supported command types for the local release:

| Command | Purpose |
| --- | --- |
| `start_assignment` | Create a Codex thread, claim the assignment, and start the worker turn. |
| `resume_assignment` | Rejoin a known thread and nudge stalled owned work. |
| `nudge_review` | Send pending handoffs to an integrator thread. |
| `interrupt_run` | Stop an active turn after explicit cancellation or supersede. |
| `refresh_capabilities` | Re-probe the local Codex adapter and update actor status. |

## Lifecycle

### Starting Worker Work

```text
1. Scheduler selects assignment task_abc at revision 7.
2. Scheduler emits start_assignment command.
3. Adapter starts an empty Codex thread.
4. Loop claims task_abc as codex-worker-7 with session_ref set to the thread id.
5. Loop records run binding metadata and command dispatch.
6. Adapter starts a turn with the worker prompt envelope.
7. Observer records the turn id in the communication cursor.
8. Worker heartbeats and submits handoff through Coordination Memory.
9. Assignment moves to awaiting_review.
10. Review nudge worker sends pending review to an integrator thread.
```

The ordering matters. Starting an empty Codex thread before claiming lets the
loop include `session_ref` in the claim without asking Codex to act before a
lease exists. If the claim fails, the loop archives the empty thread and records
the failed command.

### Resuming Owned Work

```text
1. Loop restarts.
2. Scheduler reads active assignments with claimed_by matching local actors.
3. Scheduler reads run binding and communication cursor.
4. Adapter resumes session_ref.
5. If a turn is active, observer watches it and avoids duplicate prompts.
6. If no turn is active and no handoff exists, scheduler sends a resume nudge.
```

Resume prompts must include the last known command id and ask the worker to
inspect assignment detail before doing more work.

### Review Nudge

```text
1. Review nudge worker reads pending review events.
2. It checks command journal for an existing active nudge for each event id.
3. It starts or resumes the team integrator Codex thread.
4. It sends a review prompt listing event ids and required decisions.
5. Integrator records decisions using existing review tools.
```

The loop never writes `integrator_accepted`, `integrator_rejected`, or
`needs_fix` on behalf of the integrator unless the integrator thread explicitly
uses the review tools.

## Idempotency And Recovery

### Duplicate Thread Prevention

The loop must check for an existing successful `start_assignment` command event
before starting a new thread for the same assignment revision. If a command
event has a thread id but no run binding, the loop attempts to bind that thread
before creating another one.

### Duplicate Prompt Prevention

Use `clientUserMessageId` when calling Codex `turn/start` or `turn/steer`.
Persist that value in the run communication cursor. On retry, the loop compares
the planned message id with the cursor and thread history before sending.

### Active Turn Safety

Use Codex `turn/steer` only when the loop knows the active turn id and can pass
it as `expectedTurnId`. If the expected turn no longer matches, re-read thread
state and decide again.

### Lease Expiry

If a lease expires and the Codex thread still appears active, the loop should
not blindly take over. It appends an observed stale-run event and lets the
scheduler decide whether to resume as the same actor, supersede, or request
human intervention.

### Process Restart

All state needed to resume should be recoverable from:

- assignments and active run ids,
- run binding fields,
- run metadata cursor,
- command journal events,
- Codex thread state.

The loop should not require an in-memory queue to recover correctness.

## Error Handling

| Failure | Handling |
| --- | --- |
| Codex app-server unavailable | Mark adapter unavailable, append observed event, skip scheduling. |
| Thread start succeeds but claim fails | Archive empty thread if possible, append failed command event. |
| Claim succeeds but turn start fails | Keep run binding, append observed event, retry with same command id. |
| Codex turn completes without handoff | Send one resume nudge asking for a handoff, then escalate if still missing. |
| Assignment revision is stale | Re-read assignment detail and rebuild command if still eligible. |
| Another actor holds live lease | Skip the assignment. |
| Pending review is repeatedly ignored | Nudge integrator, then request human intervention after configured attempts. |
| Secret-like payload detected | Reject the event or redact before storage, then request human intervention. |

## Security And Trust Boundaries

- Codex app-server access stays local to the user machine.
- The loop must not store Codex auth files, app-server tokens, API keys, cookie
  material, or credential-bearing logs.
- `interactive_url` should use a non-secret deep link such as
  `codex://threads/019f2093-3b06-7310-bc1f-08ccc3e4f917`.
- High-risk actions still require explicit human approval: deployment, Git
  push, ACR build, Secret changes, live cluster mutation, and destructive file
  operations.
- The loop should pass the narrowest useful workspace root and sandbox settings
  to Codex.
- Workers cannot accept their own handoffs.

## Cloud-Ready Shape

The local loop should be built as if a future cloud control plane will send the
same command envelopes to a local connector.

Future mapping:

| Local-only | Future service mode |
| --- | --- |
| Scheduler in `comem loop` | Cloud scheduler |
| Local command envelope queue | Cloud connector stream |
| Codex adapter in same process | Local connector Codex adapter |
| SQLite ledger | Cloud ledger or replicated ledger |
| Local command journal event | Cloud command acknowledgement |

The future connector should initiate outbound connections, tolerate network
interruption, and replay idempotent commands after reconnecting. None of that is
implemented in phase one, but the local command envelope and run cursor make it
possible without changing worker prompts.

## Required Store And Tool Changes

The current model already supports most of the design:

- `claim_assignment` records `session_kind`, `session_ref`,
  `interactive_url`, `worktree_path`, `branch`, and `base_commit`.
- `runs` already has `metadata_json`.
- `heartbeat_run`, `append_event`, `submit_handoff`, and review tools already
  support the core lifecycle.

Small additions needed:

1. Normalize loop-managed assignment metadata so `metadata.session_bind` is
   present when the integrator provides a target actor hint.
2. Make the loop choose `metadata.session_bind.target_actor_id` before falling
   back to generated worker ids.
3. Add a way to update run binding metadata and append a corresponding event.
4. Expose run metadata updates through MCP only for the run owner or an
   integrator.
5. Add event types for loop command dispatch, command completion, adapter
   availability, and review nudge dispatch.
6. Add `comem loop` CLI configuration and adapter capability probing.

## Testing Strategy

Unit tests:

- Command selection skips leased, terminal, and stale assignments.
- Command ids are stable across repeated scheduler passes.
- Prompt builder includes context refs, allowed paths, and acceptance criteria.
- Run binding update rejects non-owners and terminal runs.
- Review nudge worker does not duplicate active nudges.

Adapter tests:

- Fake Codex adapter supports start, resume, turn start, steer, interrupt, and
  read operations.
- Loop retries use the same `clientUserMessageId`.
- Active turn mismatch causes re-read instead of blind steering.

Store tests:

- `create_assignment` derives `metadata.session_bind` from legacy
  `assigned_actor_hint` and preserves explicit session bindings.
- `record_run_binding` updates only run metadata and appends an observed event.
- Metadata survives `get_run_detail`.
- Secret-like payloads are rejected or redacted according to existing policy.

Integration smoke tests:

- Create a test assignment, run the loop with a fake adapter, and verify claim,
  run binding, heartbeat, handoff, and pending review.
- Run dry-run mode and verify no Codex thread is started.
- With a real local Codex adapter behind an opt-in test, verify `initialize`,
  `thread/start`, `turn/start`, and `thread/read` work.

## Acceptance Criteria

- `comem loop --dry-run` prints eligible commands without mutating assignments.
- Dry-run command selection uses `metadata.session_bind.target_actor_id` when
  present.
- A fake adapter end-to-end test starts a worker run and reaches
  `awaiting_review`.
- Run detail shows `session_kind=codex_thread`, `session_ref`, and adapter
  cursor metadata.
- The same scheduler pass repeated twice does not create duplicate command
  events or duplicate thread starts.
- Pending handoffs trigger an integrator review nudge, not an automatic accept.
- Local-only implementation has no network listener and does not expose Codex
  app-server remotely.
- The design remains compatible with a later cloud connector that transports
  the same command envelopes.

## Implementation Phasing

### Phase 1: Fake Adapter Loop

Build the scheduler, command envelope, prompt builder, and fake adapter. This
proves the ledger state machine without touching Codex.

### Phase 2: Run Binding Metadata

Add the run metadata update path and events needed for communication cursors.
Surface the metadata in `get_run_detail` and the dashboard.

### Phase 3: Local Codex App-Server Adapter

Implement the stdio app-server client and map adapter methods to JSON-RPC.
Keep this opt-in and local-only.

### Phase 4: Review Nudge

Create or resume a team integrator Codex thread and send pending review prompts.
Keep decisions in the integrator review tools.

### Phase 5: Hardening

Add restart recovery, duplicate prevention, stale run handling, and opt-in real
Codex smoke tests.

## Deferred Decisions

- Whether `record_run_binding` should use assignment revision or a new run
  revision for optimistic concurrency.
- Whether integrator threads are one per team, one per workspace, or one per
  loop process.
- Whether the dashboard should show loop commands as a separate timeline
  section or only as normal events.
- Whether `codex exec` should be a fallback adapter after app-server support is
  proven.
