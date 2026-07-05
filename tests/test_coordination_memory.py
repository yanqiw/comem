from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coordination_memory_mcp.store import (
    AuthorizationError,
    CoordinationMemory,
    LeaseConflictError,
    StaleRevisionError,
    ValidationError,
)


def open_memory(tmp_path: Path) -> CoordinationMemory:
    return CoordinationMemory(tmp_path / "coordination.sqlite3")


def test_new_store_initializes_workspace_team_actor_tables(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)

    snapshot = memory.get_snapshot()

    assert snapshot["ledger_version"] == "coordination-memory-six-table-core"
    assert snapshot["workspaces"]["default"]["name"] == "Default Workspace"
    assert snapshot["teams"]["default"]["name"] == "Default Team"


def test_create_team_auto_creates_referenced_workspace(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)

    memory.create_team(
        team_id="t-ws",
        workspace_id="ws-new",
        name="T",
        owner_actor_id="integrator",
    )

    workspaces = memory.get_snapshot()["workspaces"]
    assert "ws-new" in workspaces
    assert workspaces["ws-new"]["name"] == "ws-new"
    assert workspaces["ws-new"]["status"] == "active"


def test_create_assignment_auto_creates_referenced_workspace(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)

    memory.create_assignment(
        assignment_id="a-ws",
        title="A",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        workspace_id="ws-asn",
    )

    assert "ws-asn" in memory.get_snapshot()["workspaces"]


def test_create_assignment_derives_session_bind_from_actor_hint(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)

    assignment = memory.create_assignment(
        assignment_id="a-session-bind",
        title="Session bind",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        metadata={"assigned_actor_hint": "codex-worker-a"},
    )

    assert assignment["metadata"]["assigned_actor_hint"] == "codex-worker-a"
    assert assignment["metadata"]["session_bind"] == {
        "target_actor_id": "codex-worker-a",
        "status": "pending",
        "session_kind": "codex_thread",
    }
    detail = memory.get_assignment_detail("a-session-bind")
    created_event = detail["events"][0]
    assert created_event["event_type"] == "assignment_created"
    assert created_event["payload"]["metadata"]["session_bind"]["target_actor_id"] == (
        "codex-worker-a"
    )


def test_create_assignment_preserves_explicit_session_bind(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)

    assignment = memory.create_assignment(
        assignment_id="a-explicit-bind",
        title="Explicit bind",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        metadata={
            "assigned_actor_hint": "codex-worker-a",
            "session_bind": {
                "target_actor_id": "codex-worker-b",
                "status": "reserved",
                "session_kind": "codex_thread",
            },
        },
    )

    assert assignment["metadata"]["session_bind"] == {
        "target_actor_id": "codex-worker-b",
        "status": "reserved",
        "session_kind": "codex_thread",
    }


def test_register_workspace_upserts(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)

    memory.register_workspace(workspace_id="ws-x", name="WS X", repo_root="/r", metadata={"k": "v"})
    workspace = memory.get_snapshot()["workspaces"]["ws-x"]
    assert workspace["name"] == "WS X"
    assert workspace["repo_root"] == "/r"
    assert workspace["metadata"] == {"k": "v"}

    memory.register_workspace(workspace_id="ws-x", name="WS X2")
    assert memory.get_snapshot()["workspaces"]["ws-x"]["name"] == "WS X2"


