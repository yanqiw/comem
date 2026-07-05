from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coordination_memory_mcp.store import (
    ASSIGNMENT_STATUSES,
    AuthorizationError,
    CoordinationMemory,
    StaleRevisionError,
    ValidationError,
)


def open_memory(tmp_path: Path) -> CoordinationMemory:
    return CoordinationMemory(tmp_path / "coordination.sqlite3")


def _claimed_assignment(memory: CoordinationMemory, assignment_id: str) -> dict:
    assignment = memory.create_assignment(
        assignment_id=assignment_id,
        title="Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    return memory.claim_assignment(
        assignment_id=assignment_id,
        actor_id="agent-1",
        actor_role="agent",
        base_revision=assignment["revision"],
        session_kind="codex_thread",
        session_ref="thread-1",
    )


# --- cancel_assignment ----------------------------------------------------


def test_cancel_assignment_terminalizes_and_releases_lease(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    claimed = _claimed_assignment(memory, "task-cancel")
    active_run_id = claimed["active_run_id"]

    result = memory.cancel_assignment(
        assignment_id="task-cancel",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=claimed["revision"],
        reason="created by mistake",
    )

    assert result["status"] == "cancelled"
    assert result["revision"] == claimed["revision"] + 1
    assert result["completed_at"] is not None
    assert result["active_run_id"] is None
    assert result["claimed_by"] is None
    assert result["lease_expires_at"] is None

    run = memory.get_run_detail(active_run_id)
    assert run["status"] == "cancelled"
    assert run["ended_at"] is not None

    detail = memory.get_assignment_detail("task-cancel")
    last = detail["events"][-1]
    assert last["event_type"] == "assignment_cancelled"
    assert last["actor_role"] == "integrator"
    assert last["payload"]["reason"] == "created by mistake"


def test_cancel_assignment_without_active_run(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-ready",
        title="Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )

    result = memory.cancel_assignment(
        assignment_id="task-ready",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=assignment["revision"],
        reason="no longer needed",
    )

    assert result["status"] == "cancelled"


def test_cancel_assignment_requires_integrator(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    claimed = _claimed_assignment(memory, "task-auth")

    with pytest.raises(AuthorizationError):
        memory.cancel_assignment(
            assignment_id="task-auth",
            actor_id="agent-1",
            actor_role="agent",
            base_revision=claimed["revision"],
            reason="agent self-cancel",
        )


def test_cancel_assignment_rejects_stale_revision(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    claimed = _claimed_assignment(memory, "task-stale")

    with pytest.raises(StaleRevisionError):
        memory.cancel_assignment(
            assignment_id="task-stale",
            actor_id="integrator",
            actor_role="integrator",
            base_revision=claimed["revision"] - 1,
            reason="stale",
        )


def test_cancel_assignment_rejects_already_terminal(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-twice",
        title="Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    cancelled = memory.cancel_assignment(
        assignment_id="task-twice",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=assignment["revision"],
        reason="first",
    )

    with pytest.raises(ValidationError):
        memory.cancel_assignment(
            assignment_id="task-twice",
            actor_id="integrator",
            actor_role="integrator",
            base_revision=cancelled["revision"],
            reason="second",
        )


def test_cancelled_assignment_cannot_be_claimed(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-noclaim",
        title="Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    cancelled = memory.cancel_assignment(
        assignment_id="task-noclaim",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=assignment["revision"],
        reason="void",
    )

    with pytest.raises(ValidationError):
        memory.claim_assignment(
            assignment_id="task-noclaim",
            actor_id="agent-2",
            actor_role="agent",
            base_revision=cancelled["revision"],
        )


# --- supersede_assignment -------------------------------------------------


def test_supersede_assignment_links_replacement(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    claimed = _claimed_assignment(memory, "task-old")
    active_run_id = claimed["active_run_id"]
    memory.create_assignment(
        assignment_id="task-new",
        title="Reworked task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )

    result = memory.supersede_assignment(
        assignment_id="task-old",
        superseded_by="task-new",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=claimed["revision"],
        reason="re-scoped",
    )

    assert result["status"] == "superseded"
    assert result["revision"] == claimed["revision"] + 1
    assert result["completed_at"] is not None
    assert result["active_run_id"] is None
    assert result["metadata"]["superseded_by"] == "task-new"

    run = memory.get_run_detail(active_run_id)
    assert run["status"] == "cancelled"

    detail = memory.get_assignment_detail("task-old")
    last = detail["events"][-1]
    assert last["event_type"] == "assignment_superseded"
    assert last["payload"]["superseded_by"] == "task-new"
    assert last["payload"]["reason"] == "re-scoped"


def test_superseded_is_a_valid_assignment_status() -> None:
    assert "superseded" in ASSIGNMENT_STATUSES


def test_supersede_assignment_requires_integrator(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    claimed = _claimed_assignment(memory, "task-sa-auth")
    memory.create_assignment(
        assignment_id="task-sa-new",
        title="New",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )

    with pytest.raises(AuthorizationError):
        memory.supersede_assignment(
            assignment_id="task-sa-auth",
            superseded_by="task-sa-new",
            actor_id="agent-1",
            actor_role="agent",
            base_revision=claimed["revision"],
            reason="nope",
        )


def test_supersede_rejects_unknown_replacement(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-sa-missing",
        title="Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )

    with pytest.raises(ValidationError):
        memory.supersede_assignment(
            assignment_id="task-sa-missing",
            superseded_by="does-not-exist",
            actor_id="integrator",
            actor_role="integrator",
            base_revision=assignment["revision"],
            reason="bad link",
        )


def test_server_registers_cancel_and_supersede_tools() -> None:
    import inspect

    from coordination_memory_mcp import server as server_mod

    src = inspect.getsource(server_mod.main)
    for tool in ["cancel_assignment", "supersede_assignment"]:
        assert f"def {tool}(" in src, f"missing MCP tool: {tool}"


def test_supersede_rejects_self_reference(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-sa-self",
        title="Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )

    with pytest.raises(ValidationError):
        memory.supersede_assignment(
            assignment_id="task-sa-self",
            superseded_by="task-sa-self",
            actor_id="integrator",
            actor_role="integrator",
            base_revision=assignment["revision"],
            reason="self",
        )
