# Human Attention and Status Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a human-facing latest Resume Brief and red/yellow/green Attention projection to comem without changing assignment, run, event, review, or accepted-ledger semantics.

**Architecture:** Keep the append-only `events` table as the sole source of truth. A focused domain module validates Human Resume Brief and Attention payloads; `CoordinationMemory` appends idempotent events and computes latest projections at read time; MCP and HTTP expose those projections; the Svelte console adds an Attention-first view while retaining the lifecycle board. Context compression and materialized projection tables are excluded from this implementation.

**Tech Stack:** Python 3.11+, SQLite, FastMCP, pytest, Ruff, mypy, Svelte 5, Vite, Vitest.

## Global Constraints

- Existing assignment/run lifecycle, review semantics, accepted ledger, acceptance contracts, and loop execution modes must remain unchanged.
- Human Resume Brief is for human context recovery only; it must not be used as Agent execution recovery state.
- Refreshing a Brief never creates a notification or changes assignment/run status.
- Attention is decided independently: red means a human is required for safe/correct progress; yellow means the Agent can continue but the human should be informed; green means no notification.
- Red Attention pauses only the blocked run branch; yellow and green never pause execution.
- `checkpoint_run` uses project-wide mandatory semantic triggers and a default 30-minute freshness window; teams may configure a shorter positive window but cannot disable semantic triggers.
- Yellow Attention is represented as a latest per-issue projection. The API reports a default 60-minute digest interval and product inbox channel; no external notification sender is implemented.
- Latest Brief is one item per run. Latest Attention is one item per `(run_id, dedupe_key)`. Both are disposable read projections reconstructed from append-only events.
- Context compression Worker, model selection, remote model access, retention jobs, and materialized projection tables are out of scope.
- All production behavior must be developed test-first: observe a focused failing test before adding implementation.
- Existing public method parameters remain backward compatible; new parameters are optional unless introduced by a new tool.

---

### Task 1: Human Brief and Attention domain rules

**Files:**
- Create: `src/coordination_memory_mcp/human_attention.py`
- Create: `tests/test_human_attention.py`

**Interfaces:**
- Produces: `normalize_human_brief(brief: dict[str, Any]) -> dict[str, Any]`
- Produces: `normalize_attention_item(item: dict[str, Any]) -> dict[str, Any]`
- Produces: `brief_freshness(*, updated_at: str, source_event_sequence: int, latest_event_sequence: int, now: datetime, freshness_window_minutes: int) -> str`
- Produces: constants `DEFAULT_FRESHNESS_WINDOW_MINUTES = 30`, `DEFAULT_YELLOW_DIGEST_MINUTES = 60`, `MANDATORY_CHECKPOINT_TRIGGERS`, `TERMINAL_ASSIGNMENT_STATUSES`
- Consumes: `ValidationError` is not imported from `store.py`; this module raises `ValueError` and the store translates it to `ValidationError`, avoiding a circular dependency.

- [ ] **Step 1: Write failing tests for canonical Brief validation**

```python
def test_normalize_human_brief_requires_fixed_human_fields() -> None:
    brief = normalize_human_brief(
        {
            "schema_version": 1,
            "current_goal": "Ship attention projection",
            "current_stage": "implementing",
            "recent_progress": ["Added contract tests"],
            "decisions_and_risks": [],
            "human_intervention": {"needed": False, "blocking": False},
            "next_steps": ["Implement store projection"],
            "context_refs": ["docs/design/comem-human-attention-and-status-brief-system-design.docx"],
        }
    )
    assert brief["schema_version"] == 1
    assert brief["current_stage"] == "implementing"
    assert brief["recent_progress"] == ["Added contract tests"]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/test_human_attention.py::test_normalize_human_brief_requires_fixed_human_fields -q`

Expected: FAIL because `coordination_memory_mcp.human_attention` does not exist.

- [ ] **Step 3: Implement canonical Brief normalization**

Implement exact supported stages `investigating`, `implementing`, `verifying`, `waiting`, `handing_off`, `completed`, and require all fields shown in Step 1. Reject unknown top-level types, blank goal, empty next steps, non-list progress/references, and intervention objects without boolean `needed` and `blocking`.

```python
SUPPORTED_BRIEF_STAGES = frozenset(
    {"investigating", "implementing", "verifying", "waiting", "handing_off", "completed"}
)

def normalize_human_brief(brief: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(brief, dict):
        raise ValueError("brief must be a JSON object")
    required = {
        "schema_version", "current_goal", "current_stage", "recent_progress",
        "decisions_and_risks", "human_intervention", "next_steps", "context_refs",
    }
    missing = sorted(required - brief.keys())
    if missing:
        raise ValueError(f"brief missing required fields: {', '.join(missing)}")
    # Validate exact field types and return a fresh JSON-compatible object.
```

