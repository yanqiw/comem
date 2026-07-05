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
| `record_run_binding` | agent / integrator | update active run communication metadata and append an observed binding event |
| `request_intervention` / `respond_intervention` | agent / human | move a run to/from an awaiting-human lane |
| `append_event` / `submit_handoff` | agent | append evidence / submit a reviewable handoff |
| `list_pending_reviews` | any | reviewable events with no decision yet |
| `review_event` / `accept_event` / `reject_event` | integrator | record a review decision |
| `get_team_board` / `get_assignment_detail` / `get_run_detail` | any | read models |
| `get_snapshot` / `export_git_projection` | integrator | accepted projection |

### record_run_binding

Updates metadata for one active run and appends a `run_binding_recorded`
observed event. Agents may update only their own active runs; integrators may
update any active run. This is intended for adapter kind, thread cursor, turn
cursor, and idempotency metadata. It does not change accepted state and rejects
terminal runs.

## Acceptance contracts

`create_acceptance_contract`, `add_invariant`, `bind_assignment_to_contract`,
`seal_contract`, `report_verification`, `evaluate_contract`, `accept_contract`,
`reject_contract`, `raise_deviation`, `waive_deviation`, `reopen_contract`,
`get_contract_detail`, `list_contracts`.

See [concepts](concepts.md#acceptance-contracts-goal-level-governance) for how
the three gates fit together.
