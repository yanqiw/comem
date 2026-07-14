---
layout: home

hero:
  name: Coordination Memory
  text: Coordination is live. Acceptance is durable.
  tagline: Append-only coordination memory for multi-agent and human work—leases, handoff evidence, acceptance contracts, and an integrator-owned source of truth.
  actions:
    - theme: brand
      text: Get started
      link: /quickstart
    - theme: alt
      text: View on GitHub
      link: https://github.com/yanqiw/comem

features:
  - icon: ◌
    title: Coordinate without collisions
    details: Assignment claims and leases make ownership explicit while runs and heartbeats keep liveness visible.
  - icon: ✓
    title: Acceptance is a decision
    details: An agent can report completion; only an independent integrator can promote evidence into accepted truth.
  - icon: ≋
    title: Keep an audit trail
    details: Append-only events and durable accepted projections preserve what happened, who decided, and why.
  - icon: ⌁
    title: Local-first by design
    details: SQLite and stdio keep control close to the work. No cloud service, secret collection, or hidden execution.
---

## One memory for the work in motion

Coordination Memory is an MCP server and local dashboard for teams of agents and people working on the same goal. It separates three things that are often blurred together: **ownership**, **evidence**, and **acceptance**.

```bash
uv tool install coordination-memory-mcp
comem serve
```

[Read the quickstart →](/quickstart)
