# Agent Coordinator Loop Design Principles

## Status

Draft design record.

## Purpose

Coordination Memory needs a loop that can coordinate agent teams without turning
the SQLite store into a second project memory or a hidden planning system. The
loop should schedule and observe agent work, while durable context stays in the
project repository.

## Core principle

Project Markdown is the source of context and memory. Coordination Memory is the
coordination ledger.

- Design docs, plans, background, decisions, and long-lived project context live
  in repository Markdown files.
- Assignments store enough clues for an agent to find, read, and act on that
  context.
- Runs and events store lifecycle evidence: claims, heartbeats, interventions,
  handoffs, and Integrator review decisions.
- The SQLite database must not duplicate full design or plan documents.

This avoids context forks: Git remains the durable record for project thinking,
and Coordination Memory remains the live state machine for who is doing what and
what has been accepted.

## Target scheduling model

The target architecture is an external Coordination Memory loop that schedules
first-class Codex agent conversations.

```text
Human or planner Codex thread
  writes project Markdown design and plan files
  creates Coordination Memory assignments with context references

comem loop
  owns scheduling, leases, retries, stale detection, and review nudges
  creates or resumes first-class Codex conversations

Codex Integrator thread
  reviews handoffs, creates follow-up work, asks the human when needed

Codex Worker threads
  execute assignments and report lifecycle events through Coordination Memory
```

Codex subagents are not the system-level scheduling primitive. A worker Codex
thread may choose to use Codex subagents internally while executing one
assignment, but the Coordination Memory loop only tracks the worker thread's
assignment lifecycle.

## Agent binding contract

The loop must be able to find, resume, and message the agent that claimed an
assignment. The assignment carries the intended session target before work is
claimed; the run created by `claim_assignment` carries the actual live
conversation binding.

Use three distinct layers:

- Actor profile: long-lived identity and capability information, such as
  `actor_id`, `actor_kind`, provider, status, display name, and capabilities.
- Assignment contract: durable task intent, including the objective,
  `context_refs`, allowed paths, acceptance criteria, any requested
  capabilities or preferred provider, and `metadata.session_bind` for the
  intended target actor.
- Run binding: one execution attempt for one assignment, including the current
  owner and the communication handle needed by the loop.

The minimum assignment-level binding for loop-managed Codex work is:

```yaml
session_bind:
  target_actor_id: codex-worker-7
  status: pending
  session_kind: codex_thread
```

The minimum run binding for Codex should include:

```yaml
run_binding:
  run_id: run_123
  assignment_id: task_abc
  actor_id: codex-worker-7
  session_kind: codex_thread
  session_ref: "<codex-thread-id>"
  interactive_url: "<optional-thread-link>"
  adapter_kind: codex_app_thread_bridge
  worktree_path: "/absolute/path/to/worktree"
  branch: "codex/task-abc"
  base_commit: "<starting-commit>"
  lease_expires_at: "..."
  heartbeat_at: "..."
```

For reliable loop operation, the binding also needs an idempotent communication
cursor. This can start in run metadata and later become first-class fields:

```yaml
communication_cursor:
  adapter_version: "v1"
  last_sent_message_id: "<adapter-message-id>"
  last_seen_message_id: "<adapter-message-id>"
  last_loop_instruction_event_id: "evt_..."
  last_loop_check_at: "..."
```

The invariant is: assignment describes what must be done; run describes who is
doing this attempt and how the loop can communicate with that agent. A
`claimed_by` value alone is not enough for scheduling because it does not tell
the loop how to wake, resume, inspect, or safely avoid duplicate messages to a
first-class agent conversation.

## Assignment context contract

An assignment should reference context rather than embed it:

Paths in `context_refs` are relative to the project root used by that
assignment's workspace. In this repository, callers may still choose to store
superproject-relative paths when they intentionally coordinate across modules.