def test_list_workspaces_includes_assignment_status_counts(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    memory.register_workspace(workspace_id="ws-a", name="Workspace A")
    memory.register_workspace(workspace_id="ws-b", name="Workspace B")
    memory.create_team(
        team_id="team-a",
        workspace_id="ws-a",
        name="Team A",
        owner_actor_id="integrator",
    )
    memory.create_team(
        team_id="team-b",
        workspace_id="ws-b",
        name="Team B",
        owner_actor_id="integrator",
    )
    ready = memory.create_assignment(
        assignment_id="task-ready",
        title="Ready",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        workspace_id="ws-a",
        team_id="team-a",
    )
    running = memory.create_assignment(
        assignment_id="task-running",
        title="Running",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        workspace_id="ws-a",
        team_id="team-a",
    )
    memory.claim_assignment(
        assignment_id=running["assignment_id"],
        actor_id="agent-a",
        actor_role="agent",
        base_revision=running["revision"],
    )
    handoff = memory.submit_handoff(
        assignment_id=ready["assignment_id"],
        actor_id="agent-b",
        actor_role="agent",
        base_revision=ready["revision"],
        payload={"summary": "ready for review"},
    )
    memory.accept_event(
        event_id=handoff["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=handoff["assignment_revision"],
        decision_note="accepted",
    )
    memory.create_assignment(
        assignment_id="task-other",
        title="Other workspace",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        workspace_id="ws-b",
        team_id="team-b",
    )

    workspaces = {w["workspace_id"]: w for w in memory.list_workspaces()}

    assert workspaces["ws-a"]["assignment_counts"] == {
        "accepted": 1,
        "claimed": 1,
    }
    assert workspaces["ws-a"]["assignment_total"] == 2
    assert workspaces["ws-a"]["team_count"] == 1
    assert workspaces["ws-a"]["teams"][0]["team_id"] == "team-a"
    assert workspaces["ws-a"]["teams"][0]["assignment_counts"] == {
        "accepted": 1,
        "claimed": 1,
    }
    assert workspaces["ws-b"]["assignment_counts"] == {"ready": 1}
    assert workspaces["ws-b"]["assignment_total"] == 1


def test_list_workspaces_includes_legacy_team_workspace_ids(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    with sqlite3.connect(memory.db_path) as conn:
        conn.execute(
            """
            insert into teams (
                team_id, workspace_id, name, phase_key, owner_actor_id, status,
                settings_json, created_at, updated_at
            )
            values (?, ?, ?, null, ?, 'active', '{}', ?, ?)
            """,
            (
                "team-legacy",
                "ws-legacy",
                "Legacy Team",
                "integrator",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    workspaces = {w["workspace_id"]: w for w in memory.list_workspaces()}
    detail = memory.get_workspace_detail("ws-legacy")

    assert workspaces["ws-legacy"]["name"] == "ws-legacy"
    assert workspaces["ws-legacy"]["team_count"] == 1
    assert workspaces["ws-legacy"]["teams"][0]["team_id"] == "team-legacy"
    assert detail["workspace"]["workspace_id"] == "ws-legacy"
    assert detail["teams"][0]["team_id"] == "team-legacy"


def test_list_workspaces_surfaces_blank_workspace_teams_as_unassigned(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    with sqlite3.connect(memory.db_path) as conn:
        conn.execute(
            """
            insert into teams (
                team_id, workspace_id, name, phase_key, owner_actor_id, status,
                settings_json, created_at, updated_at
            )
            values (?, ?, ?, null, ?, 'active', '{}', ?, ?)
            """,
            (
                "team-orphan",
                "",
                "Orphan Team",
                "integrator",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
    memory.create_assignment(
        assignment_id="task-orphan",
        title="Orphan Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        workspace_id="",
        team_id="team-orphan",
    )

    workspaces = {w["workspace_id"]: w for w in memory.list_workspaces()}
    detail = memory.get_workspace_detail("__unassigned__")

    assert "" not in workspaces
    assert workspaces["__unassigned__"]["name"] == "Unassigned teams"
    assert workspaces["__unassigned__"]["metadata"] == {"virtual": True}
    assert workspaces["__unassigned__"]["team_count"] == 1
    assert workspaces["__unassigned__"]["assignment_counts"] == {"ready": 1}
    assert workspaces["__unassigned__"]["teams"][0]["team_id"] == "team-orphan"
    assert workspaces["__unassigned__"]["teams"][0]["workspace_id"] == "__unassigned__"
    assert workspaces["__unassigned__"]["teams"][0]["assignment_counts"] == {"ready": 1}
    assert detail["workspace"]["workspace_id"] == "__unassigned__"
    assert detail["teams"][0]["team_id"] == "team-orphan"
    assert detail["assignments"][0]["workspace_id"] == "__unassigned__"


def test_get_workspace_detail_returns_teams_and_assignments(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    memory.register_workspace(workspace_id="ws-detail", name="Workspace Detail")
    memory.create_team(
        team_id="team-detail",
        workspace_id="ws-detail",
        name="Team Detail",
        owner_actor_id="integrator",
    )
    memory.create_assignment(
        assignment_id="task-detail",
        title="Detail Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        workspace_id="ws-detail",
        team_id="team-detail",
    )

    detail = memory.get_workspace_detail("ws-detail")

    assert detail["workspace"]["workspace_id"] == "ws-detail"
    assert [team["team_id"] for team in detail["teams"]] == ["team-detail"]
    assert detail["teams"][0]["assignment_counts"] == {"ready": 1}
    assert detail["teams"][0]["assignment_total"] == 1
    assert [assignment["assignment_id"] for assignment in detail["assignments"]] == ["task-detail"]
    assert detail["assignment_counts"] == {"ready": 1}


def test_archive_workspace_marks_workspace_archived(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    memory.register_workspace(workspace_id="ws-archive", name="Workspace Archive")

    archived = memory.archive_workspace(
        workspace_id="ws-archive",
        actor_role="integrator",
    )

    assert archived["status"] == "archived"
    assert memory.get_workspace_detail("ws-archive")["workspace"]["status"] == "archived"


def test_register_workspace_does_not_unarchive_existing_workspace(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    memory.register_workspace(workspace_id="ws-archived", name="Archived")
    memory.archive_workspace(workspace_id="ws-archived", actor_role="integrator")

    refreshed = memory.register_workspace(workspace_id="ws-archived", name="Still Archived")

    assert refreshed["name"] == "Still Archived"
    assert refreshed["status"] == "archived"


def test_archive_workspace_requires_integrator(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    memory.register_workspace(workspace_id="ws-archive-auth", name="Workspace Archive")

    with pytest.raises(AuthorizationError):
        memory.archive_workspace(
            workspace_id="ws-archive-auth",
            actor_role="agent",
        )


def test_server_registers_workspace_tools() -> None:
    import inspect

    from coordination_memory_mcp import server as server_mod

    src = inspect.getsource(server_mod.main)
    for tool in ["list_workspaces", "get_workspace_detail", "archive_workspace"]:
        assert f"def {tool}(" in src, f"missing MCP tool: {tool}"


def test_inserted_events_default_to_internal_safety_label(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-safety-label",
        title="Safety label default",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    event = memory.submit_handoff(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-1",
        actor_role="agent",
        base_revision=assignment["revision"],
        payload={"summary": "safety label defaulted"},
    )

    decision = memory.accept_event(
        event_id=event["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=event["assignment_revision"],
        decision_note="safety label accepted",
    )

    assert event["safety_label"] == "internal"
    assert decision["safety_label"] == "internal"
    with sqlite3.connect(memory.db_path) as conn:
        actor = conn.execute(
            "select actor_kind from actors where actor_id = ?",
            ("agent-1",),
        ).fetchone()
    assert actor == ("coding_agent",)


def test_two_teams_do_not_share_default_board_state(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    memory.register_actor(
        actor_id="integrator-a",
        actor_kind="integrator",
        display_name="Integrator A",
        provider="codex",
    )
    memory.register_actor(
        actor_id="integrator-b",
        actor_kind="integrator",
        display_name="Integrator B",
        provider="codex",
    )
    memory.create_team(
        team_id="team-a",
        workspace_id="default",
        name="Team A",
        owner_actor_id="integrator-a",
    )
    memory.create_team(
        team_id="team-b",
        workspace_id="default",
        name="Team B",
        owner_actor_id="integrator-b",
    )
    memory.create_assignment(
        assignment_id="a-task",
        title="A task",
        actor_id="integrator-a",
        actor_role="integrator",
        base_revision=0,
        team_id="team-a",
    )
    memory.create_assignment(
        assignment_id="b-task",
        title="B task",
        actor_id="integrator-b",
        actor_role="integrator",
        base_revision=0,
        team_id="team-b",
    )

    assert [
        item["assignment_id"] for item in memory.get_team_board("team-a")["lanes"]["ready"]
    ] == ["a-task"]
    assert [
        item["assignment_id"] for item in memory.get_team_board("team-b")["lanes"]["ready"]
    ] == ["b-task"]


def test_claim_assignment_creates_active_run(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="long-task",
        title="Long task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )

    claimed = memory.claim_assignment(
        assignment_id="long-task",
        actor_id="codex-a",
        actor_role="agent",
        base_revision=assignment["revision"],
        lease_ttl_seconds=3600,
        session_kind="codex_thread",
        session_ref="thread-123",
        interactive_url="codex://thread/thread-123",
        worktree_path="/tmp/worktrees/long-task",
        branch="codex/long-task",
        base_commit="abc123",
    )

    run = memory.get_run_detail(claimed["active_run_id"])
    assert run["actor_id"] == "codex-a"
    assert run["status"] == "claimed"
    assert run["session_ref"] == "thread-123"
    assert run["worktree_path"] == "/tmp/worktrees/long-task"


def test_record_run_binding_updates_metadata_and_appends_event(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="binding-task",
        title="Binding task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="codex-worker",
        actor_role="agent",
        base_revision=assignment["revision"],
        session_kind="codex_thread",
        session_ref="thread-1",
    )

    run = memory.record_run_binding(
        run_id=claimed["active_run_id"],
        actor_id="codex-worker",
        actor_role="agent",
        binding_patch={
            "adapter": {"kind": "fake_codex", "version": "test"},
            "communication_cursor": {
                "last_command_id": "cmd_start_assignment_binding-task_rev2_attempt1",
                "last_seen_turn_id": "turn-1",
            },
        },
        event_payload={"summary": "fake adapter bound"},
    )

    assert run["metadata"]["adapter"]["kind"] == "fake_codex"
    assert run["metadata"]["communication_cursor"]["last_seen_turn_id"] == "turn-1"
    assert run["events"][-1]["event_type"] == "run_binding_recorded"
    assert run["events"][-1]["status"] == "observed"


def test_agent_record_run_binding_rejects_another_actor_run(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="binding-owner",
        title="Binding owner",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    with pytest.raises(AuthorizationError):
        memory.record_run_binding(
            run_id=claimed["active_run_id"],
            actor_id="agent-b",
            actor_role="agent",
            binding_patch={"adapter": {"kind": "fake_codex"}},
        )


def test_integrator_can_record_run_binding_for_active_run(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="binding-integrator",
        title="Binding integrator",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    run = memory.record_run_binding(
        run_id=claimed["active_run_id"],
        actor_id="integrator",
        actor_role="integrator",
        binding_patch={"communication_cursor": {"last_loop_check_at": "2026-07-05T00:00:00+00:00"}},
    )

    assert (
        run["metadata"]["communication_cursor"]["last_loop_check_at"] == "2026-07-05T00:00:00+00:00"
    )


def test_record_run_binding_rejects_completed_run(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="binding-complete",
        title="Binding complete",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    memory.submit_handoff(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-a",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "done"},
    )

    with pytest.raises(ValidationError):
        memory.record_run_binding(
            run_id=claimed["active_run_id"],
            actor_id="agent-a",
            actor_role="agent",
            binding_patch={"communication_cursor": {"last_seen_turn_id": "turn-2"}},
        )


def test_mcp_exposed_store_methods_cover_team_run_and_review_flow(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    memory.register_actor(
        actor_id="codex-ui",
        actor_kind="coding_agent",
        display_name="Codex UI",
        provider="codex",
    )
    assignment = memory.create_assignment(
        assignment_id="mcp-flow",
        title="MCP flow",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        acceptance_criteria=["tests pass"],
    )
    claimed = memory.claim_assignment(
        assignment_id="mcp-flow",
        actor_id="codex-ui",
        actor_role="agent",
        base_revision=assignment["revision"],
        session_kind="codex_thread",
        session_ref="thread-ui",
    )
    memory.heartbeat_run(
        run_id=claimed["active_run_id"],
        actor_id="codex-ui",
        actor_role="agent",
        summary="running",
    )

    board = memory.get_team_board("default")
    detail = memory.get_assignment_detail("mcp-flow")
    run = memory.get_run_detail(claimed["active_run_id"])

    assert board["lanes"]["running"][0]["assignment_id"] == "mcp-flow"
    assert detail["runs"][0]["session_ref"] == "thread-ui"
    assert run["events"][-1]["event_type"] == "run_heartbeat"


def test_stale_write_is_rejected(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-network",
        title="Runtime gate",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )

    memory.append_event(
        assignment_id=assignment["assignment_id"],
        event_type="evidence_report",
        status="observed",
        actor_id="agent-3",
        actor_role="agent",
        base_revision=assignment["revision"],
        payload={"summary": "probe evidence captured"},
    )

    with pytest.raises(StaleRevisionError):
        memory.append_event(
            assignment_id=assignment["assignment_id"],
            event_type="evidence_report",
            status="completed_gate_passed",
            actor_id="agent-3",
            actor_role="agent",
            base_revision=assignment["revision"],
            payload={"summary": "stale completion"},
        )


def test_agent_cannot_accept_event(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-alpha",
        title="Control Panel evidence",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    event = memory.submit_handoff(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-5",
        actor_role="agent",
        base_revision=assignment["revision"],
        payload={"summary": "read-only evidence console ready"},
    )

    with pytest.raises(AuthorizationError):
        memory.accept_event(
            event_id=event["event_id"],
            actor_id="agent-5",
            actor_role="agent",
            base_revision=event["assignment_revision"],
            decision_note="agent self-accept attempted",
        )


def test_unexpired_claim_blocks_different_actor(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-policy",
        title="Policy control package",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
        lease_ttl_seconds=3600,
    )

    with pytest.raises(LeaseConflictError):
        memory.claim_assignment(
            assignment_id=assignment["assignment_id"],
            actor_id="agent-b",
            actor_role="agent",
            base_revision=claimed["revision"],
            lease_ttl_seconds=3600,
        )


def test_same_actor_can_renew_unexpired_claim(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-gateway",
        title="Knowledge context gateway",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-2",
        actor_role="agent",
        base_revision=assignment["revision"],
        lease_ttl_seconds=3600,
    )

    renewed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-2",
        actor_role="agent",
        base_revision=claimed["revision"],
        lease_ttl_seconds=7200,
    )

    assert renewed["claimed_by"] == "agent-2"
    assert renewed["active_run_id"] == claimed["active_run_id"]
    assert renewed["revision"] == claimed["revision"] + 1
    with sqlite3.connect(memory.db_path) as conn:
        active_runs = conn.execute(
            """
            select run_id, status
            from runs
            where assignment_id = ?
              and status != 'superseded'
            """,
            (assignment["assignment_id"],),
        ).fetchall()
    assert active_runs == [(claimed["active_run_id"], "claimed")]


def test_different_actor_can_claim_after_lease_expiry(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-git-submit",
        title="Git submission",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    expired = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
        lease_ttl_seconds=-1,
    )

    claimed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-b",
        actor_role="agent",
        base_revision=expired["revision"],
        lease_ttl_seconds=3600,
    )

    assert claimed["claimed_by"] == "agent-b"
    assert claimed["active_run_id"] != expired["active_run_id"]
    with sqlite3.connect(memory.db_path) as conn:
        previous_run = conn.execute(
            """
            select status, ended_at
            from runs
            where run_id = ?
            """,
            (expired["active_run_id"],),
        ).fetchone()
        active_runs = conn.execute(
            """
            select run_id, status
            from runs
            where assignment_id = ?
              and status != 'superseded'
            """,
            (assignment["assignment_id"],),
        ).fetchall()
    assert previous_run[0] == "superseded"
    assert previous_run[1] is not None
    assert active_runs == [(claimed["active_run_id"], "claimed")]


def test_handoff_after_claim_is_attached_to_active_run(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="run-scoped-handoff",
        title="Run scoped handoff",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    handoff = memory.submit_handoff(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-a",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "handoff attached to active run"},
    )

    run = memory.get_run_detail(claimed["active_run_id"])
    assert handoff["run_id"] == claimed["active_run_id"]
    assert handoff["event_id"] in [event["event_id"] for event in run["events"]]


def test_agent_append_event_rejects_another_actor_active_run(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="append-active-owner",
        title="Append active owner",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="append-active-owner",
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    with pytest.raises(AuthorizationError):
        memory.append_event(
            assignment_id="append-active-owner",
            event_type="evidence_report",
            status="observed",
            actor_id="agent-b",
            actor_role="agent",
            base_revision=claimed["revision"],
            payload={"summary": "wrong actor evidence"},
        )

    detail = memory.get_run_detail(claimed["active_run_id"])
    assert [event["event_type"] for event in detail["events"]] == ["run_claimed"]


def test_agent_submit_handoff_rejects_another_actor_active_run(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="handoff-active-owner",
        title="Handoff active owner",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="handoff-active-owner",
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    with pytest.raises(AuthorizationError):
        memory.submit_handoff(
            assignment_id="handoff-active-owner",
            actor_id="agent-b",
            actor_role="agent",
            base_revision=claimed["revision"],
            payload={"summary": "wrong actor handoff"},
        )

    board = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board["lanes"]["running"]] == ["handoff-active-owner"]


def test_assignment_detail_includes_runs_and_events(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="detail-task",
        title="Detail task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="detail-task",
        actor_id="codex-detail",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    memory.heartbeat_run(
        run_id=claimed["active_run_id"],
        actor_id="codex-detail",
        actor_role="agent",
        summary="working",
    )

    detail = memory.get_assignment_detail("detail-task")

    assert detail["assignment"]["assignment_id"] == "detail-task"
    assert len(detail["runs"]) == 1
    assert [event["event_type"] for event in detail["events"]] == [
        "assignment_created",
        "run_claimed",
        "run_heartbeat",
    ]


def test_run_heartbeat_updates_liveness_and_timeline(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="heartbeat-task",
        title="Heartbeat task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="heartbeat-task",
        actor_id="codex-heartbeat",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    heartbeat = memory.heartbeat_run(
        run_id=claimed["active_run_id"],
        actor_id="codex-heartbeat",
        actor_role="agent",
        summary="implemented storage tests",
    )

    detail = memory.get_run_detail(claimed["active_run_id"])
    assert detail["status"] == "running"
    assert detail["heartbeat_at"] == heartbeat["created_at"]
    assert detail["events"][-1]["event_type"] == "run_heartbeat"


def test_agent_heartbeat_rejects_another_actor_active_run(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="heartbeat-owner-task",
        title="Heartbeat owner task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="heartbeat-owner-task",
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    with pytest.raises(AuthorizationError):
        memory.heartbeat_run(
            run_id=claimed["active_run_id"],
            actor_id="agent-b",
            actor_role="agent",
            summary="wrong actor heartbeat",
        )

    detail = memory.get_run_detail(claimed["active_run_id"])
    assert detail["status"] == "claimed"
    assert [event["event_type"] for event in detail["events"]] == ["run_claimed"]


def test_agent_request_intervention_rejects_another_actor_active_run(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="intervention-owner-task",
        title="Intervention owner task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="intervention-owner-task",
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    with pytest.raises(AuthorizationError):
        memory.request_intervention(
            run_id=claimed["active_run_id"],
            actor_id="agent-b",
            actor_role="agent",
            prompt="wrong actor intervention",
            intervention_kind="approval",
        )

    board = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board["lanes"]["running"]] == [
        "intervention-owner-task"
    ]


def test_superseded_run_cannot_heartbeat_active_assignment(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="superseded-heartbeat-task",
        title="Superseded heartbeat task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    expired = memory.claim_assignment(
        assignment_id="superseded-heartbeat-task",
        actor_id="codex-expired",
        actor_role="agent",
        base_revision=assignment["revision"],
        lease_ttl_seconds=-1,
    )
    active = memory.claim_assignment(
        assignment_id="superseded-heartbeat-task",
        actor_id="codex-active",
        actor_role="agent",
        base_revision=expired["revision"],
    )
    memory.request_intervention(
        run_id=active["active_run_id"],
        actor_id="codex-active",
        actor_role="agent",
        prompt="Need active-run input",
        intervention_kind="approval",
    )

    with pytest.raises(ValidationError):
        memory.heartbeat_run(
            run_id=expired["active_run_id"],
            actor_id="codex-expired",
            actor_role="agent",
            summary="stale heartbeat",
        )

    board = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board["lanes"]["awaiting_human"]] == [
        "superseded-heartbeat-task"
    ]
    assert board["lanes"]["running"] == []


def test_heartbeat_preserves_awaiting_human_status(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="awaiting-human-heartbeat-task",
        title="Awaiting human heartbeat task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="awaiting-human-heartbeat-task",
        actor_id="codex-waiting",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    memory.request_intervention(
        run_id=claimed["active_run_id"],
        actor_id="codex-waiting",
        actor_role="agent",
        prompt="Need input before continuing",
        intervention_kind="approval",
    )

    memory.heartbeat_run(
        run_id=claimed["active_run_id"],
        actor_id="codex-waiting",
        actor_role="agent",
        summary="still waiting",
    )

    detail = memory.get_run_detail(claimed["active_run_id"])
    board = memory.get_team_board("default")
    assert detail["status"] == "awaiting_human"
    assert detail["events"][-1]["event_type"] == "run_heartbeat"
    assert [item["assignment_id"] for item in board["lanes"]["awaiting_human"]] == [
        "awaiting-human-heartbeat-task"
    ]


def test_heartbeat_rejects_reviewed_assignment(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="accepted-heartbeat-task",
        title="Accepted heartbeat task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="accepted-heartbeat-task",
        actor_id="codex-accepted",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    handoff = memory.submit_handoff(
        assignment_id="accepted-heartbeat-task",
        actor_id="codex-accepted",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "ready for review"},
    )
    memory.accept_event(
        event_id=handoff["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=handoff["assignment_revision"],
        decision_note="accepted",
    )

    board_before = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board_before["lanes"]["accepted"]] == [
        "accepted-heartbeat-task"
    ]

    with pytest.raises(ValidationError):
        memory.heartbeat_run(
            run_id=claimed["active_run_id"],
            actor_id="codex-accepted",
            actor_role="agent",
            summary="late heartbeat",
        )

    board_after = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board_after["lanes"]["accepted"]] == [
        "accepted-heartbeat-task"
    ]


def test_append_and_handoff_reject_accepted_assignment(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="accepted-write-task",
        title="Accepted write task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="accepted-write-task",
        actor_id="codex-accepted-write",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    handoff = memory.submit_handoff(
        assignment_id="accepted-write-task",
        actor_id="codex-accepted-write",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "ready for review"},
    )
    memory.accept_event(
        event_id=handoff["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=handoff["assignment_revision"],
        decision_note="accepted",
    )
    current = memory.get_assignment_detail("accepted-write-task")["assignment"]

    with pytest.raises(ValidationError):
        memory.append_event(
            assignment_id="accepted-write-task",
            event_type="evidence_report",
            status="observed",
            actor_id="codex-accepted-write",
            actor_role="agent",
            base_revision=current["revision"],
            payload={"summary": "late evidence"},
        )
    with pytest.raises(ValidationError):
        memory.submit_handoff(
            assignment_id="accepted-write-task",
            actor_id="codex-accepted-write",
            actor_role="agent",
            base_revision=current["revision"],
            payload={"summary": "late handoff"},
        )

    board = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board["lanes"]["accepted"]] == ["accepted-write-task"]


def test_claim_rejects_accepted_assignment(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="accepted-claim-task",
        title="Accepted claim task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="accepted-claim-task",
        actor_id="codex-accepted-claim",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    handoff = memory.submit_handoff(
        assignment_id="accepted-claim-task",
        actor_id="codex-accepted-claim",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "ready for review"},
    )
    memory.accept_event(
        event_id=handoff["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=handoff["assignment_revision"],
        decision_note="accepted",
    )
    current = memory.get_assignment_detail("accepted-claim-task")["assignment"]

    with pytest.raises(ValidationError):
        memory.claim_assignment(
            assignment_id="accepted-claim-task",
            actor_id="codex-accepted-claim",
            actor_role="agent",
            base_revision=current["revision"],
        )

    board = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board["lanes"]["accepted"]] == ["accepted-claim-task"]


def test_append_and_handoff_reject_rejected_assignment(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="rejected-write-task",
        title="Rejected write task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="rejected-write-task",
        actor_id="codex-rejected-write",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    handoff = memory.submit_handoff(
        assignment_id="rejected-write-task",
        actor_id="codex-rejected-write",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "ready for review"},
    )
    memory.reject_event(
        event_id=handoff["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=handoff["assignment_revision"],
        decision_note="rejected",
    )
    current = memory.get_assignment_detail("rejected-write-task")["assignment"]

    with pytest.raises(ValidationError):
        memory.append_event(
            assignment_id="rejected-write-task",
            event_type="evidence_report",
            status="observed",
            actor_id="codex-rejected-write",
            actor_role="agent",
            base_revision=current["revision"],
            payload={"summary": "late evidence"},
        )
    with pytest.raises(ValidationError):
        memory.submit_handoff(
            assignment_id="rejected-write-task",
            actor_id="codex-rejected-write",
            actor_role="agent",
            base_revision=current["revision"],
            payload={"summary": "late handoff"},
        )

    board = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board["lanes"]["rejected"]] == ["rejected-write-task"]


def test_claim_rejects_rejected_assignment(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="rejected-claim-task",
        title="Rejected claim task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="rejected-claim-task",
        actor_id="codex-rejected-claim",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    handoff = memory.submit_handoff(
        assignment_id="rejected-claim-task",
        actor_id="codex-rejected-claim",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "ready for review"},
    )
    memory.reject_event(
        event_id=handoff["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=handoff["assignment_revision"],
        decision_note="rejected",
    )
    current = memory.get_assignment_detail("rejected-claim-task")["assignment"]

    with pytest.raises(ValidationError):
        memory.claim_assignment(
            assignment_id="rejected-claim-task",
            actor_id="codex-rejected-claim",
            actor_role="agent",
            base_revision=current["revision"],
        )

    board = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board["lanes"]["rejected"]] == ["rejected-claim-task"]


def test_intervention_moves_assignment_to_awaiting_human(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="human-input-task",
        title="Human input task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="human-input-task",
        actor_id="codex-human",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    request = memory.request_intervention(
        run_id=claimed["active_run_id"],
        actor_id="codex-human",
        actor_role="agent",
        prompt="Approve using existing worktree?",
        intervention_kind="approval",
    )

    board = memory.get_team_board("default")
    assert request["event_type"] == "intervention_requested"
    assert [item["assignment_id"] for item in board["lanes"]["awaiting_human"]] == [
        "human-input-task"
    ]


def test_intervention_response_returns_assignment_to_running(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="human-response-task",
        title="Human response task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="human-response-task",
        actor_id="codex-human-response",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    request = memory.request_intervention(
        run_id=claimed["active_run_id"],
        actor_id="codex-human-response",
        actor_role="agent",
        prompt="Approve continuing?",
        intervention_kind="approval",
    )

    response = memory.respond_intervention(
        run_id=claimed["active_run_id"],
        actor_id="integrator",
        actor_role="human",
        response="Approved",
        reviewed_event_id=request["event_id"],
    )

    detail = memory.get_run_detail(claimed["active_run_id"])
    board = memory.get_team_board("default")
    assert response["event_type"] == "intervention_responded"
    assert response["reviewed_event_id"] == request["event_id"]
    assert detail["status"] == "running"
    assert detail["events"][-1]["payload"] == {
        "response": "Approved",
        "reviewed_event_id": request["event_id"],
    }
    assert [item["assignment_id"] for item in board["lanes"]["running"]] == ["human-response-task"]


def test_integrator_intervention_response_returns_assignment_to_running(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="integrator-response-task",
        title="Integrator response task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="integrator-response-task",
        actor_id="codex-integrator-response",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    request = memory.request_intervention(
        run_id=claimed["active_run_id"],
        actor_id="codex-integrator-response",
        actor_role="agent",
        prompt="Approve continuing?",
        intervention_kind="approval",
    )

    response = memory.respond_intervention(
        run_id=claimed["active_run_id"],
        actor_id="integrator",
        actor_role="integrator",
        response="Approved",
        reviewed_event_id=request["event_id"],
    )

    detail = memory.get_run_detail(claimed["active_run_id"])
    assert response["reviewed_event_id"] == request["event_id"]
    assert detail["status"] == "running"


def test_intervention_response_requires_reviewed_event_id(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="required-review-target-task",
        title="Required review target task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="required-review-target-task",
        actor_id="codex-required-review",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    request = memory.request_intervention(
        run_id=claimed["active_run_id"],
        actor_id="codex-required-review",
        actor_role="agent",
        prompt="Need approval before continuing",
        intervention_kind="approval",
    )

    with pytest.raises(ValidationError):
        memory.respond_intervention(
            run_id=claimed["active_run_id"],
            actor_id="integrator",
            actor_role="human",
            response="Approved",
        )

    detail = memory.get_run_detail(claimed["active_run_id"])
    board = memory.get_team_board("default")
    assert detail["status"] == "awaiting_human"
    assert detail["events"][-1]["event_id"] == request["event_id"]
    assert [item["assignment_id"] for item in board["lanes"]["awaiting_human"]] == [
        "required-review-target-task"
    ]


def test_intervention_response_requires_awaiting_run(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="not-awaiting-response-task",
        title="Not awaiting response task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="not-awaiting-response-task",
        actor_id="codex-not-awaiting",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    request = memory.request_intervention(
        run_id=claimed["active_run_id"],
        actor_id="codex-not-awaiting",
        actor_role="agent",
        prompt="Need approval before continuing",
        intervention_kind="approval",
    )
    memory.respond_intervention(
        run_id=claimed["active_run_id"],
        actor_id="integrator",
        actor_role="human",
        response="Approved",
        reviewed_event_id=request["event_id"],
    )

    with pytest.raises(ValidationError):
        memory.respond_intervention(
            run_id=claimed["active_run_id"],
            actor_id="integrator",
            actor_role="human",
            response="Approved again",
            reviewed_event_id=request["event_id"],
        )

    board = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board["lanes"]["running"]] == [
        "not-awaiting-response-task"
    ]


def test_agent_intervention_response_rejects_another_actor_active_run(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="wrong-agent-response-task",
        title="Wrong agent response task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="wrong-agent-response-task",
        actor_id="agent-a",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    request = memory.request_intervention(
        run_id=claimed["active_run_id"],
        actor_id="agent-a",
        actor_role="agent",
        prompt="Need approval before continuing",
        intervention_kind="approval",
    )

    with pytest.raises(AuthorizationError):
        memory.respond_intervention(
            run_id=claimed["active_run_id"],
            actor_id="agent-b",
            actor_role="agent",
            response="Approved",
            reviewed_event_id=request["event_id"],
        )

    board = memory.get_team_board("default")
    assert [item["assignment_id"] for item in board["lanes"]["awaiting_human"]] == [
        "wrong-agent-response-task"
    ]


def test_intervention_response_rejects_missing_review_target(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="missing-review-target-task",
        title="Missing review target task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="missing-review-target-task",
        actor_id="codex-missing-review",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    memory.request_intervention(
        run_id=claimed["active_run_id"],
        actor_id="codex-missing-review",
        actor_role="agent",
        prompt="Need input before continuing",
        intervention_kind="approval",
    )

    with pytest.raises(ValidationError):
        memory.respond_intervention(
            run_id=claimed["active_run_id"],
            actor_id="integrator",
            actor_role="human",
            response="Approved",
            reviewed_event_id="evt_missing",
        )


def test_intervention_response_rejects_wrong_run_review_target(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment_a = memory.create_assignment(
        assignment_id="wrong-run-a",
        title="Wrong run A",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    assignment_b = memory.create_assignment(
        assignment_id="wrong-run-b",
        title="Wrong run B",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed_a = memory.claim_assignment(
        assignment_id="wrong-run-a",
        actor_id="codex-a",
        actor_role="agent",
        base_revision=assignment_a["revision"],
    )
    claimed_b = memory.claim_assignment(
        assignment_id="wrong-run-b",
        actor_id="codex-b",
        actor_role="agent",
        base_revision=assignment_b["revision"],
    )
    request_a = memory.request_intervention(
        run_id=claimed_a["active_run_id"],
        actor_id="codex-a",
        actor_role="agent",
        prompt="Need input for A",
        intervention_kind="approval",
    )
    memory.request_intervention(
        run_id=claimed_b["active_run_id"],
        actor_id="codex-b",
        actor_role="agent",
        prompt="Need input for B",
        intervention_kind="approval",
    )

    with pytest.raises(ValidationError):
        memory.respond_intervention(
            run_id=claimed_b["active_run_id"],
            actor_id="integrator",
            actor_role="human",
            response="Approved",
            reviewed_event_id=request_a["event_id"],
        )


def test_intervention_response_rejects_wrong_type_review_target(
    tmp_path: Path,
) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="wrong-type-review-target-task",
        title="Wrong type review target task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="wrong-type-review-target-task",
        actor_id="codex-wrong-type",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    heartbeat = memory.heartbeat_run(
        run_id=claimed["active_run_id"],
        actor_id="codex-wrong-type",
        actor_role="agent",
        summary="not an intervention request",
    )
    memory.request_intervention(
        run_id=claimed["active_run_id"],
        actor_id="codex-wrong-type",
        actor_role="agent",
        prompt="Need input before continuing",
        intervention_kind="approval",
    )

    with pytest.raises(ValidationError):
        memory.respond_intervention(
            run_id=claimed["active_run_id"],
            actor_id="integrator",
            actor_role="human",
            response="Approved",
            reviewed_event_id=heartbeat["event_id"],
        )


def test_assignment_claims_do_not_enter_pending_reviews(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-network",
        title="Runtime gate",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-3",
        actor_role="agent",
        base_revision=assignment["revision"],
    )

    assert memory.list_pending_reviews() == []

    evidence = memory.append_event(
        assignment_id=assignment["assignment_id"],
        event_type="evidence_report",
        status="observed",
        actor_id="agent-3",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "direct probe evidence captured"},
    )

    assert [item["event_id"] for item in memory.list_pending_reviews()] == [evidence["event_id"]]


def test_needs_fix_decision_does_not_create_pending_review(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-alpha",
        title="Control Panel evidence",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    event = memory.submit_handoff(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-5",
        actor_role="agent",
        base_revision=assignment["revision"],
        payload={"summary": "evidence UI needs another pass"},
    )

    decision = memory.review_event(
        event_id=event["event_id"],
        decision_status="needs_fix",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=event["assignment_revision"],
        decision_note="surface failed gate evidence before accept",
    )

    assert decision["status"] == "needs_fix"
    assert memory.list_pending_reviews() == []


def test_same_actor_retry_after_needs_fix_creates_new_run(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="needs-fix-retry-task",
        title="Needs fix retry task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="needs-fix-retry-task",
        actor_id="codex-retry",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    handoff = memory.submit_handoff(
        assignment_id="needs-fix-retry-task",
        actor_id="codex-retry",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "needs review"},
    )
    decision = memory.review_event(
        event_id=handoff["event_id"],
        decision_status="needs_fix",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=handoff["assignment_revision"],
        decision_note="retry required",
    )

    with pytest.raises(ValidationError):
        memory.append_event(
            assignment_id="needs-fix-retry-task",
            event_type="evidence_report",
            status="observed",
            actor_id="codex-retry",
            actor_role="agent",
            base_revision=decision["assignment_revision"],
            payload={"summary": "fix without retry claim"},
        )
    with pytest.raises(ValidationError):
        memory.submit_handoff(
            assignment_id="needs-fix-retry-task",
            actor_id="codex-retry",
            actor_role="agent",
            base_revision=decision["assignment_revision"],
            payload={"summary": "handoff without retry claim"},
        )

    retry = memory.claim_assignment(
        assignment_id="needs-fix-retry-task",
        actor_id="codex-retry",
        actor_role="agent",
        base_revision=decision["assignment_revision"],
    )

    old_run = memory.get_run_detail(claimed["active_run_id"])
    new_run = memory.get_run_detail(retry["active_run_id"])
    assert retry["status"] == "claimed"
    assert retry["active_run_id"] != claimed["active_run_id"]
    assert old_run["status"] == "completed_gate_failed"
    assert old_run["ended_at"] is not None
    assert new_run["attempt"] == old_run["attempt"] + 1
    assert new_run["status"] == "claimed"
    assert new_run["ended_at"] is None


def test_integrator_accept_updates_snapshot_and_review_queue(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-baseline",
        title="Baseline evidence",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    event = memory.submit_handoff(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-1",
        actor_role="agent",
        base_revision=assignment["revision"],
        payload={"summary": "static gate passed"},
    )

    assert [item["event_id"] for item in memory.list_pending_reviews()] == [event["event_id"]]

    accepted = memory.accept_event(
        event_id=event["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=event["assignment_revision"],
        decision_note="static gate accepted",
    )

    snapshot = memory.get_snapshot()
    assert accepted["status"] == "integrator_accepted"
    assert memory.list_pending_reviews() == []
    assert snapshot["active_assignments"]["task-baseline"]["status"] == ("integrator_accepted")
    assert snapshot["accepted_events"][0]["event_id"] == event["event_id"]
    assert snapshot["accepted_events"][0]["payload"]["summary"] == "static gate passed"


def test_review_rejects_assignment_created_event(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="non-reviewable-create-task",
        title="Non-reviewable create task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    created_event = memory.get_assignment_detail("non-reviewable-create-task")["events"][0]

    with pytest.raises(ValidationError):
        memory.accept_event(
            event_id=created_event["event_id"],
            actor_id="integrator",
            actor_role="integrator",
            base_revision=assignment["revision"],
            decision_note="invalid accept",
        )

    assert memory.get_snapshot()["accepted_events"] == []
    assert memory.get_team_board("default")["lanes"]["accepted"] == []


def test_review_rejects_run_heartbeat_event(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="non-reviewable-heartbeat-task",
        title="Non-reviewable heartbeat task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="non-reviewable-heartbeat-task",
        actor_id="codex-heartbeat-review",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    heartbeat = memory.heartbeat_run(
        run_id=claimed["active_run_id"],
        actor_id="codex-heartbeat-review",
        actor_role="agent",
        summary="still working",
    )

    with pytest.raises(ValidationError):
        memory.accept_event(
            event_id=heartbeat["event_id"],
            actor_id="integrator",
            actor_role="integrator",
            base_revision=claimed["revision"],
            decision_note="invalid accept",
        )

    assert memory.get_snapshot()["accepted_events"] == []
    assert memory.get_team_board("default")["lanes"]["accepted"] == []


def test_handoff_review_and_export_remain_integrator_owned(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="accepted-task",
        title="Accepted task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    claimed = memory.claim_assignment(
        assignment_id="accepted-task",
        actor_id="codex-accepted",
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    handoff = memory.submit_handoff(
        assignment_id="accepted-task",
        actor_id="codex-accepted",
        actor_role="agent",
        base_revision=claimed["revision"],
        payload={"summary": "ready for review"},
    )

    assert [event["event_id"] for event in memory.list_pending_reviews()] == [handoff["event_id"]]
    assert [
        item["assignment_id"]
        for item in memory.get_team_board("default")["lanes"]["awaiting_review"]
    ] == ["accepted-task"]

    memory.accept_event(
        event_id=handoff["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=handoff["assignment_revision"],
        decision_note="accepted",
    )

    snapshot = memory.get_snapshot()
    board = memory.get_team_board("default")
    run = memory.get_run_detail(claimed["active_run_id"])
    assert snapshot["active_assignments"]["accepted-task"]["status"] == ("integrator_accepted")
    assert memory.list_pending_reviews() == []
    assert [item["assignment_id"] for item in board["lanes"]["accepted"]] == ["accepted-task"]
    assert run["status"] == "completed_gate_passed"
    assert run["ended_at"] is not None


def test_export_projection_writes_accepted_state(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-alpha",
        title="Control Panel evidence",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    event = memory.submit_handoff(
        assignment_id=assignment["assignment_id"],
        actor_id="agent-5",
        actor_role="agent",
        base_revision=assignment["revision"],
        payload={
            "summary": "read model reviewed",
            "contract_versions": {"example.read_model.v1": "review"},
        },
    )
    memory.accept_event(
        event_id=event["event_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=event["assignment_revision"],
        decision_note="read-only boundary accepted",
    )

    output_dir = tmp_path / "projection"
    result = memory.export_git_projection(output_dir=output_dir, actor_role="integrator")

    accepted_state = json.loads(
        (output_dir / "coordination-memory" / "snapshots" / "accepted-state.json").read_text()
    )
    assert result["accepted_state_path"].endswith("accepted-state.json")
    assert accepted_state["schema_version"] == "agent_team.collaboration.snapshot.v1"
    assert accepted_state["single_writer_rules"]["accepted_ledger_writer"] == "Integrator"
    assert accepted_state["active_assignments"]["task-alpha"]["status"] == "integrator_accepted"
    assert accepted_state["accepted_events"][0]["payload"]["summary"] == ("read model reviewed")


def test_completed_gate_failed_is_not_projected_as_accepted(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    assignment = memory.create_assignment(
        assignment_id="task-network",
        title="Runtime live gate",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    memory.append_event(
        assignment_id=assignment["assignment_id"],
        event_type="evidence_report",
        status="completed_gate_failed",
        actor_id="agent-3",
        actor_role="agent",
        base_revision=assignment["revision"],
        payload={"summary": "direct probe release gate failed"},
    )

    snapshot = memory.get_snapshot()
    assert snapshot["accepted_events"] == []
    assert "task-network" not in snapshot["active_assignments"]
