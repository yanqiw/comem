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

## Human Resume Brief and Attention

Brief and Attention are disposable human-facing projections over the same
append-only event ledger. They do not replace assignments, runs, reviews,
acceptance contracts, or repository Markdown.

- A **Human Resume Brief** is the latest one-minute status summary for a run. It
  records the goal, stage, recent progress, decisions and risks, intervention
  state, next steps, and context references. It exists to help a person re-enter
  the work; agents must recover execution context from the assignment and its
  referenced project files.
- **Attention** answers a separate question: does a person need to look now?
  Red is derived from an unresolved blocking intervention on the active run.
  Yellow is non-blocking information for the next digest. Green resolves the
  matching yellow issue and is hidden by default.
- Refreshing a Brief never changes run status and never creates Attention.
  Raising yellow or green Attention never pauses execution. Only the existing
  intervention path moves a run into `awaiting_human`.

Both views are reconstructed from events. The store keeps the latest Brief per
run and the latest Attention item per `(run_id, dedupe_key)` without adding a
second source of truth.

## Accepted projection

An integrator can export accepted state as a durable, auditable projection (for
example, committed to Git) — separate from the live SQLite store, which is never
committed.
