# Concepts & governance model

## The core idea

The MCP server is the **live coordination layer**. Its accepted state is the
single source of truth for "what is done." Everything else (proposals, runs,
evidence) is in service of producing accepted state.

## Roles

| Role | Can do |
| --- | --- |
| `integrator` | Create assignments; record review decisions (accept / reject / needs_fix). Only an integrator produces accepted truth. |
| `agent` | Claim assignments, do the work, append evidence, submit handoffs. |
| `human` | Answer interventions; act as ultimate acceptor. |

## The rule that matters

`completed_gate_passed` is **not** accepted truth. An agent reporting "done" is a
*proposal*. Only an integrator review decision (`integrator_accepted`) promotes
work into the accepted ledger. This makes "the implementer declared it done"
structurally insufficient.

## Data model

Six core tables: **workspace → team → assignment → run → event**, plus
**actors**.

- An **assignment** is a unit of work. Claiming one starts a **run** and takes a
  lease.
- **Events** are the append-only log (evidence, handoffs, reviews, …).
- Mutating writes use **optimistic concurrency**: each carries the current
  `base_revision` and bumps the revision. Stale writes are rejected — re-read and
  retry rather than force.

## Acceptance contracts (goal-level governance)

For a goal-level outcome, an **acceptance contract** defines machine-checkable
invariants that cannot be self-certified. Three gates:

1. **`seal`** — freeze the invariant set. Refuses to seal without at least one
   deny test and one second-instance test, a probe spec on every invariant, and
   an acceptor that did not run a bound assignment.
2. **`evaluate`** — the objective gate and self-healing loop. If every required
   invariant's latest probe `passed` and no blocker is open → `awaiting_acceptor`;
   otherwise it emits a bounded repair assignment. A bound runner cannot
   evaluate or accept its own contract.
3. **`accept`** — only the independent acceptor signs off that the invariant set
   adequately covers the goal (green is already objective fact).

## Accepted projection

An integrator can export accepted state as a durable, auditable projection (for
example, committed to Git) — separate from the live SQLite store, which is never
committed.
