---
name: coordination-memory
description: Use when coordinating multi-agent work through the coordination-memory MCP server — claiming assignments, appending evidence, submitting handoffs, and respecting integrator-only acceptance. Read AGENTS.md for the full protocol.
---

# Coordination Memory

Follow the **Coordination Memory protocol** in `AGENTS.md` at the repository
root (the section between the `coordination-memory` markers).

Key rules:

- `completed_gate_passed` is not accepted truth; only an integrator
  `accept_event` makes work accepted.
- Always `claim_assignment` before working, and pass the current
  `base_revision` on mutating calls.
- Orient with `get_team_board` / `get_assignment_detail` before acting.
- For loop-dispatched work, treat the assignment as the task contract: read
  `metadata.context_refs`, obey `allowed_paths` and `acceptance_criteria`, and
  use `metadata.session_bind.target_actor_id` as the intended worker binding
  before any run exists. Keep run communication metadata current with
  `record_run_binding` after the conversation starts.
