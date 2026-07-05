from pathlib import Path

from coordination_memory_mcp.loop_adapters import CodexAppServerAdapter, FakeCodexAdapter
from coordination_memory_mcp.loop_models import LoopConfig
from coordination_memory_mcp.loop_runner import LoopRunner
from coordination_memory_mcp.store import CoordinationMemory


def open_memory(tmp_path: Path) -> CoordinationMemory:
    return CoordinationMemory(tmp_path / "coordination.sqlite3")


def submit_fake_worker_handoff(memory: CoordinationMemory, assignment_id: str) -> None:
    detail = memory.get_assignment_detail(assignment_id)
    assignment = detail["assignment"]
    run = memory.get_run_detail(assignment["active_run_id"])
    memory.submit_handoff(
        assignment_id=assignment_id,
        actor_id=run["actor_id"],
        actor_role="agent",
        base_revision=assignment["revision"],
        payload={
            "summary": "fake worker completed assignment",
            "evidence": [
                "fake adapter prompt was sent",
                "run binding metadata was recorded",
            ],
        },
    )


def test_loop_dry_run_selects_ready_assignment_without_mutating(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="loop-ready",
        title="Loop ready",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        acceptance_criteria=["selected"],
        metadata={"context_refs": [{"path": "docs/design/local-codex-loop-detailed-design.md"}]},
    )

    result = LoopRunner(
        memory=memory,
        config=LoopConfig(team_id="default", adapter="fake", dry_run=True, once=True),
        adapter=FakeCodexAdapter(),
    ).run_once()

    assert [command.assignment_id for command in result.commands] == ["loop-ready"]
    assert result.dispatched == 0
    detail = memory.get_assignment_detail(assignment["assignment_id"])
    assert detail["assignment"]["status"] == "ready"


def test_loop_skips_scheduling_when_adapter_capability_probe_fails(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="loop-codex-unavailable",
        title="Loop codex unavailable",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        acceptance_criteria=["not scheduled"],
    )

    result = LoopRunner(
        memory=memory,
        config=LoopConfig(team_id="default", adapter="codex-app-server", once=True),
        adapter=CodexAppServerAdapter(),
    ).run_once()

    assert result.commands == []
    assert result.dispatched == 0
    detail = memory.get_assignment_detail(assignment["assignment_id"])
    assert detail["assignment"]["status"] == "ready"


def test_loop_fake_adapter_claims_and_records_run_binding(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="loop-claim",
        title="Loop claim",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        acceptance_criteria=["claimed"],
        metadata={"context_refs": [{"path": "docs/design/local-codex-loop-detailed-design.md"}]},
    )
    adapter = FakeCodexAdapter()

    result = LoopRunner(
        memory=memory,
        config=LoopConfig(team_id="default", adapter="fake", once=True),
        adapter=adapter,
    ).run_once()

    detail = memory.get_assignment_detail(assignment["assignment_id"])
    run = memory.get_run_detail(detail["assignment"]["active_run_id"])
    assert result.dispatched == 1
    assert detail["assignment"]["status"] == "claimed"
    assert run["session_kind"] == "codex_thread"
    assert run["session_ref"] == "fake-thread-1"
    assert run["metadata"]["adapter"]["kind"] == "fake_codex"
    assert run["metadata"]["communication_cursor"]["last_seen_turn_id"] == "fake-turn-1"


def test_loop_fake_adapter_handoff_reaches_pending_review_and_nudges_integrator(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="loop-e2e",
        title="Loop e2e",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        acceptance_criteria=["handoff reaches review"],
        metadata={"context_refs": [{"path": "docs/design/local-codex-loop-detailed-design.md"}]},
    )
    adapter = FakeCodexAdapter()
    runner = LoopRunner(
        memory=memory,
        config=LoopConfig(team_id="default", adapter="fake", once=True),
        adapter=adapter,
    )

    runner.run_once()
    submit_fake_worker_handoff(memory, assignment["assignment_id"])
    result = runner.run_once()

    detail = memory.get_assignment_detail(assignment["assignment_id"])
    nudges = [
        event for event in detail["events"] if event["event_type"] == "review_nudge_dispatched"
    ]
    assert detail["assignment"]["status"] == "awaiting_review"
    assert result.dispatched == 1
    assert len(nudges) == 1
    assert nudges[0]["actor_id"] == "codex-integrator-loop"
    assert nudges[0]["actor_role"] == "integrator"


def test_review_nudge_is_not_duplicated_for_same_pending_event(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="loop-review-once",
        title="Loop review once",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    adapter = FakeCodexAdapter()
    runner = LoopRunner(
        memory=memory,
        config=LoopConfig(team_id="default", adapter="fake", once=True),
        adapter=adapter,
    )
    runner.run_once()
    submit_fake_worker_handoff(memory, assignment["assignment_id"])

    first = runner.run_once()
    second = runner.run_once()

    detail = memory.get_assignment_detail(assignment["assignment_id"])
    nudges = [
        event for event in detail["events"] if event["event_type"] == "review_nudge_dispatched"
    ]
    assert first.dispatched == 1
    assert second.dispatched == 0
    assert len(nudges) == 1
