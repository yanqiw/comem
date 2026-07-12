## Coordination Memory protocol

This project uses the **coordination-memory** MCP server for multi-agent
coordination. Treat its accepted state as the single source of truth for "what
is done." Follow this protocol whenever you act as a coordinated agent.

### Roles

- `integrator` — owns the accepted ledger: creates assignments and records
  review decisions (accept / reject / needs_fix). Only an integrator turns work
  into accepted truth.
- `agent` — claims assignments, does the work, appends evidence, submits
  handoffs. An agent's "completed" is a *proposal*, not acceptance.
- `human` — answers interventions and acts as the ultimate acceptor.

### The rule that matters

`completed_gate_passed` is **not** accepted truth. Only an integrator review
decision (`integrator_accepted`) produces accepted state. Never self-certify
your own work as done.

### Normal flow

1. `register_actor` (once) — declare who you are.
2. `claim_assignment` — take a lease before working; records run metadata.
3. `record_run_binding` — keep session/thread/worktree communication metadata
   current when a loop or adapter starts or resumes an agent conversation.
4. `heartbeat_run` — report liveness on long runs.
5. `checkpoint_run` — refresh the Human Resume Brief after a meaningful change.
6. `raise_attention` — write yellow/green human Attention without pausing work;
   use `request_intervention` only for the red/blocking path.
7. `append_event` / `submit_handoff` — append evidence; submit a reviewable
   handoff when you believe the work is complete.
8. Integrator: `list_pending_reviews`, then `review_event` / `accept_event` /
   `reject_event`.
9. Read models: `get_team_board`, `get_assignment_detail`, `get_run_detail`,
   `get_human_brief`, `get_attention_board`.

### Human status and attention

Human Resume Brief is a one-minute status view for a person. Keep it current
after phase changes, milestones, plan or decision changes, risk changes,
interventions, handoffs, and run completion. It does not restore agent execution
context; recover that from the assignment and `metadata.context_refs`.

Decide Attention independently from Brief freshness:

- Red: work cannot safely continue without a person. Use
  `request_intervention`; include a Decision Packet when a choice is needed.
- Yellow: work continues, but a person should review the item in the next
  digest. Use `raise_attention` with a stable `dedupe_key`.
- Green: the matching issue is resolved. Use `raise_attention` with the same
  `dedupe_key`; green is hidden from the default board but remains counted.

Refreshing a Brief never creates Attention, and yellow/green Attention never
changes assignment or run status.

### Execution mode selection

After a Codex Integrator creates a workspace, team, and assignments, ask the
user to choose one execution mode before starting work:

- `codex_subagent` (default) — the current Codex conversation remains the
  Integrator, starts Codex subagents as workers, and records claims,
  heartbeats, handoffs, and reviews in Coordination Memory.
- `comem_loop` — Codex starts `comem loop` with the selected workspace/team and
  the loop owns worker claims and thread starts.

For `codex_subagent`, claim runs with `session_kind="codex_subagent"` and
`session_ref` set to the parent Codex thread id when available. Record the
subagent nickname/name in run metadata or an observed event when Codex exposes
it. This mode is dashboard-visible through the parent conversation; do not
pretend the subagent is an independently addressable first-class thread.

For `comem_loop`, use loop-managed `metadata.session_bind` and let the loop
claim assignments. Start with a dry-run before launching a polling loop.

### Local loop and task contract

When a local scheduler such as `comem loop` starts or nudges an agent, the
assignment is the contract. Treat `title`, `allowed_paths`,
`acceptance_criteria`, `metadata.context_refs`, and the current `revision` as
the authoritative task boundary.

Loop-managed assignments should also include `metadata.session_bind` so the
loop has a stable target before any run exists:

```json
{
  "session_bind": {
    "target_actor_id": "<intended-worker-actor-id>",
    "status": "pending",
    "session_kind": "codex_thread"
  }
}
```

`assigned_actor_hint` is a compatibility shortcut; new task contracts should
prefer `metadata.session_bind.target_actor_id`.

Durable memory and long context live in repository Markdown files, not in MCP
payloads. Assignments should point to design docs, plans, runbooks, or evidence
through `metadata.context_refs`; agents must read those files before changing
code. Do not paste large docs, `.env` contents, credentials, or secret-bearing
logs into Coordination Memory.

For Codex-style first-class agent conversations, claims and run bindings should
turn that intended binding into the actual reachable conversation for the loop
and humans. Prefer claim metadata such as:

```json
{
  "session_kind": "codex_thread",
  "session_ref": "<thread-or-agent-id>",
  "interactive_url": "<link-if-available>",
  "worktree_path": "<absolute-worktree-path>",
  "branch": "codex/<feature-branch>",
  "base_commit": "<starting-commit>"
}
```

Use `record_run_binding` for adapter kind, command id, client message id, and
last seen turn/cursor updates. The loop may start workers and nudge
integrators, but it never accepts work; acceptance still requires an integrator
review decision.

### Starting a local loop from Codex

A Codex Integrator conversation may start `comem loop` from its terminal. Do
this only as an operator action, not from inside a worker that is currently
claiming an assignment.

Before starting the loop, set `COORDINATION_MEMORY_DB` to the same stable
absolute SQLite path used by the MCP server and dashboard. Do not rely on the
default DB path, because that can create a separate per-worktree memory.

Start with a dry-run:

```bash
comem loop --workspace <workspace_id> --team <team_id> --adapter fake --dry-run --once
```

Then run one pass or one long-running loop:

```bash
comem loop --workspace <workspace_id> --team <team_id> --adapter fake --once
comem loop --workspace <workspace_id> --team <team_id> --adapter fake --poll-interval 30
```

Run at most one active loop per team and DB unless the Integrator deliberately
shards work. `fake` is the safe local adapter for deterministic validation.
`codex-app-server` is a guarded capability probe/skeleton; use it only when a
local Codex app-server endpoint is explicitly available, and do not claim it
started real Codex conversations otherwise.

### Optimistic concurrency

Every mutating call carries `base_revision` (the revision you read) and bumps
it. If a write is rejected as stale, re-read the current state and retry — do
not force.

### Tool reference

- Setup: `register_actor`, `register_workspace`, `create_team`.
- Work (agent): `claim_assignment`, `record_run_binding`, `heartbeat_run`,
  `checkpoint_run`, `raise_attention`, `append_event`, `submit_handoff`,
  `request_intervention`.
- Review (integrator): `create_assignment`, `cancel_assignment`,
  `supersede_assignment`, `list_pending_reviews`, `review_event`,
  `accept_event`, `reject_event`, `respond_intervention`.
- Read models (any role): `get_team_board`, `get_assignment_detail`,
  `get_run_detail`, `get_human_brief`, `get_attention_board`, `get_snapshot`.
- Acceptance contracts: `create_acceptance_contract`, `add_invariant`,
  `bind_assignment_to_contract`, `seal_contract`, `report_verification`,
  `evaluate_contract`, `accept_contract`, `reject_contract`, `raise_deviation`,
  `waive_deviation`, `reopen_contract`, `get_contract_detail`, `list_contracts`.

### Acceptance contracts (goal-level governance)

For goal-level outcomes, an **acceptance contract** defines machine-checkable
invariants that cannot be self-certified, enforced by three gates: `seal`
(freeze criteria; requires a deny test and a second-instance test), `evaluate`
(objective self-healing loop), and `accept` (an independent acceptor signs off;
the acceptor may not be an actor that ran a bound assignment).

When unsure which tool to call, read `get_assignment_detail` /
`get_contract_detail` first and follow the `next_action_hint`.
