# Examples

These show the shape of the tool calls. Argument names match the MCP tools;
every mutating call carries the current `base_revision`.

## Assignment loop (create → claim → handoff → accept)

```text
# Integrator sets up identities and a task
register_actor(actor_id="alice", actor_kind="human", display_name="Alice")
register_actor(actor_id="builder-1", actor_kind="ai", display_name="Builder")
register_workspace(workspace_id="proj", repo_root="/abs/proj", default_branch="main")
create_team(team_id="core", workspace_id="proj", name="Core", owner_actor_id="alice")
create_assignment(
    assignment_id="task-1", title="Add rate limiting",
    actor_id="alice", actor_role="integrator", base_revision=0,
    team_id="core", workspace_id="proj",
    acceptance_criteria=["unit tests pass", "p95 latency < 200ms"],
)

# Agent does the work
claim_assignment(assignment_id="task-1", actor_id="builder-1",
                 actor_role="agent", base_revision=1, branch="feat/ratelimit")
append_event(assignment_id="task-1", event_type="progress", status="observed",
             actor_id="builder-1", actor_role="agent", base_revision=2,
             payload={"summary": "added token bucket"})
submit_handoff(assignment_id="task-1", actor_id="builder-1", actor_role="agent",
               base_revision=3, payload={"summary": "done", "evidence": {...}})
# -> event status: completed_gate_passed  (NOT accepted yet)

# Integrator reviews
list_pending_reviews()
accept_event(event_id="evt_...", actor_id="alice", actor_role="integrator",
             base_revision=4, decision_note="criteria verified")
# -> status: integrator_accepted  (now it is accepted truth)
```

If a write returns a stale-revision error, re-read with `get_assignment_detail`
and retry with the new `base_revision`.

## Acceptance contract (goal-level)

```text
create_acceptance_contract(contract_id="c1", goal_statement="Login is rate-limited",
                           actor_id="alice", actor_role="integrator", ...)
add_invariant(contract_id="c1", probe_kind="command",
              probe_spec={"ref": "probes/tests.sh"}, ...)        # positive test
add_invariant(contract_id="c1", probe_kind="http", is_negative=True, ...)  # deny test
add_invariant(contract_id="c1", is_second_instance=True, ...)   # second-instance test
seal_contract(contract_id="c1", ...)        # refuses without deny + second-instance
report_verification(contract_id="c1", invariant_key="...", outcome="passed", ...)
evaluate_contract(contract_id="c1", ...)    # all green + no blocker -> awaiting_acceptor
accept_contract(contract_id="c1", ...)      # independent acceptor signs off
```

A runner bound to the contract cannot `evaluate` or `accept` it — sign-off is
independent by construction. See [concepts](concepts.md) for the full model.
