# 90-Second Demo Script

Use this when recording a short launch video or walking someone through the
project live. The goal is to show why Coordination Memory exists, not to list
every tool.

## One-Sentence Setup

Coordination Memory is a local MCP server that stops parallel coding agents from
overwriting each other or self-certifying done: agents can claim leased work and
submit evidence, but only an integrator can accept it into the ledger.

## Demo Beats

0-10 seconds: Show the problem.

"I have two agents working on the same repo. Without shared coordination, they
can duplicate work, clobber files, or both say they are done even though nobody
accepted the result."

10-25 seconds: Start from a shared local store.

```bash
COORDINATION_MEMORY_DB=/absolute/path/coordination.sqlite3 comem serve
```

Point out that the server is stdio MCP, SQLite-backed, local-first, and does not
execute shell commands.

25-45 seconds: Show assignment ownership.

In an MCP client, call the assignment loop:

```text
register_actor(...)
register_workspace(...)
create_team(...)
create_assignment(...)
claim_assignment(...)
```

Narration: "The claim creates a lease. If another agent tries to claim the same
assignment with a stale revision, the store rejects it. The coordination state is
append-only and optimistic-concurrency guarded."

45-65 seconds: Show evidence and acceptance.

```text
append_event(status="observed", payload={"summary": "implemented the fix"})
submit_handoff(payload={"summary": "ready for review", "evidence": {...}})
accept_event(actor_role="integrator", decision_note="criteria verified")
```

Narration: "`completed_gate_passed` is still only a proposal. Accepted truth
appears only after an integrator records the review decision."

65-80 seconds: Open the dashboard.

```bash
COORDINATION_MEMORY_DB=/absolute/path/coordination.sqlite3 \
  comem dashboard --host 127.0.0.1 --port 8765
```

Show the board, pending reviews, accepted work, and the contract detail page.

80-90 seconds: Close with the hook.

"This is not generic memory or RAG. It is a local coordination and governance
layer for agentic coding: leases, handoffs, evidence, review, and accepted
projection."

## Screenshot Checklist

- Overview board with at least one ready, claimed, awaiting review, and accepted
  assignment.
- Assignment detail showing acceptance criteria and event timeline.
- Contract detail showing sealed criteria, invariants, verification results, and
  independent acceptor status.
- Dashboard URL and local DB path visible only if they do not reveal secrets.