- [ ] **Step 4: Add failing tests for Attention normalization and freshness**

Cover these exact behaviors:

```python
def test_attention_green_closes_same_issue_without_blocking() -> None:
    item = normalize_attention_item(
        {
            "level": "green",
            "target": "human",
            "blocking": False,
            "dedupe_key": "retry-budget",
            "reason_code": "risk_resolved",
            "why_now": "Fallback succeeded",
            "recommended_action": "None",
            "source_event_ids": [],
        }
    )
    assert item["level"] == "green"

def test_attention_rejects_red_from_nonblocking_raise_path() -> None:
    with pytest.raises(ValueError, match="yellow or green"):
        normalize_attention_item({**valid_attention(), "level": "red"})

def test_brief_is_stale_only_when_newer_events_exist_past_window() -> None:
    assert brief_freshness(
        updated_at="2026-07-12T00:00:00+00:00",
        source_event_sequence=4,
        latest_event_sequence=5,
        now=datetime.fromisoformat("2026-07-12T00:31:00+00:00"),
        freshness_window_minutes=30,
    ) == "stale"
```

- [ ] **Step 5: Run new tests and verify RED**

Run: `uv run pytest tests/test_human_attention.py -q`

Expected: existing Brief test passes; new Attention/freshness tests fail because functions are missing.

- [ ] **Step 6: Implement Attention normalization and freshness calculation**

`normalize_attention_item` accepts only `yellow` or `green`, requires `blocking is False`, and requires non-empty `dedupe_key`, `reason_code`, `why_now`, and `recommended_action`. `brief_freshness` returns `fresh` when no newer event exists regardless of wall-clock age; otherwise it returns `stale` only after the positive configured window has elapsed.

- [ ] **Step 7: Run domain tests and static checks**

Run: `uv run pytest tests/test_human_attention.py -q`

Expected: PASS.

Run: `uv run ruff check src/coordination_memory_mcp/human_attention.py tests/test_human_attention.py`

Expected: `All checks passed!`

Run: `uv run mypy`

Expected: `Success: no issues found`.

- [ ] **Step 8: Commit**

```bash
git add src/coordination_memory_mcp/human_attention.py tests/test_human_attention.py
git commit -m "feat: define human brief and attention rules"
```

### Task 2: Append-only writes and latest read projections

**Files:**
- Modify: `src/coordination_memory_mcp/store.py`
- Create: `tests/test_human_attention_store.py`

**Interfaces:**
- Consumes: Task 1 normalization and constants.
- Produces: `CoordinationMemory.checkpoint_run(...) -> dict[str, Any]`
- Produces: `CoordinationMemory.raise_attention(...) -> dict[str, Any]`
- Produces: `CoordinationMemory.get_human_brief(run_id: str) -> dict[str, Any]`
- Produces: `CoordinationMemory.get_attention_board(team_id: str = "default", target: str = "human", include_green: bool = False) -> dict[str, Any]`
- Changes: `CoordinationMemory.request_intervention` accepts optional `decision_packet: dict[str, Any] | None = None` without breaking existing callers.

- [ ] **Step 1: Write failing checkpoint projection tests**

Create a helper that creates and claims one assignment. Test:

```python
event = memory.checkpoint_run(
    run_id=run["run_id"], actor_id="agent-a", actor_role="agent",
    client_update_id="brief-1",
    source_event_sequence=memory.get_run_detail(run["run_id"])["events"][0]["sequence"],
    brief=valid_brief(),
)
assert event["event_type"] == "human_brief_updated"
assert memory.get_human_brief(run["run_id"])["brief"]["current_goal"] == valid_brief()["current_goal"]
assert memory.get_assignment_detail("task-1")["assignment"]["status"] == "claimed"
```

Also test: same `client_update_id` and identical payload returns the original event; same ID with changed payload raises `ValidationError`; a lower `source_event_sequence` cannot replace a newer Brief; another agent cannot checkpoint the run.

- [ ] **Step 2: Run checkpoint tests and verify RED**

Run: `uv run pytest tests/test_human_attention_store.py -q -k checkpoint`

Expected: FAIL because `checkpoint_run` and `get_human_brief` are missing.

- [ ] **Step 3: Implement checkpoint write and latest Brief projection**

Use `events` only. Before writing, validate ownership with `_require_active_mutable_run` and `_require_agent_owns_run`, translate `ValueError` from Task 1 into `ValidationError`, verify `source_event_sequence` is a positive existing event sequence for the same run, and detect idempotency by scanning prior `human_brief_updated` events for `client_update_id`. Never update `runs` or `assignments`.

The read result must contain:

