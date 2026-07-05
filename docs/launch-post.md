# Launch Post Draft

Publication gate: post this only after the PyPI package resolves, the GitHub
repository has its launch metadata set, and Discussions is enabled.

## Title Options

- Completed is not accepted: Coordination Memory for multi-agent coding
- A local MCP coordination layer for parallel coding agents
- Stop coding agents from overwriting each other or self-certifying done

## Long Form

When multiple coding agents work on the same project, two things go wrong fast:
they overwrite each other, and "the agent says it is done" gets confused with
"the work was accepted."

Coordination Memory MCP is a local-first MCP server for that coordination layer.
It records assignment ownership, run liveness, human interventions, handoff
evidence, and integrator review decisions in an append-only SQLite store.

The key rule is simple: completed is not accepted.

An agent can submit a handoff with evidence. Only an integrator can promote that
handoff into the accepted ledger. For goal-level work, acceptance contracts make
self-certified done structurally insufficient: criteria are sealed, probes are
reported as evidence, and an independent acceptor signs off.

It is intentionally boring infrastructure:

- local SQLite and stdio MCP
- no deployment
- no secret reading
- no shell execution
- optimistic concurrency on mutating writes
- exported accepted projection for durable audit
- a local dashboard for assignments, runs, reviews, and contracts

Install:

```bash
uv tool install coordination-memory-mcp
comem --help
```

Run:

```bash
COORDINATION_MEMORY_DB=/absolute/path/coordination.sqlite3 comem serve
```

Set up agent onboarding files:

```bash
comem init
```

Open the local dashboard:

```bash
COORDINATION_MEMORY_DB=/absolute/path/coordination.sqlite3 \
  comem dashboard --host 127.0.0.1 --port 8765
```

Good fits:

- multiple Codex, Claude Code, Cursor, or other agents working from separate
  worktrees
- teams that need review before an agent's work counts as accepted
- maintainers who want a replayable audit trail of coordination decisions
- local-first users who do not want their coordination layer reading secrets or
  executing commands

Not a fit:

- generic long-term memory
- RAG
- secret storage
- cloud orchestration

Repository: https://github.com/yanqiw/comem

## Short Form

I released Coordination Memory MCP: a local SQLite-backed MCP server for
multi-agent coding coordination.

The key idea: completed is not accepted.

Agents can claim leased assignments and submit handoff evidence. Only an
integrator can accept work into the ledger. Acceptance contracts add independent
goal-level sign-off.

Repo: https://github.com/yanqiw/comem

## Outreach Checklist

- GitHub repository release notes for `v0.2.4`.
- MCP Registry once PyPI is live and `server.json` is publishable.
- Glama MCP server directory.
- `awesome-mcp-servers` pull request.
- MCP community channels with a feedback request focused on multi-agent coding
  coordination.
- Hacker News "Show HN" only after install works from PyPI.
- X/LinkedIn short form with the dashboard screenshot.

