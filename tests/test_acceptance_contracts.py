from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coordination_memory_mcp.store import (
    AuthorizationError,
    CoordinationMemory,
    StaleRevisionError,
    ValidationError,
)


def open_memory(tmp_path: Path) -> CoordinationMemory:
    return CoordinationMemory(tmp_path / "coordination.sqlite3")


def make_contract(memory: CoordinationMemory, contract_id: str = "c1") -> dict:
    return memory.create_acceptance_contract(
        contract_id=contract_id,
        title="P4 Real Execution",
        goal_statement="Governed multi-tenant execution is real, not demo-shaped.",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )


def test_create_contract_starts_in_drafting(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    assert contract["status"] == "drafting"
    assert contract["revision"] == 1
    assert contract["max_repair_attempts"] == 3
    assert contract["repair_attempt"] == 0


def test_create_contract_requires_integrator(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    with pytest.raises(AuthorizationError):
        memory.create_acceptance_contract(
            contract_id="c1",
            title="x",
            goal_statement="y",
            actor_id="agent-1",
            actor_role="agent",
            base_revision=0,
        )


def test_create_contract_requires_base_revision_zero(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    with pytest.raises(StaleRevisionError):
        memory.create_acceptance_contract(
            contract_id="c1",
            title="x",
            goal_statement="y",
            actor_id="integrator",
            actor_role="integrator",
            base_revision=1,
        )


def test_create_contract_rejects_duplicate(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    make_contract(memory)
    with pytest.raises(ValidationError):
        make_contract(memory)


def add_basic_invariants(memory: CoordinationMemory, contract: dict) -> dict:
    contract = memory.add_invariant(
        contract_id=contract["contract_id"],
        key="tenant-b-isolation",
        description="Second tenant policy isolation holds.",
        probe_kind="sql",
        probe_spec={"ref": "probes/tenant_b.sql"},
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
        is_second_instance=True,
    )
    contract = memory.add_invariant(
        contract_id=contract["contract_id"],
        key="deny-unauthorized",
        description="Unauthorized request is denied.",
        probe_kind="http",
        probe_spec={"ref": "probes/deny.http"},
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
        is_negative=True,
    )
    return contract


def test_add_invariant_appends_and_bumps_revision(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    updated = add_basic_invariants(memory, contract)
    assert updated["revision"] == 3  # 1 create + 2 invariants


def test_add_invariant_rejects_unknown_contract(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    with pytest.raises(ValidationError):
        memory.add_invariant(
            contract_id="missing",
            key="k",
            description="d",
            probe_kind="command",
            probe_spec={"ref": "x"},
            actor_id="integrator",
            actor_role="integrator",
            base_revision=0,
        )


def test_add_invariant_rejects_bad_probe_kind(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    with pytest.raises(ValidationError):
        memory.add_invariant(
            contract_id=contract["contract_id"],
            key="k",
            description="d",
            probe_kind="telepathy",
            probe_spec={"ref": "x"},
            actor_id="integrator",
            actor_role="integrator",
            base_revision=contract["revision"],
        )


def test_raise_deviation_requires_valid_disposition(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    with pytest.raises(ValidationError):
        memory.raise_deviation(
            contract_id=contract["contract_id"],
            title="shortcut",
            description="prompt keyword admission",
            disposition="meh",
            actor_id="agent-1",
            actor_role="agent",
            base_revision=contract["revision"],
        )


def test_raise_blocker_deviation_is_recorded_open(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    updated = memory.raise_deviation(
        contract_id=contract["contract_id"],
        title="demo admission",
        description="DeerFlow entry uses prompt keyword rule",
        disposition="blocker",
        actor_id="agent-1",
        actor_role="agent",
        base_revision=contract["revision"],
    )
    assert updated["revision"] == 2
    devs = memory._deviations(contract["contract_id"])
    assert devs[0]["disposition"] == "blocker"
    assert devs[0]["status"] == "open"


def bind_a_running_assignment(
    memory: CoordinationMemory, contract: dict, actor_id: str = "agent-runner"
) -> dict:
    assignment = memory.create_assignment(
        assignment_id="work-1",
        title="work",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        team_id=contract["team_id"],
    )
    memory.claim_assignment(
        assignment_id="work-1",
        actor_id=actor_id,
        actor_role="agent",
        base_revision=assignment["revision"],
    )
    return memory.bind_assignment_to_contract(
        contract_id=contract["contract_id"],
        assignment_id="work-1",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )


def test_bind_assignment_requires_integrator(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory.create_assignment(
        assignment_id="work-1",
        title="w",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    with pytest.raises(AuthorizationError):
        memory.bind_assignment_to_contract(
            contract_id=contract["contract_id"],
            assignment_id="work-1",
            actor_id="agent-1",
            actor_role="agent",
            base_revision=contract["revision"],
        )


def test_bind_assignment_records_bound_runner(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    updated = bind_a_running_assignment(memory, contract)
    assert updated["revision"] == 2
    assert "agent-runner" in memory._bound_runner_actor_ids(contract["contract_id"])


def sealed_contract(tmp_path_memory, acceptor="acceptor-1"):
    memory, contract = tmp_path_memory
    contract = add_basic_invariants(memory, contract)
    contract = memory.seal_contract(
        contract_id=contract["contract_id"],
        acceptor_actor_id=acceptor,
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    return memory, contract


def test_seal_requires_negative_test(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = memory.add_invariant(
        contract_id=contract["contract_id"],
        key="tenant-b",
        description="d",
        probe_kind="sql",
        probe_spec={"ref": "x"},
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
        is_second_instance=True,
    )
    with pytest.raises(ValidationError, match="negative"):
        memory.seal_contract(
            contract_id=contract["contract_id"],
            acceptor_actor_id="acceptor-1",
            actor_id="integrator",
            actor_role="integrator",
            base_revision=contract["revision"],
        )


def test_seal_requires_second_instance_test(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = memory.add_invariant(
        contract_id=contract["contract_id"],
        key="deny",
        description="d",
        probe_kind="http",
        probe_spec={"ref": "x"},
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
        is_negative=True,
    )
    with pytest.raises(ValidationError, match=r"second.instance"):
        memory.seal_contract(
            contract_id=contract["contract_id"],
            acceptor_actor_id="acceptor-1",
            actor_id="integrator",
            actor_role="integrator",
            base_revision=contract["revision"],
        )


def test_seal_rejects_acceptor_who_ran_bound_assignment(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = add_basic_invariants(memory, contract)
    contract = bind_a_running_assignment(memory, contract, actor_id="agent-runner")
    with pytest.raises(AuthorizationError, match="independent"):
        memory.seal_contract(
            contract_id=contract["contract_id"],
            acceptor_actor_id="agent-runner",
            actor_id="integrator",
            actor_role="integrator",
            base_revision=contract["revision"],
        )


def test_seal_freezes_invariants(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    assert contract["status"] == "criteria_sealed"
    assert contract["acceptor_actor_id"] == "acceptor-1"
    with pytest.raises(ValidationError, match="frozen"):
        memory.add_invariant(
            contract_id=contract["contract_id"],
            key="late",
            description="d",
            probe_kind="command",
            probe_spec={"ref": "x"},
            actor_id="integrator",
            actor_role="integrator",
            base_revision=contract["revision"],
        )


def test_report_verification_requires_sealed_contract(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = add_basic_invariants(memory, contract)
    with pytest.raises(ValidationError, match="sealed"):
        memory.report_verification(
            contract_id=contract["contract_id"],
            invariant_key="deny-unauthorized",
            outcome="passed",
            actor_id="agent-runner",
            actor_role="agent",
        )


def test_report_verification_rejects_unknown_invariant(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    with pytest.raises(ValidationError, match="invariant"):
        memory.report_verification(
            contract_id=contract["contract_id"],
            invariant_key="nope",
            outcome="passed",
            actor_id="agent-runner",
            actor_role="agent",
        )


def test_report_verification_records_outcome(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="deny-unauthorized",
        outcome="failed",
        actor_id="agent-runner",
        actor_role="agent",
        evidence={"ref": "logs/deny.txt"},
    )
    latest = memory._latest_verifications(contract["contract_id"])
    assert latest["deny-unauthorized"] == "failed"


def report_all_green(memory: CoordinationMemory, contract: dict) -> None:
    for key in ("tenant-b-isolation", "deny-unauthorized"):
        memory.report_verification(
            contract_id=contract["contract_id"],
            invariant_key=key,
            outcome="passed",
            actor_id="agent-runner",
            actor_role="agent",
        )


def test_evaluate_all_green_moves_to_awaiting_acceptor(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    report_all_green(memory, contract)
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    assert contract["status"] == "awaiting_acceptor"


def test_evaluate_open_blocker_blocks_awaiting_acceptor(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = add_basic_invariants(memory, contract)
    contract = memory.raise_deviation(
        contract_id=contract["contract_id"],
        title="b",
        description="d",
        disposition="blocker",
        actor_id="agent-1",
        actor_role="agent",
        base_revision=contract["revision"],
    )
    contract = memory.seal_contract(
        contract_id=contract["contract_id"],
        acceptor_actor_id="acceptor-1",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    report_all_green(memory, contract)
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    assert contract["status"] != "awaiting_acceptor"
    assert contract["status"] == "repair_ready"


def test_evaluate_rejected_for_bound_runner(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = add_basic_invariants(memory, contract)
    contract = bind_a_running_assignment(memory, contract, actor_id="agent-runner")
    contract = memory.seal_contract(
        contract_id=contract["contract_id"],
        acceptor_actor_id="acceptor-1",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    report_all_green(memory, contract)
    contract = memory._get_contract(contract["contract_id"])
    with pytest.raises(AuthorizationError, match="independent"):
        memory.evaluate_contract(
            contract_id=contract["contract_id"],
            actor_id="agent-runner",
            actor_role="agent",
            base_revision=contract["revision"],
        )


# ── Task 8: self-healing repair loop ──────────────────────────────────────────


def test_failure_creates_bound_repair_assignment(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="deny-unauthorized",
        outcome="failed",
        actor_id="agent-runner",
        actor_role="agent",
    )
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="tenant-b-isolation",
        outcome="passed",
        actor_id="agent-runner",
        actor_role="agent",
    )
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    assert contract["status"] == "repair_ready"
    assert contract["repair_attempt"] == 1
    board = memory.get_team_board(contract["team_id"])
    repair = [
        a
        for lane in board["lanes"].values()
        for a in lane
        if a["assignment_id"].startswith(contract["contract_id"] + "-repair-")
    ]
    assert len(repair) == 1
    assert repair[0]["metadata"]["failing_invariants"] == ["deny-unauthorized"]
    assert repair[0]["contract_id"] == contract["contract_id"]


def test_repair_then_green_reaches_awaiting_acceptor(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="deny-unauthorized",
        outcome="failed",
        actor_id="agent-runner",
        actor_role="agent",
    )
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="tenant-b-isolation",
        outcome="passed",
        actor_id="agent-runner",
        actor_role="agent",
    )
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    # repair run fixes the deny probe
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="deny-unauthorized",
        outcome="passed",
        actor_id="repair-bot",
        actor_role="agent",
    )
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    assert contract["status"] == "awaiting_acceptor"


# ── Task 9: Loop brakes — max attempts + no-progress → awaiting_human ─────────


def _fail_deny_and_evaluate(memory, contract, reporter="agent-runner"):
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="deny-unauthorized",
        outcome="failed",
        actor_id=reporter,
        actor_role="agent",
    )
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="tenant-b-isolation",
        outcome="passed",
        actor_id=reporter,
        actor_role="agent",
    )
    contract = memory._get_contract(contract["contract_id"])
    return memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )


def test_no_progress_escalates_to_human(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    contract = _fail_deny_and_evaluate(memory, contract)  # attempt 1, repair_ready
    contract = _fail_deny_and_evaluate(memory, contract)  # same failing set -> no progress
    assert contract["status"] == "awaiting_human"


def test_max_attempts_escalates_to_human(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = add_basic_invariants(memory, contract)
    contract = memory.seal_contract(
        contract_id=contract["contract_id"],
        acceptor_actor_id="acceptor-1",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    # max_repair_attempts defaults to 3; drive 3 *shrinking-but-never-clean* rounds.
    # Round 1: both fail. Round 2: only deny fails (progress). Round 3: only deny fails (no progress) -> human.
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="deny-unauthorized",
        outcome="failed",
        actor_id="agent-runner",
        actor_role="agent",
    )
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="tenant-b-isolation",
        outcome="failed",
        actor_id="agent-runner",
        actor_role="agent",
    )
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )  # attempt 1, failing={deny,tenant}
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="tenant-b-isolation",
        outcome="passed",
        actor_id="repair-bot",
        actor_role="agent",
    )
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )  # attempt 2, failing={deny} (shrunk)
    assert contract["status"] == "repair_ready"
    assert contract["repair_attempt"] == 2


# ── Task 10: accept_contract / reject_contract (Gate 3 — independent sign-off) ─


def green_awaiting_acceptor(tmp_path: Path):
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    report_all_green(memory, contract)
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    return memory, contract


def test_accept_only_by_bound_acceptor(tmp_path: Path) -> None:
    memory, contract = green_awaiting_acceptor(tmp_path)
    with pytest.raises(AuthorizationError):
        memory.accept_contract(
            contract_id=contract["contract_id"],
            actor_id="someone-else",
            actor_role="human",
            base_revision=contract["revision"],
            decision_note="nope",
        )


def test_accept_rejected_for_bound_runner(tmp_path: Path) -> None:
    # Even if the runner were named acceptor, independence is re-checked.
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = add_basic_invariants(memory, contract)
    contract = bind_a_running_assignment(memory, contract, actor_id="agent-runner")
    contract = memory.seal_contract(
        contract_id=contract["contract_id"],
        acceptor_actor_id="acceptor-1",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    report_all_green(memory, contract)
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    with pytest.raises(AuthorizationError, match="independent"):
        memory.accept_contract(
            contract_id=contract["contract_id"],
            actor_id="agent-runner",
            actor_role="agent",
            base_revision=contract["revision"],
            decision_note="self",
        )


def test_accept_moves_to_accepted(tmp_path: Path) -> None:
    memory, contract = green_awaiting_acceptor(tmp_path)
    contract = memory.accept_contract(
        contract_id=contract["contract_id"],
        actor_id="acceptor-1",
        actor_role="human",
        base_revision=contract["revision"],
        decision_note="invariant set adequately covers the goal",
    )
    assert contract["status"] == "accepted"
    assert contract["decided_at"] is not None


def test_accept_requires_awaiting_acceptor_state(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))  # still criteria_sealed
    with pytest.raises(ValidationError):
        memory.accept_contract(
            contract_id=contract["contract_id"],
            actor_id="acceptor-1",
            actor_role="human",
            base_revision=contract["revision"],
            decision_note="too early",
        )


def test_reject_criteria_inadequate_goes_to_awaiting_human(tmp_path: Path) -> None:
    memory, contract = green_awaiting_acceptor(tmp_path)
    contract = memory.reject_contract(
        contract_id=contract["contract_id"],
        actor_id="acceptor-1",
        actor_role="human",
        base_revision=contract["revision"],
        decision_note="invariants miss the rollback case",
    )
    assert contract["status"] == "awaiting_human"


# ── Task 11: waive_deviation (acceptor-only blocker waiver) ───────────────────


def blocked_green_contract(tmp_path: Path):
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = add_basic_invariants(memory, contract)
    contract = memory.raise_deviation(
        contract_id=contract["contract_id"],
        title="demo admission",
        description="prompt keyword rule",
        disposition="blocker",
        actor_id="agent-1",
        actor_role="agent",
        base_revision=contract["revision"],
    )
    dev_id = memory._deviations(contract["contract_id"])[0]["deviation_id"]
    contract = memory.seal_contract(
        contract_id=contract["contract_id"],
        acceptor_actor_id="acceptor-1",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    report_all_green(memory, contract)
    return memory, memory._get_contract(contract["contract_id"]), dev_id


def test_waive_requires_acceptor(tmp_path: Path) -> None:
    memory, contract, dev_id = blocked_green_contract(tmp_path)
    with pytest.raises(AuthorizationError):
        memory.waive_deviation(
            contract_id=contract["contract_id"],
            deviation_id=dev_id,
            actor_id="integrator",
            actor_role="integrator",
            base_revision=contract["revision"],
            reason="not your call",
        )


def test_waive_unblocks_path_to_accepted(tmp_path: Path) -> None:
    memory, contract, dev_id = blocked_green_contract(tmp_path)
    contract = memory.waive_deviation(
        contract_id=contract["contract_id"],
        deviation_id=dev_id,
        actor_id="acceptor-1",
        actor_role="human",
        base_revision=contract["revision"],
        reason="acceptable this phase, tracked",
    )
    assert memory._deviations(contract["contract_id"])[0]["status"] == "waived"
    assert not memory._has_open_blocker(contract["contract_id"])
    contract = memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    assert contract["status"] == "awaiting_acceptor"


# ── Task 12: reopen_contract (loud goalpost change) ───────────────────────────


def test_reopen_returns_to_drafting_and_unbinds_acceptor(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    contract = memory.reopen_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
        reason="criteria inadequate; adding rollback invariant",
    )
    assert contract["status"] == "drafting"
    assert contract["acceptor_actor_id"] is None
    assert contract["sealed_at"] is None
    # invariants are editable again
    contract = memory.add_invariant(
        contract_id=contract["contract_id"],
        key="rollback",
        description="d",
        probe_kind="command",
        probe_spec={"ref": "x"},
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    assert contract["status"] == "drafting"


def test_reopen_invalidates_prior_verifications(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    report_all_green(memory, contract)
    contract = memory._get_contract(contract["contract_id"])
    contract = memory.reopen_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
        reason="reset",
    )
    assert memory._latest_verifications(contract["contract_id"]) == {}


def test_reopen_requires_integrator(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    memory, contract = sealed_contract((memory, contract))
    with pytest.raises(AuthorizationError):
        memory.reopen_contract(
            contract_id=contract["contract_id"],
            actor_id="agent-1",
            actor_role="agent",
            base_revision=contract["revision"],
            reason="x",
        )


# ── Task 13: Projection — accepted_contracts + open_governance ────────────────


def test_snapshot_excludes_unaccepted_goal(tmp_path: Path) -> None:
    memory, contract = green_awaiting_acceptor(tmp_path)
    snap = memory.get_snapshot()
    assert contract["contract_id"] not in snap["accepted_contracts"]
    assert contract["contract_id"] in snap["open_governance"]
    assert snap["open_governance"][contract["contract_id"]]["status"] == "awaiting_acceptor"


def test_snapshot_includes_accepted_goal(tmp_path: Path) -> None:
    memory, contract = green_awaiting_acceptor(tmp_path)
    contract = memory.accept_contract(
        contract_id=contract["contract_id"],
        actor_id="acceptor-1",
        actor_role="human",
        base_revision=contract["revision"],
        decision_note="adequate",
    )
    snap = memory.get_snapshot()
    assert contract["contract_id"] in snap["accepted_contracts"]
    entry = snap["accepted_contracts"][contract["contract_id"]]
    assert entry["acceptor_actor_id"] == "acceptor-1"
    assert sorted(entry["invariants"]) == ["deny-unauthorized", "tenant-b-isolation"]
    assert contract["contract_id"] not in snap["open_governance"]


# ── Task 14: Read models — get_contract_detail / list_contracts ───────────────


def test_get_contract_detail_returns_full_object(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = add_basic_invariants(memory, contract)
    detail = memory.get_contract_detail(contract["contract_id"])
    assert detail["contract"]["contract_id"] == contract["contract_id"]
    assert {i["key"] for i in detail["invariants"]} == {"tenant-b-isolation", "deny-unauthorized"}
    assert detail["deviations"] == []
    assert detail["verifications"] == []


def test_list_contracts_filters_by_team(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    make_contract(memory, contract_id="c1")
    listed = memory.list_contracts(team_id="default")
    assert [c["contract_id"] for c in listed] == ["c1"]
    assert memory.list_contracts(team_id="other") == []


# ── Task 15: MCP tool wrappers in server.py ───────────────────────────────────


def test_server_registers_contract_tools() -> None:
    import inspect

    from coordination_memory_mcp import server as server_mod

    src = inspect.getsource(server_mod.main)
    for tool in [
        "create_acceptance_contract",
        "add_invariant",
        "raise_deviation",
        "bind_assignment_to_contract",
        "seal_contract",
        "report_verification",
        "evaluate_contract",
        "accept_contract",
        "reject_contract",
        "waive_deviation",
        "reopen_contract",
        "get_contract_detail",
        "list_contracts",
    ]:
        assert f"def {tool}(" in src, f"missing MCP tool: {tool}"


def test_contract_detail_includes_bound_assignments_and_events(tmp_path: Path) -> None:
    memory = open_memory(tmp_path)
    contract = make_contract(memory)
    contract = add_basic_invariants(memory, contract)
    contract = bind_a_running_assignment(memory, contract, actor_id="agent-runner")
    contract = memory.seal_contract(
        contract_id=contract["contract_id"],
        acceptor_actor_id="acceptor-1",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )
    # one failed probe -> evaluate dispatches a repair assignment + events
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="deny-unauthorized",
        outcome="failed",
        actor_id="agent-runner",
        actor_role="agent",
    )
    memory.report_verification(
        contract_id=contract["contract_id"],
        invariant_key="tenant-b-isolation",
        outcome="passed",
        actor_id="agent-runner",
        actor_role="agent",
    )
    contract = memory._get_contract(contract["contract_id"])
    memory.evaluate_contract(
        contract_id=contract["contract_id"],
        actor_id="integrator",
        actor_role="integrator",
        base_revision=contract["revision"],
    )

    detail = memory.get_contract_detail(contract["contract_id"])

    bound_ids = {a["assignment_id"] for a in detail["bound_assignments"]}
    assert "work-1" in bound_ids
    assert any(a.endswith("-repair-1") for a in bound_ids)
    types = [e["event_type"] for e in detail["events"]]
    assert "contract_sealed" in types
    assert "repair_dispatched" in types
    # every event belongs to this contract
    assert all(e["payload"].get("contract_id") == contract["contract_id"] for e in detail["events"])
