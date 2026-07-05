from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from coordination_memory_mcp.store import CoordinationMemory

DEFAULT_DB_PATH = ".coordination-memory/coordination.sqlite3"


def memory_from_env() -> CoordinationMemory:
    return CoordinationMemory(os.environ.get("COORDINATION_MEMORY_DB", DEFAULT_DB_PATH))


def main() -> None:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("P2 Coordination Memory", json_response=True)
    memory = memory_from_env()

    @mcp.tool()
    def register_actor(
        actor_id: str,
        actor_kind: str,
        display_name: str,
        provider: str | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register or refresh a local coordination actor profile."""

        return memory.register_actor(
            actor_id=actor_id,
            actor_kind=actor_kind,
            display_name=display_name,
            provider=provider,
            capabilities=capabilities,
        )

    @mcp.tool()
    def create_team(
        team_id: str,
        workspace_id: str,
        name: str,
        owner_actor_id: str,
        phase_key: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or refresh a local coordination team."""

        return memory.create_team(
            team_id=team_id,
            workspace_id=workspace_id,
            name=name,
            owner_actor_id=owner_actor_id,
            phase_key=phase_key,
            settings=settings,
        )

    @mcp.tool()
    def register_workspace(
        workspace_id: str,
        name: str | None = None,
        repo_root: str | None = None,
        default_branch: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or refresh a workspace record (idempotent upsert)."""

        return memory.register_workspace(
            workspace_id=workspace_id,
            name=name,
            repo_root=repo_root,
            default_branch=default_branch,
            metadata=metadata,
        )

    @mcp.tool()
    def list_workspaces() -> list[dict[str, Any]]:
        """List workspaces with assignment status counts."""

        return memory.list_workspaces()

    @mcp.tool()
    def get_workspace_detail(workspace_id: str) -> dict[str, Any]:
        """Return one workspace with its teams, assignments, and status counts."""

        return memory.get_workspace_detail(workspace_id)

    @mcp.tool()
    def archive_workspace(workspace_id: str, actor_role: str) -> dict[str, Any]:
        """Archive a workspace. Integrator-only; this is a soft status change."""

        return memory.archive_workspace(workspace_id=workspace_id, actor_role=actor_role)

    @mcp.tool()
    def create_assignment(
        assignment_id: str,
        title: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        workspace_id: str = "default",
        team_id: str = "default",
        allowed_paths: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an assignment. Integrator-only; starts with base_revision=0."""

        return memory.create_assignment(
            assignment_id=assignment_id,
            title=title,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            workspace_id=workspace_id,
            team_id=team_id,
            allowed_paths=allowed_paths,
            acceptance_criteria=acceptance_criteria,
            metadata=metadata,
        )

    @mcp.tool()
    def claim_assignment(
        assignment_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        lease_ttl_seconds: int = 3600,
        session_kind: str | None = None,
        session_ref: str | None = None,
        interactive_url: str | None = None,
        worktree_path: str | None = None,
        branch: str | None = None,
        base_commit: str | None = None,
        resume_of_run_id: str | None = None,
    ) -> dict[str, Any]:
        """Claim an assignment lease with optimistic concurrency."""

        return memory.claim_assignment(
            assignment_id=assignment_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            lease_ttl_seconds=lease_ttl_seconds,
            session_kind=session_kind,
            session_ref=session_ref,
            interactive_url=interactive_url,
            worktree_path=worktree_path,
            branch=branch,
            base_commit=base_commit,
            resume_of_run_id=resume_of_run_id,
        )

    @mcp.tool()
    def append_event(
        assignment_id: str,
        event_type: str,
        status: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Append a structured coordination event without mutating history."""

        return memory.append_event(
            assignment_id=assignment_id,
            event_type=event_type,
            status=status,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            payload=payload,
        )

    @mcp.tool()
    def submit_handoff(
        assignment_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit a reviewable handoff event; completion is not acceptance."""

        return memory.submit_handoff(
            assignment_id=assignment_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            payload=payload,
        )

    @mcp.tool()
    def heartbeat_run(
        run_id: str,
        actor_id: str,
        actor_role: str,
        summary: str,
    ) -> dict[str, Any]:
        """Record run liveness and keep the assignment in a running lane."""

        return memory.heartbeat_run(
            run_id=run_id,
            actor_id=actor_id,
            actor_role=actor_role,
            summary=summary,
        )

    @mcp.tool()
    def record_run_binding(
        run_id: str,
        actor_id: str,
        actor_role: str,
        binding_patch: dict[str, Any],
        event_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update active run communication metadata and append an observed event."""

        return memory.record_run_binding(
            run_id=run_id,
            actor_id=actor_id,
            actor_role=actor_role,
            binding_patch=binding_patch,
            event_payload=event_payload,
        )

    @mcp.tool()
    def request_intervention(
        run_id: str,
        actor_id: str,
        actor_role: str,
        prompt: str,
        intervention_kind: str,
    ) -> dict[str, Any]:
        """Move an active run into a local awaiting-human lane."""

        return memory.request_intervention(
            run_id=run_id,
            actor_id=actor_id,
            actor_role=actor_role,
            prompt=prompt,
            intervention_kind=intervention_kind,
        )

    @mcp.tool()
    def respond_intervention(
        run_id: str,
        actor_id: str,
        actor_role: str,
        response: str,
        reviewed_event_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a human response and return the run to local execution."""

        return memory.respond_intervention(
            run_id=run_id,
            actor_id=actor_id,
            actor_role=actor_role,
            response=response,
            reviewed_event_id=reviewed_event_id,
        )

    @mcp.tool()
    def list_pending_reviews() -> list[dict[str, Any]]:
        """List reviewable events that do not yet have an Integrator decision."""

        return memory.list_pending_reviews()

    @mcp.tool()
    def review_event(
        event_id: str,
        decision_status: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        """Append an Integrator review decision for a submitted event."""

        return memory.review_event(
            event_id=event_id,
            decision_status=decision_status,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            decision_note=decision_note,
        )

    @mcp.tool()
    def accept_event(
        event_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        """Integrator-only accept decision."""

        return memory.accept_event(
            event_id=event_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            decision_note=decision_note,
        )

    @mcp.tool()
    def reject_event(
        event_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        """Integrator-only reject decision."""

        return memory.reject_event(
            event_id=event_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            decision_note=decision_note,
        )

    @mcp.tool()
    def cancel_assignment(
        assignment_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        """Integrator-only: void an assignment (mistake/scope dropped). Releases any lease."""

        return memory.cancel_assignment(
            assignment_id=assignment_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            reason=reason,
        )

    @mcp.tool()
    def supersede_assignment(
        assignment_id: str,
        superseded_by: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        """Integrator-only: retire an assignment replaced by another (``superseded_by``)."""

        return memory.supersede_assignment(
            assignment_id=assignment_id,
            superseded_by=superseded_by,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            reason=reason,
        )

    @mcp.tool()
    def get_snapshot() -> dict[str, Any]:
        """Return the derived accepted-state snapshot."""

        return memory.get_snapshot()

    @mcp.tool()
    def get_team_board(team_id: str = "default") -> dict[str, Any]:
        """Return a team's assignment lanes from the local store."""

        return memory.get_team_board(team_id)

    @mcp.tool()
    def get_assignment_detail(assignment_id: str) -> dict[str, Any]:
        """Return an assignment with its run and event timeline."""

        return memory.get_assignment_detail(assignment_id)

    @mcp.tool()
    def get_run_detail(run_id: str) -> dict[str, Any]:
        """Return one run with its event timeline."""

        return memory.get_run_detail(run_id)

    @mcp.tool()
    def export_git_projection(output_dir: str, actor_role: str) -> dict[str, str]:
        """Integrator-only export to a Git-compatible projection directory."""

        return memory.export_git_projection(
            output_dir=Path(output_dir),
            actor_role=actor_role,
        )

    @mcp.tool()
    def create_acceptance_contract(
        contract_id: str,
        title: str,
        goal_statement: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        workspace_id: str = "default",
        team_id: str = "default",
        max_repair_attempts: int = 3,
        author_actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Open a goal-level acceptance contract (Integrator-only, base_revision=0)."""
        return memory.create_acceptance_contract(
            contract_id=contract_id,
            title=title,
            goal_statement=goal_statement,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            workspace_id=workspace_id,
            team_id=team_id,
            max_repair_attempts=max_repair_attempts,
            author_actor_id=author_actor_id,
            metadata=metadata,
        )

    @mcp.tool()
    def add_invariant(
        contract_id: str,
        key: str,
        description: str,
        probe_kind: str,
        probe_spec: dict[str, Any],
        actor_id: str,
        actor_role: str,
        base_revision: int,
        required: bool = True,
        is_negative: bool = False,
        is_second_instance: bool = False,
    ) -> dict[str, Any]:
        """Add a machine-checkable invariant (drafting only; frozen after seal)."""
        return memory.add_invariant(
            contract_id=contract_id,
            key=key,
            description=description,
            probe_kind=probe_kind,
            probe_spec=probe_spec,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            required=required,
            is_negative=is_negative,
            is_second_instance=is_second_instance,
        )

    @mcp.tool()
    def raise_deviation(
        contract_id: str,
        title: str,
        description: str,
        disposition: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
    ) -> dict[str, Any]:
        """Register a shortcut/deviation with a forced disposition."""
        return memory.raise_deviation(
            contract_id=contract_id,
            title=title,
            description=description,
            disposition=disposition,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
        )

    @mcp.tool()
    def bind_assignment_to_contract(
        contract_id: str,
        assignment_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
    ) -> dict[str, Any]:
        """Bind a work assignment to a contract for independence tracking."""
        return memory.bind_assignment_to_contract(
            contract_id=contract_id,
            assignment_id=assignment_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
        )

    @mcp.tool()
    def seal_contract(
        contract_id: str,
        acceptor_actor_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
    ) -> dict[str, Any]:
        """Seal invariants and bind the independent acceptor (deny+second-instance required)."""
        return memory.seal_contract(
            contract_id=contract_id,
            acceptor_actor_id=acceptor_actor_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
        )

    @mcp.tool()
    def report_verification(
        contract_id: str,
        invariant_key: str,
        outcome: str,
        actor_id: str,
        actor_role: str,
        evidence: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Report a probe outcome for an invariant (append-only; post-seal only)."""
        return memory.report_verification(
            contract_id=contract_id,
            invariant_key=invariant_key,
            outcome=outcome,
            actor_id=actor_id,
            actor_role=actor_role,
            evidence=evidence,
            run_id=run_id,
        )

    @mcp.tool()
    def evaluate_contract(
        contract_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
    ) -> dict[str, Any]:
        """Run the objective gate; green advances to awaiting_acceptor, else dispatches repair."""
        return memory.evaluate_contract(
            contract_id=contract_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
        )

    @mcp.tool()
    def accept_contract(
        contract_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        """Bound acceptor signs off that invariants adequately cover the goal."""
        return memory.accept_contract(
            contract_id=contract_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            decision_note=decision_note,
        )

    @mcp.tool()
    def reject_contract(
        contract_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        """Bound acceptor rejects the contract (criteria inadequate); moves to awaiting_human."""
        return memory.reject_contract(
            contract_id=contract_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            decision_note=decision_note,
        )

    @mcp.tool()
    def waive_deviation(
        contract_id: str,
        deviation_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        """Acceptor-only: formally downgrade a blocker deviation to acceptable_this_phase."""
        return memory.waive_deviation(
            contract_id=contract_id,
            deviation_id=deviation_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            reason=reason,
        )

    @mcp.tool()
    def reopen_contract(
        contract_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        """Integrator-only loud reset to drafting; unbinds acceptor, clears verifications."""
        return memory.reopen_contract(
            contract_id=contract_id,
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            reason=reason,
        )

    @mcp.tool()
    def get_contract_detail(contract_id: str) -> dict[str, Any]:
        """Return a contract with its invariants, deviations, and verification history."""
        return memory.get_contract_detail(contract_id=contract_id)

    @mcp.tool()
    def list_contracts(
        workspace_id: str | None = None,
        team_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List acceptance contracts, optionally filtered by workspace or team."""
        return memory.list_contracts(
            workspace_id=workspace_id,
            team_id=team_id,
        )

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