```python
{
    "run_id": run_id,
    "assignment_id": run["assignment_id"],
    "brief": event["payload"]["brief"],
    "client_update_id": event["payload"]["client_update_id"],
    "source_event_sequence": event["payload"]["source_event_sequence"],
    "latest_event_sequence": latest_sequence,
    "updated_at": event["created_at"],
    "freshness": "fresh" | "stale",
    "freshness_window_minutes": configured_window,
}
```

Read `freshness_window_minutes` from team settings, defaulting to 30 and rejecting/ignoring non-positive overrides.

- [ ] **Step 4: Write failing latest Attention tests**

Test yellow does not change run/assignment state, green supersedes yellow for the same `(run_id, dedupe_key)`, different dedupe keys remain separate, `include_green=False` hides resolved green items, and team filtering is correct.

```python
memory.raise_attention(
    run_id=run_id, actor_id="agent-a", actor_role="agent",
    client_update_id="attn-1", level="yellow", target="human",
    dedupe_key="retry-budget", reason_code="retry_near_limit",
    why_now="Two attempts failed", recommended_action="Review in next digest",
    source_event_ids=[],
)
board = memory.get_attention_board("default")
assert board["counts"] == {"red": 0, "yellow": 1, "green": 0}
assert board["items"][0]["level"] == "yellow"
assert memory.get_run_detail(run_id)["status"] == "claimed"
```

- [ ] **Step 5: Run Attention tests and verify RED**

Run: `uv run pytest tests/test_human_attention_store.py -q -k attention`

Expected: FAIL because `raise_attention` and `get_attention_board` are missing.

- [ ] **Step 6: Implement non-blocking Attention and red intervention projection**

Append `attention_raised` events for yellow/green. Idempotency follows the checkpoint rule. Build latest items by highest event sequence for each `(run_id, dedupe_key)`. Add unresolved `intervention_requested` events as red; remove them when a matching `intervention_responded.reviewed_event_id` exists. Terminal assignments do not surface open Attention.

Return `digest` metadata:

```python
{
    "interval_minutes": team.settings.get("yellow_digest_minutes", 60),
    "channel": team.settings.get("attention_channel", "product_inbox"),
    "group_by": ["owner", "project", "assignment"],
}
```

Extend `request_intervention` only by adding the optional structured Decision Packet to the existing event payload. Existing positional/keyword calls and awaiting-human transition remain unchanged.

- [ ] **Step 7: Run store tests and full Python regression suite**

Run: `uv run pytest tests/test_human_attention_store.py tests/test_coordination_memory.py -q`

Expected: PASS.

Run: `uv run pytest -q`

Expected: all tests pass.

Run: `uv run ruff check src tests`

Expected: `All checks passed!`

Run: `uv run mypy`

Expected: `Success: no issues found`.

- [ ] **Step 8: Commit**

```bash
git add src/coordination_memory_mcp/store.py tests/test_human_attention_store.py
git commit -m "feat: persist human briefs and attention events"
```

### Task 3: MCP tools, read-only HTTP APIs, and operator documentation

**Files:**
- Modify: `src/coordination_memory_mcp/server.py`
- Modify: `src/coordination_memory_mcp/console.py`
- Modify: `tests/test_console.py`
- Modify: `README.md`
- Modify: `docs/tools.md`

**Interfaces:**
- Consumes: Task 2 store methods.
- Produces MCP tools: `checkpoint_run`, `raise_attention`, `get_human_brief`, `get_attention_board`.
- Produces HTTP routes: `GET /api/attention`, `GET /api/runs/<run_id>/brief`.
- Preserves: existing `/api/board`, `request_intervention`, and all existing tool signatures.

- [ ] **Step 1: Write failing HTTP API tests**

Add a run, checkpoint, and yellow Attention to the console fixture. Assert:

```python
status, ctype, body = _fetch(readonly, "/api/attention?team_id=default")
assert status == 200
assert ctype == "application/json; charset=utf-8"
assert json.loads(body)["counts"]["yellow"] == 1

status, _, body = _fetch(readonly, f"/api/runs/{run_id}/brief")
assert status == 200
assert json.loads(body)["run_id"] == run_id
```

- [ ] **Step 2: Run focused console tests and verify RED**

Run: `uv run pytest tests/test_console.py -q -k 'attention or brief'`

Expected: FAIL with 404 responses.

- [ ] **Step 3: Add MCP wrappers and HTTP read routes**

MCP wrappers mirror store signatures exactly. `/api/attention` accepts `team_id`, `target`, and `include_green=true|false`; `/api/runs/<id>/brief` must be matched before the existing generic run detail route. Both routes remain read-only.

- [ ] **Step 4: Extend documentation with exact semantics and examples**

Document:

