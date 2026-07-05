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
5. `append_event` / `submit_handoff` — append evidence; submit a reviewable
   handoff when you believe the work is complete.
6. Integrator: `list_pending_reviews`, then `review_event` / `accept_event` /
   `reject_event`.
7. Read models: `get_team_board`, `get_assignment_detail`, `get_run_detail`.

### Local loop and task contract

When a local scheduler such as `comem loop` starts or nudges an agent, the
assignment is the contract. Treat `title`, `allowed_paths`,
`acceptance_criteria`, `metadata.context_refs`, and the current `revision` as
the authoritative task boundary.

Durable memory and long context live in repository Markdown files, not in MCP
payloads. Assignments should point to design docs, plans, runbooks, or evidence
through `metadata.context_refs`; agents must read those files before changing
code. Do not paste large docs, `.env` contents, credentials, or secret-bearing
logs into Coordination Memory.

For Codex-style first-class agent conversations, claims and run bindings should
make the agent reachable by the loop and by humans. Prefer claim metadata such
as:

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

### Optimistic concurrency

Every mutating call carries `base_revision` (the revision you read) and bumps
it. If a write is rejected as stale, re-read the current state and retry — do
not force.

### Tool reference

- Setup: `register_actor`, `register_workspace`, `create_team`.
- Work (agent): `claim_assignment`, `record_run_binding`, `heartbeat_run`,
  `append_event`, `submit_handoff`, `request_intervention`.
- Review (integrator): `create_assignment`, `cancel_assignment`,
  `supersede_assignment`, `list_pending_reviews`, `review_event`,
  `accept_event`, `reject_event`, `respond_intervention`.
- Read models (any role): `get_team_board`, `get_assignment_detail`,
  `get_run_detail`, `get_snapshot`.
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
