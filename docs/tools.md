# Tool reference

Every mutating tool takes a `base_revision` and rejects stale writes. Run and
intervention tools only change local lanes and the event timeline — they never
execute commands, resume threads, or touch files.

## Coordination

| Tool | Role | Purpose |
| --- | --- | --- |
| `register_actor` | any | register/refresh an actor profile |
| `register_workspace` | any | create/refresh a workspace record (idempotent) |
| `create_team` | any | create/refresh a team (auto-creates its workspace) |
| `create_assignment` | integrator | create a task (optional workspace/team/paths/criteria) |
| `cancel_assignment` | integrator | void a task (mistake/scope dropped); releases any lease |
| `supersede_assignment` | integrator | retire a task replaced by another (`superseded_by`) |
| `claim_assignment` | agent | claim a lease; records run/session/worktree metadata |
| `heartbeat_run` | agent | report run liveness |
| `checkpoint_run` | agent | refresh the latest human-only Brief without changing run status |
| `raise_attention` | agent | write yellow/green non-blocking Attention; green resolves a dedupe key |
| `record_run_binding` | agent / integrator | update active run communication metadata and append an observed binding event |
| `request_intervention` / `respond_intervention` | agent / human | use the red/blocking path (optionally with a Decision Packet) and move a run to/from an awaiting-human lane |
| `append_event` / `submit_handoff` | agent | append evidence / submit a reviewable handoff |
| `list_pending_reviews` | any | reviewable events with no decision yet |
| `review_event` / `accept_event` / `reject_event` | integrator | record a review decision |
| `get_team_board` / `get_assignment_detail` / `get_run_detail` | any | coordination read models |
| `get_human_brief` / `get_attention_board` | any | reconstruct the latest human projections from the event ledger |
| `get_snapshot` / `export_git_projection` | integrator | accepted projection |

### record_run_binding

Updates metadata for one active run and appends a `run_binding_recorded`
observed event. Agents may update only their own active runs; integrators may
update any active run. This is intended for adapter kind, thread cursor, turn
cursor, and idempotency metadata. It does not change accepted state and rejects
terminal runs.

## Human Brief and Attention

`checkpoint_run` refreshes a human-only latest Brief and never changes run
status. The `source_event_sequence` must identify an event from that run, while
`client_update_id` makes retries idempotent:

Brief freshness defaults to 30 minutes. A team's `freshness_window_minutes`
setting may only shorten that window: positive integers are capped at 30, while
invalid values (including booleans) fall back to 30. Age alone does not make a
Brief stale; the window must have elapsed and a later event for the same run
other than `human_brief_updated` must exist.

Checkpoints are mandatory for `phase_changed`, `milestone_completed`,
`plan_changed`, `decision_made`, `risk_changed`, `intervention_requested`,
`handoff`, and `run_finished`. Team settings cannot disable these triggers.

```json
{
  "run_id": "run_123",
  "actor_id": "agent-a",
  "actor_role": "agent",
  "client_update_id": "brief-7",
  "source_event_sequence": 42,
  "brief": {
    "schema_version": 1,
    "current_goal": "Expose human attention APIs",
    "current_stage": "implementing",
    "recent_progress": ["Added the read routes"],
    "decisions_and_risks": [],
    "human_intervention": {"needed": false, "blocking": false},
    "next_steps": ["Run verification"],
    "context_refs": ["task-3-brief"]
  }
}
```

`raise_attention` writes yellow/green non-blocking Attention. A later green item
with the same run and `dedupe_key` resolves the visible yellow item:

```json
{
  "run_id": "run_123",
  "actor_id": "agent-a",
  "actor_role": "agent",
  "client_update_id": "attention-4",
  "level": "yellow",
  "target": "human",
  "dedupe_key": "review-api",
  "reason_code": "review_soon",
  "why_now": "The API surface is ready",
  "recommended_action": "Review in the next digest",
  "source_event_ids": []
}
```

`request_intervention` remains the red/blocking path and may include a Decision
Packet. It moves the run to `awaiting_human`; use it only when work cannot safely
continue without a response:

```json
{
  "run_id": "run_123",
  "actor_id": "agent-a",
  "actor_role": "agent",
  "prompt": "Choose the rollout policy",
  "intervention_kind": "decision_required",
  "decision_packet": {"options": ["canary", "all-at-once"], "recommended": "canary"}
}
```

`get_human_brief` and `get_attention_board` reconstruct the latest projections
from the event ledger. The dashboard exposes the same read-only projections:

```text
GET /api/runs/run_123/brief
GET /api/attention?team_id=default&target=human&include_green=false
```

`include_green=true` includes resolved green items in `items`; counts always
cover red, yellow, and green items for the selected target.

## Acceptance contracts

`create_acceptance_contract`, `add_invariant`, `bind_assignment_to_contract`,
`seal_contract`, `report_verification`, `evaluate_contract`, `accept_contract`,
`reject_contract`, `raise_deviation`, `waive_deviation`, `reopen_contract`,
`get_contract_detail`, `list_contracts`.

See [concepts](concepts.md#acceptance-contracts-goal-level-governance) for how
the three gates fit together.