```yaml
assignment_id: codex-thread-adapter-v1
workspace_id: example-workspace
team_id: coordination-memory-loop
allowed_paths:
  - coordination-memory-mcp/**
context_refs:
  - path: docs/design/agent-coordinator-loop-principles.md
    read:
      - Core principle
      - Target scheduling model
  - path: docs/superpowers/plans/2026-07-02-comem-loop.md
    read:
      - Phase 1
      - Acceptance criteria
acceptance_criteria:
  - Worker thread receives the assignment envelope.
  - Worker thread claims, heartbeats, and submits a handoff.
  - The handoff appears in the Integrator review queue.
```

The `context_refs` shape can live in assignment metadata initially. It should be
treated as a pointer contract, not as copied project knowledge.

## Agent prompt envelope

The loop should start each worker with a consistent prompt envelope:

```text
You are worker agent <actor_id>.
Your assignment is <assignment_id>.

Read context in this order:
1. <path>#<section>
2. <path>#<section>

Use Coordination Memory:
- Claim the assignment with the current base_revision.
- Heartbeat while working.
- Submit a handoff when complete.
- Do not accept your own work.

Allowed paths:
<allowed_paths>

Acceptance criteria:
<acceptance_criteria>
```

Integrator prompts use the same idea, but point at pending review events and
ask for an explicit `accept`, `needs_fix`, `reject`, follow-up assignment, or
human intervention.

## Codex communication boundary

The loop needs a Codex thread adapter. In a Codex app environment, this adapter
may be able to create, read, and message first-class Codex conversations. In a
headless CLI environment, those capabilities may not exist.

The product must represent that difference explicitly:

- If a Codex thread bridge is available, `comem loop` may create or resume
  first-class Codex worker and Integrator conversations.
- If no thread bridge is available, `comem loop` must report the missing
  capability or use a different runner mode. It must not pretend that a normal
  process is an interactive Codex conversation.

## Local-only first, cloud-ready later

The first implementation should be local-only. It should prove that a local
Coordination Memory loop can create or resume first-class Codex conversations,
send assignment prompts, observe progress, and keep review work from being
forgotten.

Local-only still needs the same seams a future cloud service would need:

- The scheduler issues explicit command envelopes, such as `start_assignment`,
  `resume_assignment`, `nudge_review`, and `interrupt_run`.
- The Codex adapter consumes those envelopes locally through Codex app-server or
  an equivalent local bridge.
- Run binding records the communication handle and idempotency cursor, not just
  the claiming actor.
- Heartbeats, handoffs, review decisions, and stale detection flow through the
  Coordination Memory ledger instead of private adapter state.
- The adapter reports capability and availability, even when there is only one
  local node.

This keeps the local loop useful by itself while preserving a later migration
path to a cloud control plane with local connectors. The later cloud service can
replace the local scheduler transport with a resilient connector channel without
changing assignment contracts, run bindings, or Codex prompt envelopes.

The local implementation must not expose Codex app-server directly to remote
callers. If service mode is added later, a local connector should initiate the
outbound connection, tolerate network interruption, and replay idempotent
commands after reconnecting.

## Non-goals

- Do not store full design or plan content in Coordination Memory.
- Do not make Codex subagents the canonical team model.
- Do not let workers accept their own handoffs.
- Do not bypass explicit human or Integrator approval for deployment, secret,
  push, or other high-risk actions.
- Do not make the local dashboard the execution surface; it may visualize and
  trigger reviewed actions, but the ledger remains the source of truth.
- Do not build the cloud service, remote connector, or network transport in the
  first local-only implementation.

## Implications

The initial implementation should focus on five contracts:

1. A pointer-rich assignment metadata convention for `context_refs`.
2. A run-level agent binding convention for claim/session communication.
3. A Codex thread adapter capability model.
4. A local command-envelope interface that can later be carried over a cloud
   connector.
5. A loop-owned review nudge that prevents `awaiting_review` work from being
   forgotten.

These contracts allow Coordination Memory to coordinate agent teams while keeping
project memory in the project itself.