```text
checkpoint_run: refreshes a human-only latest Brief and never changes run status.
raise_attention: writes yellow/green non-blocking Attention; green resolves a dedupe key.
request_intervention: remains the red/blocking path and may include a Decision Packet.
get_human_brief/get_attention_board: reconstruct latest projections from the event ledger.
```

Do not document context compression or materialized caches as shipped.

- [ ] **Step 5: Run API, docs-adjacent, and full Python checks**

Run: `uv run pytest tests/test_console.py tests/test_human_attention_store.py -q`

Expected: PASS.

Run: `uv run pytest -q`

Expected: all tests pass.

Run: `uv run ruff check src tests`

Expected: `All checks passed!`

Run: `uv run mypy`

Expected: `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add src/coordination_memory_mcp/server.py src/coordination_memory_mcp/console.py tests/test_console.py README.md docs/tools.md
git commit -m "feat: expose human attention APIs"
```

### Task 4: Attention-first console and Human Resume Brief detail

**Files:**
- Modify: `frontend/src/App.svelte`
- Modify: `frontend/src/ui.js`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/test/ui.test.js`
- Regenerate: `src/coordination_memory_mcp/static/index.html`
- Regenerate: `src/coordination_memory_mcp/static/app.js`
- Regenerate: `src/coordination_memory_mcp/static/styles.css`

**Interfaces:**
- Consumes: `GET /api/attention` and `GET /api/runs/<run_id>/brief` from Task 3.
- Produces: dashboard Attention summary ordered red, yellow, green; lifecycle board remains available on the same route.
- Produces UI helpers: `attentionSortValue(level)`, `attentionLabel(level)`, `briefFreshnessLabel(freshness)`.

- [ ] **Step 1: Write failing helper tests**

```javascript
test("orders human attention by required human urgency", () => {
  expect(["green", "red", "yellow"].sort((a, b) => attentionSortValue(a) - attentionSortValue(b)))
    .toEqual(["red", "yellow", "green"]);
});

test("formats brief freshness without implying agent recovery", () => {
  expect(briefFreshnessLabel("fresh")).toBe("brief up to date");
  expect(briefFreshnessLabel("stale")).toBe("brief needs refresh");
});
```

- [ ] **Step 2: Run frontend test and verify RED**

Run: `npm test -- --run`

Expected: FAIL because helpers are not exported.

- [ ] **Step 3: Implement helpers and Attention-first dashboard loading**

Load `/api/attention?team_id=<selected>` alongside existing board/governance data. Render one compact section before lifecycle lanes:

- red: “Intervention required”, Decision Packet summary, link to run/assignment;
- yellow: “Review recommended”, non-blocking reason and recommended action;
- green: hidden by default, represented only in counts;
- empty state: “No items currently require your attention.”

Do not remove or rename the lifecycle board. Do not add notification settings UI.

- [ ] **Step 4: Show latest Brief on run and assignment detail routes**

On a run detail route, fetch `/api/runs/<id>/brief`; render the fixed fields and `freshness`. On assignment detail, show the Brief for the active run when present. A missing Brief displays “No Human Resume Brief yet.” and does not become a red Attention item.

- [ ] **Step 5: Run frontend tests and build checked-in assets**

Run: `npm test -- --run`

Expected: PASS.

Run: `npm run build`

Expected: Vite build succeeds and refreshes the three static assets.

Run: `node --check src/coordination_memory_mcp/static/app.js`

Expected: exit 0.

- [ ] **Step 6: Run the complete project verification suite**

Run: `uv run pytest -q`

Expected: all Python tests pass.

Run: `uv run ruff check src tests`

Expected: `All checks passed!`

Run: `uv run mypy`

Expected: `Success: no issues found`.

Run: `npm run check`

Expected: frontend tests and production build both pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.svelte frontend/src/ui.js frontend/src/styles.css frontend/test/ui.test.js src/coordination_memory_mcp/static/index.html src/coordination_memory_mcp/static/app.js src/coordination_memory_mcp/static/styles.css
git commit -m "feat: add attention-first human console"
```

## Final Acceptance

The Integrator must verify all of the following against the complete branch:

1. A Brief update appends `human_brief_updated`, leaves run/assignment state unchanged, and reads back as the latest per run.
2. Yellow Attention leaves execution running; green supersedes the same issue; red comes only from unresolved blocking intervention.
3. Existing intervention callers, lifecycle board, loop runner, acceptance contracts, and accepted snapshot tests remain green.
4. MCP and HTTP read surfaces expose the projections with no new write authority in the console.
5. The dashboard leads with human attention while retaining the original lifecycle view and evidence drill-down.
6. Python tests, Ruff, mypy, Vitest, Vite build, and generated static JavaScript syntax checks all pass.
7. No context-compression Worker, external model call, materialized projection table, email sender, Slack sender, or Agent recovery coupling is introduced.
