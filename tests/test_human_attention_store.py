from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from coordination_memory_mcp.store import (
    AuthorizationError,
    CoordinationMemory,
    ValidationError,
)


def valid_brief(**overrides: Any) -> dict[str, Any]:
    brief: dict[str, Any] = {
        "schema_version": 1,
        "current_goal": "Implement durable human attention projections",
        "current_stage": "implementing",
        "recent_progress": ["Defined domain validation"],
        "decisions_and_risks": [],
        "human_intervention": {"needed": False, "blocking": False},
        "next_steps": ["Persist the latest brief"],
        "context_refs": ["task-2-brief"],
    }
    brief.update(overrides)
    return brief


def claimed_run(
    tmp_path: Path,
    *,
    assignment_id: str = "task-1",
    team_id: str = "default",
    actor_id: str = "agent-a",
) -> tuple[CoordinationMemory, dict[str, Any]]:
    memory = CoordinationMemory(tmp_path / "coordination.sqlite3")
    assignment = memory.create_assignment(
        assignment_id=assignment_id,
        title="Human attention persistence",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        team_id=team_id,
    )
    claimed = memory.claim_assignment(
        assignment_id=assignment_id,
        actor_id=actor_id,
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    return memory, memory.get_run_detail(claimed["active_run_id"])


def checkpoint(
    memory: CoordinationMemory,
    run: dict[str, Any],
    *,
    client_update_id: str = "brief-1",
    source_event_sequence: int | None = None,
    brief: dict[str, Any] | None = None,
    actor_id: str = "agent-a",
) -> dict[str, Any]:
    return memory.checkpoint_run(
        run_id=run["run_id"],
        actor_id=actor_id,
        actor_role="agent",
        client_update_id=client_update_id,
        source_event_sequence=(
            run["events"][0]["sequence"] if source_event_sequence is None else source_event_sequence
        ),
        brief=brief or valid_brief(),
    )


def test_checkpoint_appends_brief_without_changing_assignment_state(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)

    event = checkpoint(memory, run)
    projection = memory.get_human_brief(run["run_id"])

    assert event["event_type"] == "human_brief_updated"
    assert projection["brief"]["current_goal"] == valid_brief()["current_goal"]
    assert memory.get_assignment_detail("task-1")["assignment"]["status"] == "claimed"


def test_checkpoint_replays_identical_client_update(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)

    original = checkpoint(memory, run)
    replay = checkpoint(memory, run)

    assert replay == original
    assert [
        event
        for event in memory.get_run_detail(run["run_id"])["events"]
        if event["event_type"] == "human_brief_updated"
    ] == [original]


def test_checkpoint_rejects_changed_payload_for_client_update(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)
    checkpoint(memory, run)

    with pytest.raises(ValidationError, match="client_update_id"):
        checkpoint(
            memory,
            run,
            brief=valid_brief(current_goal="A conflicting goal"),
        )


def test_checkpoint_rejects_source_older_than_latest_brief(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)
    first_sequence = run["events"][0]["sequence"]
    heartbeat = memory.heartbeat_run(
        run_id=run["run_id"],
        actor_id="agent-a",
        actor_role="agent",
        summary="Made progress",
    )
    checkpoint(
        memory,
        run,
        source_event_sequence=heartbeat["sequence"],
    )

    with pytest.raises(ValidationError, match="source_event_sequence"):
        checkpoint(
            memory,
            run,
            client_update_id="brief-2",
            source_event_sequence=first_sequence,
        )


def test_checkpoint_rejects_another_agent(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)

    with pytest.raises(AuthorizationError, match="does not own run"):
        checkpoint(memory, run, actor_id="agent-b")


def test_checkpoint_brief_stays_fresh_past_window_without_later_work(
    tmp_path: Path,
) -> None:
    memory, run = claimed_run(tmp_path)
    event = checkpoint(memory, run)
    with sqlite3.connect(memory.db_path) as conn:
        conn.execute(
            "update events set created_at = ? where event_id = ?",
            ("2000-01-01T00:00:00+00:00", event["event_id"]),
        )

    projection = memory.get_human_brief(run["run_id"])

    assert projection["freshness"] == "fresh"
    assert projection["latest_event_sequence"] == projection["source_event_sequence"]


def test_checkpoint_brief_becomes_stale_past_window_after_later_work(
    tmp_path: Path,
) -> None:
    memory, run = claimed_run(tmp_path)
    event = checkpoint(memory, run)
    heartbeat = memory.heartbeat_run(
        run_id=run["run_id"],
        actor_id="agent-a",
        actor_role="agent",
        summary="Continued implementation",
    )
    with sqlite3.connect(memory.db_path) as conn:
        conn.execute(
            "update events set created_at = ? where event_id = ?",
            ("2000-01-01T00:00:00+00:00", event["event_id"]),
        )

    projection = memory.get_human_brief(run["run_id"])

    assert projection["freshness"] == "stale"
    assert projection["latest_event_sequence"] == heartbeat["sequence"]


def raise_attention(
    memory: CoordinationMemory,
    run_id: str,
    *,
    client_update_id: str = "attn-1",
    level: str = "yellow",
    target: str = "human",
    dedupe_key: str = "retry-budget",
    reason_code: str = "retry_near_limit",
    why_now: str = "Two attempts failed",
    recommended_action: str = "Review in next digest",
    source_event_ids: list[str] | None = None,
) -> dict[str, Any]:
    return memory.raise_attention(
        run_id=run_id,
        actor_id="agent-a",
        actor_role="agent",
        client_update_id=client_update_id,
        level=level,
        target=target,
        dedupe_key=dedupe_key,
        reason_code=reason_code,
        why_now=why_now,
        recommended_action=recommended_action,
        source_event_ids=source_event_ids or [],
    )


def test_attention_yellow_is_append_only_and_nonblocking(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)

    event = raise_attention(memory, run["run_id"])
    board = memory.get_attention_board("default")

    assert event["event_type"] == "attention_raised"
    assert board["counts"] == {"red": 0, "yellow": 1, "green": 0}
    assert board["items"][0]["level"] == "yellow"
    assert memory.get_run_detail(run["run_id"])["status"] == "claimed"
    assert memory.get_assignment_detail("task-1")["assignment"]["status"] == "claimed"


def test_attention_green_supersedes_yellow_for_same_issue(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)
    raise_attention(memory, run["run_id"])
    raise_attention(
        memory,
        run["run_id"],
        client_update_id="attn-2",
        level="green",
        reason_code="risk_resolved",
        why_now="Fallback succeeded",
        recommended_action="None",
    )

    assert memory.get_attention_board("default")["items"] == []
    board = memory.get_attention_board("default", include_green=True)
    assert board["counts"] == {"red": 0, "yellow": 0, "green": 1}
    assert [item["level"] for item in board["items"]] == ["green"]


def test_attention_keeps_different_dedupe_keys_separate(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)
    raise_attention(memory, run["run_id"])
    raise_attention(
        memory,
        run["run_id"],
        client_update_id="attn-2",
        dedupe_key="dependency-delay",
        reason_code="dependency_delayed",
    )

    board = memory.get_attention_board("default")
    assert board["counts"] == {"red": 0, "yellow": 2, "green": 0}
    assert {item["dedupe_key"] for item in board["items"]} == {
        "retry-budget",
        "dependency-delay",
    }


def test_attention_board_filters_team_and_target(tmp_path: Path) -> None:
    memory = CoordinationMemory(tmp_path / "coordination.sqlite3")
    memory.create_team(
        team_id="other",
        workspace_id="default",
        name="Other",
        owner_actor_id="integrator",
    )
    for assignment_id, team_id in (("default-task", "default"), ("other-task", "other")):
        assignment = memory.create_assignment(
            assignment_id=assignment_id,
            title=assignment_id,
            actor_id="integrator",
            actor_role="integrator",
            base_revision=0,
            team_id=team_id,
        )
        claimed = memory.claim_assignment(
            assignment_id=assignment_id,
            actor_id="agent-a",
            actor_role="agent",
            base_revision=assignment["revision"],
        )
        raise_attention(memory, claimed["active_run_id"])
    other_run = memory.get_assignment_detail("other-task")["assignment"]["active_run_id"]
    raise_attention(
        memory,
        other_run,
        client_update_id="attn-integrator",
        target="integrator",
        dedupe_key="integrator-review",
    )

    assert len(memory.get_attention_board("default")["items"]) == 1
    assert len(memory.get_attention_board("other")["items"]) == 1
    assert len(memory.get_attention_board("other", target="integrator")["items"]) == 1


def test_attention_latest_issue_target_replaces_prior_target(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)
    raise_attention(memory, run["run_id"])
    raise_attention(
        memory,
        run["run_id"],
        client_update_id="attn-2",
        target="integrator",
    )

    assert memory.get_attention_board("default")["items"] == []
    assert len(memory.get_attention_board("default", target="integrator")["items"]) == 1


def test_attention_replays_identical_update_and_rejects_conflict(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)
    original = raise_attention(memory, run["run_id"])

    assert raise_attention(memory, run["run_id"]) == original
    with pytest.raises(ValidationError, match="client_update_id"):
        raise_attention(memory, run["run_id"], why_now="Conflicting reason")


def test_attention_projects_open_intervention_as_red_and_response_clears_it(
    tmp_path: Path,
) -> None:
    memory, run = claimed_run(tmp_path)
    decision_packet = {
        "summary": "Choose a safe retry policy",
        "options": ["stop", "retry once"],
    }
    request = memory.request_intervention(
        run_id=run["run_id"],
        actor_id="agent-a",
        actor_role="agent",
        prompt="Should the agent retry?",
        intervention_kind="decision",
        decision_packet=decision_packet,
    )

    board = memory.get_attention_board("default")
    assert board["counts"] == {"red": 1, "yellow": 0, "green": 0}
    assert board["items"][0]["level"] == "red"
    assert board["items"][0]["decision_packet"] == decision_packet
    assert request["payload"]["decision_packet"] == decision_packet

    memory.respond_intervention(
        run_id=run["run_id"],
        actor_id="integrator",
        actor_role="human",
        response="Retry once",
        reviewed_event_id=request["event_id"],
    )
    assert memory.get_attention_board("default")["counts"]["red"] == 0


def test_attention_hides_open_items_for_terminal_assignment(tmp_path: Path) -> None:
    memory, run = claimed_run(tmp_path)
    raise_attention(memory, run["run_id"])
    assignment = memory.get_assignment_detail("task-1")["assignment"]
    memory.cancel_assignment(
        assignment_id="task-1",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=assignment["revision"],
        reason="No longer needed",
    )

    assert memory.get_attention_board("default", include_green=True)["items"] == []
