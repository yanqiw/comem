from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from coordination_memory_mcp.human_attention import (
    DEFAULT_FRESHNESS_WINDOW_MINUTES,
    DEFAULT_YELLOW_DIGEST_MINUTES,
    TERMINAL_ASSIGNMENT_STATUSES,
    brief_freshness,
    normalize_attention_item,
    normalize_human_brief,
)

ASSIGNMENT_STATUSES = {
    "proposed",
    "ready",
    "claimed",
    "running",
    "awaiting_human",
    "awaiting_approval",
    "awaiting_review",
    "needs_fix",
    "blocked",
    "accepted",
    "rejected",
    "cancelled",
    "superseded",
}
RUN_STATUSES = {
    "claimed",
    "running",
    "awaiting_human",
    "awaiting_approval",
    "stalled",
    "completed_gate_passed",
    "completed_gate_failed",
    "failed",
    "cancelled",
    "superseded",
}
TERMINAL_RUN_STATUSES = {
    "completed_gate_passed",
    "completed_gate_failed",
    "failed",
    "cancelled",
    "superseded",
}
EVENT_STATUSES = {
    "proposed",
    "observed",
    "completed_gate_passed",
    "completed_gate_failed",
    "integrator_accepted",
    "integrator_rejected",
    "needs_fix",
}
REVIEWABLE_EVENT_STATUSES = {
    "proposed",
    "observed",
    "completed_gate_passed",
    "completed_gate_failed",
}
DECISION_STATUSES = {
    "integrator_accepted",
    "integrator_rejected",
    "needs_fix",
}
REVIEWABLE_EVENT_TYPES = {
    "contract_declared",
    "contract_proposal",
    "artifact_declared",
    "evidence_report",
    "gate_result",
    "handoff_submitted",
}
UNASSIGNED_WORKSPACE_ID = "__unassigned__"

PROBE_KINDS = {"command", "http", "sql", "file_assert", "artifact_present"}
DEVIATION_DISPOSITIONS = {"acceptable_forever", "acceptable_this_phase", "blocker"}
VERIFICATION_OUTCOMES = {"passed", "failed", "error"}
CONTRACT_STATUSES = {
    "drafting",
    "criteria_sealed",
    "verifying",
    "repair_ready",
    "awaiting_acceptor",
    "accepted",
    "awaiting_human",
    "rejected",
    "cancelled",
}
CONTRACT_MUTABLE_STATUSES = {"drafting"}


class CoordinationMemoryError(Exception):
    """Base error for coordination memory contract failures."""


class StaleRevisionError(CoordinationMemoryError):
    """Raised when base_revision does not match the latest assignment revision."""


class LeaseConflictError(CoordinationMemoryError):
    """Raised when another actor holds an unexpired assignment lease."""


class AuthorizationError(CoordinationMemoryError):
    """Raised when an actor role crosses an explicit permission boundary."""


class ValidationError(CoordinationMemoryError):
    """Raised when a request violates the structured coordination schema."""


class CoordinationMemory:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._readonly = False
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def open_readonly(cls, db_path: str | Path) -> CoordinationMemory:
        memory = cls.__new__(cls)
        memory.db_path = Path(db_path)
        memory._readonly = True
        return memory

    def register_actor(
        self,
        *,
        actor_id: str,
        actor_kind: str,
        display_name: str,
        provider: str | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into actors (
                    actor_id, actor_kind, display_name, provider, status,
                    capabilities_json, last_seen_at, created_at, updated_at
                )
                values (?, ?, ?, ?, 'active', ?, ?, ?, ?)
                on conflict(actor_id) do update set
                    actor_kind = excluded.actor_kind,
                    display_name = excluded.display_name,
                    provider = excluded.provider,
                    status = 'active',
                    capabilities_json = excluded.capabilities_json,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (
                    actor_id,
                    actor_kind,
                    display_name,
                    provider or "local",
                    self._json(capabilities or {}),
                    now,
                    now,
                    now,
                ),
            )
        return self._get_actor(actor_id)

    def create_team(
        self,
        *,
        team_id: str,
        workspace_id: str,
        name: str,
        owner_actor_id: str,
        phase_key: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        with self._connect() as conn:
            self._ensure_workspace_record(conn, workspace_id)
            conn.execute(
                """
                insert into teams (
                    team_id, workspace_id, name, phase_key, owner_actor_id,
                    status, settings_json, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                on conflict(team_id) do update set
                    workspace_id = excluded.workspace_id,
                    name = excluded.name,
                    phase_key = excluded.phase_key,
                    owner_actor_id = excluded.owner_actor_id,
                    status = 'active',
                    settings_json = excluded.settings_json,
                    updated_at = excluded.updated_at
                """,
                (
                    team_id,
                    workspace_id,
                    name,
                    phase_key,
                    owner_actor_id,
                    self._json(settings or {}),
                    now,
                    now,
                ),
            )
        return self._get_team(team_id)

    def register_workspace(
        self,
        *,
        workspace_id: str,
        name: str | None = None,
        repo_root: str | None = None,
        default_branch: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into workspaces (
                    workspace_id, name, repo_root, default_branch, status,
                    metadata_json, created_at, updated_at
                )
                values (?, ?, ?, ?, 'active', ?, ?, ?)
                on conflict(workspace_id) do update set
                    name = excluded.name,
                    repo_root = excluded.repo_root,
                    default_branch = excluded.default_branch,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    workspace_id,
                    name or workspace_id,
                    repo_root,
                    default_branch,
                    self._json(metadata or {}),
                    now,
                    now,
                ),
            )
        return self._get_workspace(workspace_id)

    def list_workspaces(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            workspace_rows = conn.execute(
                """
                select *
                from workspaces
                order by workspace_id
                """
            ).fetchall()
            team_rows = conn.execute(
                """
                select *
                from teams
                order by workspace_id, team_id
                """
            ).fetchall()
            assignment_rows = conn.execute(
                """
                select workspace_id, status, count(*) as status_count
                from assignments
                group by workspace_id, status
                """
            ).fetchall()
            team_assignment_rows = conn.execute(
                """
                select workspace_id, team_id, status, count(*) as status_count
                from assignments
                group by workspace_id, team_id, status
                """
            ).fetchall()

        workspaces_by_id = {}
        for row in workspace_rows:
            workspace = self._workspace_from_row(row)
            workspace_id = self._display_workspace_id(workspace["workspace_id"])
            workspace["workspace_id"] = workspace_id
            if workspace_id == UNASSIGNED_WORKSPACE_ID:
                workspace["name"] = "Unassigned teams"
                workspace["metadata"] = {"virtual": True}
            workspaces_by_id[workspace_id] = workspace
        assignment_counts: dict[str, dict[str, int]] = {}
        for row in assignment_rows:
            workspace_id = self._display_workspace_id(row["workspace_id"])
            assignment_counts.setdefault(workspace_id, {})[row["status"]] = row["status_count"]
            if workspace_id not in workspaces_by_id:
                workspaces_by_id[workspace_id] = self._inferred_workspace(workspace_id)

        team_assignment_counts: dict[tuple[str, str], dict[str, int]] = {}
        for row in team_assignment_rows:
            workspace_id = self._display_workspace_id(row["workspace_id"])
            key = (workspace_id, row["team_id"])
            team_assignment_counts.setdefault(key, {})[row["status"]] = row["status_count"]
            if workspace_id not in workspaces_by_id:
                workspaces_by_id[workspace_id] = self._inferred_workspace(workspace_id)

        teams_by_workspace: dict[str, list[dict[str, Any]]] = {}
        seen_team_keys: set[tuple[str, str]] = set()
        for row in team_rows:
            workspace_id = self._display_workspace_id(row["workspace_id"])
            if workspace_id not in workspaces_by_id:
                workspaces_by_id[workspace_id] = self._inferred_workspace(
                    workspace_id,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            team = self._team_from_row(row)
            team["workspace_id"] = workspace_id
            key = (workspace_id, team["team_id"])
            seen_team_keys.add(key)
            teams_by_workspace.setdefault(workspace_id, []).append(
                self._team_with_assignment_counts(
                    team,
                    team_assignment_counts.get(key, {}),
                )
            )

        for (workspace_id, team_id), counts in team_assignment_counts.items():
            if (workspace_id, team_id) in seen_team_keys:
                continue
            teams_by_workspace.setdefault(workspace_id, []).append(
                self._team_with_assignment_counts(
                    self._inferred_team(workspace_id, team_id),
                    counts,
                )
            )

        workspaces = []
        for workspace_id in sorted(workspaces_by_id):
            workspace = workspaces_by_id[workspace_id]
            counts = assignment_counts.get(workspace["workspace_id"], {})
            teams = teams_by_workspace.get(workspace["workspace_id"], [])
            workspace["team_count"] = len(teams)
            workspace["teams"] = teams
            workspace["assignment_counts"] = counts
            workspace["assignment_total"] = sum(counts.values())
            workspaces.append(workspace)
        return workspaces

    def get_workspace_detail(self, workspace_id: str) -> dict[str, Any]:
        workspace_id = self._display_workspace_id(workspace_id)
        storage_workspace_id = self._storage_workspace_id(workspace_id)
        with self._connect() as conn:
            workspace_row = conn.execute(
                "select * from workspaces where workspace_id = ?",
                (storage_workspace_id,),
            ).fetchone()
            team_rows = conn.execute(
                """
                select *
                from teams
                where workspace_id = ?
                order by team_id
                """,
                (storage_workspace_id,),
            ).fetchall()
            assignment_rows = conn.execute(
                """
                select *
                from assignments
                where workspace_id = ?
                order by priority desc, created_at, assignment_id
                """,
                (storage_workspace_id,),
            ).fetchall()

        assignments = []
        for row in assignment_rows:
            assignment = self._assignment_from_row(row)
            assignment["workspace_id"] = workspace_id
            assignments.append(assignment)
        assignment_counts: dict[str, int] = {}
        team_assignment_counts: dict[str, dict[str, int]] = {}
        for assignment in assignments:
            status = assignment["status"]
            assignment_counts[status] = assignment_counts.get(status, 0) + 1
            team_id = assignment["team_id"]
            team_assignment_counts.setdefault(team_id, {})[status] = (
                team_assignment_counts.setdefault(team_id, {}).get(status, 0) + 1
            )
        if workspace_row is None and not team_rows and not assignments:
            raise ValidationError(f"workspace not found: {workspace_id}")

        teams = []
        seen_team_ids = set()
        for row in team_rows:
            team = self._team_from_row(row)
            team["workspace_id"] = workspace_id
            seen_team_ids.add(team["team_id"])
            teams.append(
                self._team_with_assignment_counts(
                    team,
                    team_assignment_counts.get(team["team_id"], {}),
                )
            )
        for team_id, counts in sorted(team_assignment_counts.items()):
            if team_id in seen_team_ids:
                continue
            teams.append(
                self._team_with_assignment_counts(
                    self._inferred_team(workspace_id, team_id),
                    counts,
                )
            )
        workspace = (
            self._workspace_from_row(workspace_row)
            if workspace_row is not None
            else self._inferred_workspace(
                workspace_id,
                created_at=team_rows[0]["created_at"] if team_rows else None,
                updated_at=team_rows[0]["updated_at"] if team_rows else None,
            )
        )
        workspace["workspace_id"] = workspace_id
        if workspace_id == UNASSIGNED_WORKSPACE_ID:
            workspace["name"] = "Unassigned teams"
            workspace["metadata"] = {"virtual": True}
        return {
            "workspace": workspace,
            "teams": teams,
            "assignments": assignments,
            "assignment_counts": assignment_counts,
            "assignment_total": len(assignments),
        }

    def archive_workspace(self, *, workspace_id: str, actor_role: str) -> dict[str, Any]:
        self._require_integrator(actor_role)
        now = self._now()
        with self._connect() as conn:
            row = conn.execute(
                "select * from workspaces where workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            if row is None:
                raise ValidationError(f"workspace not found: {workspace_id}")
            conn.execute(
                """
                update workspaces
                set status = 'archived',
                    updated_at = ?
                where workspace_id = ?
                """,
                (now, workspace_id),
            )
        return self._get_workspace(workspace_id)

    def create_assignment(
        self,
        *,
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
        self._require_integrator(actor_role)
        if base_revision != 0:
            raise StaleRevisionError("new assignments must use base_revision=0")
        now = self._now()
        normalized_metadata = self._normalize_assignment_metadata(metadata)
        metadata_json = self._json(normalized_metadata)
        with self._connect() as conn:
            exists = conn.execute(
                "select 1 from assignments where assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if exists:
                raise ValidationError(f"assignment already exists: {assignment_id}")
            self._ensure_actor_record(conn, actor_id, actor_role)
            self._ensure_workspace_record(conn, workspace_id)
            conn.execute(
                """
                insert into assignments (
                    assignment_id, workspace_id, team_id, title, status, priority,
                    created_by_actor_id, active_run_id, revision, allowed_paths_json,
                    acceptance_criteria_json, metadata_json, created_at, updated_at,
                    completed_at, claimed_by, lease_expires_at
                )
                values (
                    ?, ?, ?, ?, 'ready', 0, ?, null, 1,
                    ?, ?, ?, ?, ?, null, null, null
                )
                """,
                (
                    assignment_id,
                    workspace_id,
                    team_id,
                    title,
                    actor_id,
                    self._json(allowed_paths or []),
                    self._json(acceptance_criteria or []),
                    metadata_json,
                    now,
                    now,
                ),
            )
            self._insert_event(
                conn,
                assignment_id=assignment_id,
                event_type="assignment_created",
                status="proposed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={
                    "title": title,
                    "metadata": normalized_metadata,
                },
                reviewed_event_id=None,
                assignment_revision=1,
                created_at=now,
            )
        return self._get_assignment(assignment_id)

    def claim_assignment(
        self,
        *,
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
        self._require_known_role(actor_role)
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease_expires_at = (now_dt + timedelta(seconds=lease_ttl_seconds)).isoformat()
        with self._connect() as conn:
            assignment = self._require_current_assignment(conn, assignment_id, base_revision)
            if assignment["status"] in {"accepted", "rejected", "cancelled", "blocked"}:
                raise ValidationError(
                    f"assignment cannot be claimed: {assignment_id} is {assignment['status']}"
                )
            self._require_claim_available(assignment, actor_id)
            next_revision = assignment["revision"] + 1
            self._ensure_actor_record(conn, actor_id, actor_role)
            active_run_id = assignment["active_run_id"]
            active_run = None
            if active_run_id is not None:
                active_run_row = conn.execute(
                    "select * from runs where run_id = ?",
                    (active_run_id,),
                ).fetchone()
                if active_run_row is not None:
                    active_run = self._run_from_row(active_run_row)
            active_run_is_terminal = active_run is not None and (
                active_run["status"] in TERMINAL_RUN_STATUSES or active_run["ended_at"] is not None
            )
            is_live_same_actor_renewal = (
                assignment["claimed_by"] == actor_id
                and active_run_id is not None
                and active_run is not None
                and not active_run_is_terminal
                and assignment["lease_expires_at"] is not None
                and self._parse_timestamp(assignment["lease_expires_at"]) > now_dt
            )
            if is_live_same_actor_renewal:
                run_id = active_run_id
                conn.execute(
                    """
                    update runs
                    set lease_expires_at = ?,
                        updated_at = ?
                    where run_id = ?
                    """,
                    (lease_expires_at, now, run_id),
                )
            else:
                if active_run_id is not None and not active_run_is_terminal:
                    conn.execute(
                        """
                        update runs
                        set status = 'superseded',
                            ended_at = ?,
                            updated_at = ?
                        where run_id = ?
                        """,
                        (now, now, active_run_id),
                    )
                run_id = f"run_{uuid.uuid4().hex}"
                attempt = conn.execute(
                    """
                    select coalesce(max(attempt), 0) + 1
                    from runs
                    where assignment_id = ?
                    """,
                    (assignment_id,),
                ).fetchone()[0]
                conn.execute(
                    """
                    insert into runs (
                        run_id, assignment_id, team_id, actor_id, attempt, status,
                        lease_expires_at, heartbeat_at, started_at, ended_at,
                        updated_at, session_kind, session_ref, interactive_url,
                        worktree_path, branch, base_commit, head_commit,
                        resume_of_run_id, metadata_json
                    )
                    values (
                        ?, ?, ?, ?, ?, 'claimed', ?, null, ?, null, ?, ?, ?, ?, ?,
                        ?, ?, null, ?, ?
                    )
                    """,
                    (
                        run_id,
                        assignment_id,
                        assignment["team_id"],
                        actor_id,
                        attempt,
                        lease_expires_at,
                        now,
                        now,
                        session_kind,
                        session_ref,
                        interactive_url,
                        worktree_path,
                        branch,
                        base_commit,
                        resume_of_run_id,
                        self._json({}),
                    ),
                )
            conn.execute(
                """
                update assignments
                set status = 'claimed',
                    active_run_id = ?,
                    revision = ?,
                    updated_at = ?,
                    claimed_by = ?,
                    lease_expires_at = ?
                where assignment_id = ?
                """,
                (
                    run_id,
                    next_revision,
                    now,
                    actor_id,
                    lease_expires_at,
                    assignment_id,
                ),
            )
            self._insert_event(
                conn,
                assignment_id=assignment_id,
                event_type="run_claimed",
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"lease_ttl_seconds": lease_ttl_seconds},
                reviewed_event_id=None,
                assignment_revision=next_revision,
                created_at=now,
                run_id=run_id,
            )
        return self._get_assignment(assignment_id)

    def append_event(
        self,
        *,
        assignment_id: str,
        event_type: str,
        status: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        self._require_event_status(status)
        if status in DECISION_STATUSES:
            raise ValidationError("review decisions must use review_event")
        now = self._now()
        with self._connect() as conn:
            assignment = self._require_current_assignment(conn, assignment_id, base_revision)
            self._require_assignment_accepts_writes(assignment)
            self._require_agent_owns_assignment_active_run(
                conn,
                assignment=assignment,
                actor_id=actor_id,
                actor_role=actor_role,
            )
            next_revision = assignment["revision"] + 1
            event = self._insert_event(
                conn,
                assignment_id=assignment_id,
                event_type=event_type,
                status=status,
                actor_id=actor_id,
                actor_role=actor_role,
                payload=payload,
                reviewed_event_id=None,
                assignment_revision=next_revision,
                created_at=now,
                run_id=assignment.get("active_run_id"),
            )
            conn.execute(
                """
                update assignments
                set revision = ?, updated_at = ?
                where assignment_id = ?
                """,
                (next_revision, now, assignment_id),
            )
        return event

    def submit_handoff(
        self,
        *,
        assignment_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        now = self._now()
        with self._connect() as conn:
            assignment = self._require_current_assignment(conn, assignment_id, base_revision)
            self._require_assignment_accepts_writes(assignment)
            self._require_agent_owns_assignment_active_run(
                conn,
                assignment=assignment,
                actor_id=actor_id,
                actor_role=actor_role,
            )
            next_revision = assignment["revision"] + 1
            event = self._insert_event(
                conn,
                assignment_id=assignment_id,
                event_type="handoff_submitted",
                status="completed_gate_passed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload=payload,
                reviewed_event_id=None,
                assignment_revision=next_revision,
                created_at=now,
                run_id=assignment.get("active_run_id"),
            )
            if assignment["active_run_id"] is not None:
                conn.execute(
                    """
                    update runs
                    set status = 'completed_gate_passed',
                        updated_at = ?
                    where run_id = ?
                    """,
                    (now, assignment["active_run_id"]),
                )
            conn.execute(
                """
                update assignments
                set status = 'awaiting_review',
                    revision = ?,
                    updated_at = ?
                where assignment_id = ?
                """,
                (next_revision, now, assignment_id),
            )
        return event

    def heartbeat_run(
        self,
        *,
        run_id: str,
        actor_id: str,
        actor_role: str,
        summary: str,
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        now = self._now()
        with self._connect() as conn:
            run, assignment = self._require_active_mutable_run(conn, run_id)
            self._require_agent_owns_run(run, actor_id, actor_role)
            wait_statuses = {"awaiting_human", "awaiting_approval"}
            run_status = run["status"] if run["status"] in wait_statuses else "running"
            assignment_status = (
                assignment["status"] if assignment["status"] in wait_statuses else "running"
            )
            conn.execute(
                """
                update runs
                set status = ?,
                    heartbeat_at = ?,
                    updated_at = ?
                where run_id = ?
                """,
                (run_status, now, now, run_id),
            )
            conn.execute(
                """
                update assignments
                set status = ?,
                    updated_at = ?
                where assignment_id = ?
                  and active_run_id = ?
                """,
                (assignment_status, now, assignment["assignment_id"], run_id),
            )
            event = self._insert_run_event(
                conn,
                run=run,
                assignment=assignment,
                event_type="run_heartbeat",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"summary": summary},
                reviewed_event_id=None,
                created_at=now,
            )
        return event

    def record_run_binding(
        self,
        *,
        run_id: str,
        actor_id: str,
        actor_role: str,
        binding_patch: dict[str, Any],
        event_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        if not isinstance(binding_patch, dict):
            raise ValidationError("binding_patch must be a JSON object")
        now = self._now()
        with self._connect() as conn:
            run, assignment = self._require_active_mutable_run(conn, run_id)
            self._require_agent_owns_run(run, actor_id, actor_role)
            metadata = self._merge_json_object(run["metadata"], binding_patch)
            conn.execute(
                """
                update runs
                set metadata_json = ?,
                    updated_at = ?
                where run_id = ?
                """,
                (self._json(metadata), now, run_id),
            )
            self._insert_run_event(
                conn,
                run=run,
                assignment=assignment,
                event_type="run_binding_recorded",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={
                    "binding_patch": binding_patch,
                    "event_payload": event_payload or {},
                },
                reviewed_event_id=None,
                created_at=now,
            )
        return self.get_run_detail(run_id)

    def checkpoint_run(
        self,
        *,
        run_id: str,
        actor_id: str,
        actor_role: str,
        client_update_id: str,
        source_event_sequence: int,
        brief: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        if not isinstance(client_update_id, str) or not client_update_id.strip():
            raise ValidationError("client_update_id must be a non-empty string")
        try:
            normalized_brief = normalize_human_brief(brief)
        except ValueError as error:
            raise ValidationError(str(error)) from error
        if (
            isinstance(source_event_sequence, bool)
            or not isinstance(source_event_sequence, int)
            or source_event_sequence <= 0
        ):
            raise ValidationError("source_event_sequence must be a positive integer")

        payload = {
            "client_update_id": client_update_id,
            "source_event_sequence": source_event_sequence,
            "brief": normalized_brief,
        }
        now = self._now()
        with self._connect() as conn:
            run, assignment = self._require_active_mutable_run(conn, run_id)
            self._require_agent_owns_run(run, actor_id, actor_role)
            source = conn.execute(
                "select 1 from events where run_id = ? and sequence = ?",
                (run_id, source_event_sequence),
            ).fetchone()
            if source is None:
                raise ValidationError(
                    "source_event_sequence must reference an existing event for the run"
                )

            prior_rows = conn.execute(
                """
                select *
                from events
                where run_id = ? and event_type = 'human_brief_updated'
                order by sequence
                """,
                (run_id,),
            ).fetchall()
            prior_events = [self._event_from_row(row) for row in prior_rows]
            for prior in prior_events:
                if prior["payload"].get("client_update_id") == client_update_id:
                    if prior["payload"] == payload:
                        return prior
                    raise ValidationError("client_update_id already used with a different payload")
            if (
                prior_events
                and source_event_sequence < prior_events[-1]["payload"]["source_event_sequence"]
            ):
                raise ValidationError("source_event_sequence cannot be older than the latest brief")

            return self._insert_run_event(
                conn,
                run=run,
                assignment=assignment,
                event_type="human_brief_updated",
                actor_id=actor_id,
                actor_role=actor_role,
                payload=payload,
                reviewed_event_id=None,
                created_at=now,
            )

    def get_human_brief(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            run_row = conn.execute(
                "select * from runs where run_id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                raise ValidationError(f"run not found: {run_id}")
            run = self._run_from_row(run_row)
            event_row = conn.execute(
                """
                select *
                from events
                where run_id = ? and event_type = 'human_brief_updated'
                order by sequence desc
                limit 1
                """,
                (run_id,),
            ).fetchone()
            if event_row is None:
                raise ValidationError(f"human brief not found for run: {run_id}")
            latest_sequence = conn.execute(
                """
                select max(sequence)
                from events
                where run_id = ? and event_type != 'human_brief_updated'
                """,
                (run_id,),
            ).fetchone()[0]
            team_row = conn.execute(
                "select settings_json from teams where team_id = ?",
                (run["team_id"],),
            ).fetchone()

        event = self._event_from_row(event_row)
        settings = json.loads(team_row["settings_json"]) if team_row is not None else {}
        configured_window = settings.get(
            "freshness_window_minutes", DEFAULT_FRESHNESS_WINDOW_MINUTES
        )
        if (
            isinstance(configured_window, bool)
            or not isinstance(configured_window, int)
            or configured_window <= 0
        ):
            configured_window = DEFAULT_FRESHNESS_WINDOW_MINUTES
        payload = event["payload"]
        return {
            "run_id": run_id,
            "assignment_id": run["assignment_id"],
            "brief": payload["brief"],
            "client_update_id": payload["client_update_id"],
            "source_event_sequence": payload["source_event_sequence"],
            "latest_event_sequence": latest_sequence,
            "updated_at": event["created_at"],
            "freshness": brief_freshness(
                updated_at=event["created_at"],
                source_event_sequence=payload["source_event_sequence"],
                latest_event_sequence=latest_sequence,
                now=datetime.now(UTC),
                freshness_window_minutes=configured_window,
            ),
            "freshness_window_minutes": configured_window,
        }

    def raise_attention(
        self,
        *,
        run_id: str,
        actor_id: str,
        actor_role: str,
        client_update_id: str,
        level: str,
        target: str,
        dedupe_key: str,
        reason_code: str,
        why_now: str,
        recommended_action: str,
        source_event_ids: list[str],
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        if not isinstance(client_update_id, str) or not client_update_id.strip():
            raise ValidationError("client_update_id must be a non-empty string")
        try:
            attention = normalize_attention_item(
                {
                    "level": level,
                    "target": target,
                    "blocking": False,
                    "dedupe_key": dedupe_key,
                    "reason_code": reason_code,
                    "why_now": why_now,
                    "recommended_action": recommended_action,
                    "source_event_ids": source_event_ids,
                }
            )
        except ValueError as error:
            raise ValidationError(str(error)) from error

        payload = {
            "client_update_id": client_update_id,
            "attention": attention,
        }
        now = self._now()
        with self._connect() as conn:
            run, assignment = self._require_active_mutable_run(conn, run_id)
            self._require_agent_owns_run(run, actor_id, actor_role)
            prior_rows = conn.execute(
                """
                select *
                from events
                where run_id = ? and event_type = 'attention_raised'
                order by sequence
                """,
                (run_id,),
            ).fetchall()
            for row in prior_rows:
                prior = self._event_from_row(row)
                if prior["payload"].get("client_update_id") == client_update_id:
                    if prior["payload"] == payload:
                        return prior
                    raise ValidationError("client_update_id already used with a different payload")
            return self._insert_run_event(
                conn,
                run=run,
                assignment=assignment,
                event_type="attention_raised",
                actor_id=actor_id,
                actor_role=actor_role,
                payload=payload,
                reviewed_event_id=None,
                created_at=now,
            )

    def get_attention_board(
        self,
        team_id: str = "default",
        target: str = "human",
        include_green: bool = False,
    ) -> dict[str, Any]:
        team = self._get_team(team_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                select e.*
                from events e
                join assignments a on a.assignment_id = e.assignment_id
                where e.team_id = ?
                  and e.event_type in ('attention_raised', 'intervention_requested')
                order by e.sequence
                """,
                (team_id,),
            ).fetchall()
            resolved_rows = conn.execute(
                """
                select reviewed_event_id
                from events
                where team_id = ?
                  and event_type = 'intervention_responded'
                  and reviewed_event_id is not null
                """,
                (team_id,),
            ).fetchall()
            assignment_rows = conn.execute(
                "select assignment_id, status from assignments where team_id = ?",
                (team_id,),
            ).fetchall()

        resolved_ids = {row["reviewed_event_id"] for row in resolved_rows}
        assignment_statuses = {row["assignment_id"]: row["status"] for row in assignment_rows}
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        red_items: list[dict[str, Any]] = []
        for row in rows:
            event = self._event_from_row(row)
            if assignment_statuses.get(event["assignment_id"]) in TERMINAL_ASSIGNMENT_STATUSES:
                continue
            if event["event_type"] == "attention_raised":
                attention = event["payload"]["attention"]
                latest[(event["run_id"], attention["dedupe_key"])] = {
                    **attention,
                    "client_update_id": event["payload"]["client_update_id"],
                    "event_id": event["event_id"],
                    "sequence": event["sequence"],
                    "run_id": event["run_id"],
                    "assignment_id": event["assignment_id"],
                    "team_id": event["team_id"],
                    "updated_at": event["created_at"],
                }
                continue
            if target != "human" or event["event_id"] in resolved_ids:
                continue
            payload = event["payload"]
            red_items.append(
                {
                    "level": "red",
                    "target": "human",
                    "blocking": True,
                    "dedupe_key": f"intervention:{event['event_id']}",
                    "reason_code": payload["intervention_kind"],
                    "why_now": payload["prompt"],
                    "recommended_action": "Respond to the intervention request",
                    "source_event_ids": [event["event_id"]],
                    "decision_packet": payload.get("decision_packet"),
                    "event_id": event["event_id"],
                    "sequence": event["sequence"],
                    "run_id": event["run_id"],
                    "assignment_id": event["assignment_id"],
                    "team_id": event["team_id"],
                    "updated_at": event["created_at"],
                }
            )

        projected = [
            *red_items,
            *(item for item in latest.values() if item["target"] == target),
        ]
        counts = {
            level: sum(item["level"] == level for item in projected)
            for level in ("red", "yellow", "green")
        }
        visible = [item for item in projected if include_green or item["level"] != "green"]
        level_order = {"red": 0, "yellow": 1, "green": 2}
        visible.sort(key=lambda item: (level_order[item["level"]], item["sequence"]))
        settings = team["settings"]
        return {
            "team_id": team_id,
            "target": target,
            "counts": counts,
            "items": visible,
            "digest": {
                "interval_minutes": settings.get(
                    "yellow_digest_minutes", DEFAULT_YELLOW_DIGEST_MINUTES
                ),
                "channel": settings.get("attention_channel", "product_inbox"),
                "group_by": ["owner", "project", "assignment"],
            },
        }

    def request_intervention(
        self,
        *,
        run_id: str,
        actor_id: str,
        actor_role: str,
        prompt: str,
        intervention_kind: str,
        decision_packet: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        if decision_packet is not None and not isinstance(decision_packet, dict):
            raise ValidationError("decision_packet must be a JSON object")
        now = self._now()
        with self._connect() as conn:
            run, assignment = self._require_active_mutable_run(conn, run_id)
            self._require_agent_owns_run(run, actor_id, actor_role)
            conn.execute(
                """
                update runs
                set status = 'awaiting_human',
                    updated_at = ?
                where run_id = ?
                """,
                (now, run_id),
            )
            conn.execute(
                """
                update assignments
                set status = 'awaiting_human',
                    updated_at = ?
                where assignment_id = ?
                  and active_run_id = ?
                """,
                (now, assignment["assignment_id"], run_id),
            )
            payload: dict[str, Any] = {
                "prompt": prompt,
                "intervention_kind": intervention_kind,
            }
            if decision_packet is not None:
                payload["decision_packet"] = decision_packet
            event = self._insert_run_event(
                conn,
                run=run,
                assignment=assignment,
                event_type="intervention_requested",
                actor_id=actor_id,
                actor_role=actor_role,
                payload=payload,
                reviewed_event_id=None,
                created_at=now,
            )
        return event

    def respond_intervention(
        self,
        *,
        run_id: str,
        actor_id: str,
        actor_role: str,
        response: str,
        reviewed_event_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        now = self._now()
        payload = {"response": response}
        if reviewed_event_id is not None:
            payload["reviewed_event_id"] = reviewed_event_id
        with self._connect() as conn:
            run, assignment = self._require_active_mutable_run(conn, run_id)
            self._require_agent_owns_run(run, actor_id, actor_role)
            self._validate_intervention_review_target(
                conn,
                run=run,
                assignment=assignment,
                reviewed_event_id=reviewed_event_id,
            )
            conn.execute(
                """
                update runs
                set status = 'running',
                    updated_at = ?
                where run_id = ?
                """,
                (now, run_id),
            )
            conn.execute(
                """
                update assignments
                set status = 'running',
                    updated_at = ?
                where assignment_id = ?
                  and active_run_id = ?
                """,
                (now, assignment["assignment_id"], run_id),
            )
            event = self._insert_run_event(
                conn,
                run=run,
                assignment=assignment,
                event_type="intervention_responded",
                actor_id=actor_id,
                actor_role=actor_role,
                payload=payload,
                reviewed_event_id=reviewed_event_id,
                created_at=now,
            )
        return event

    def list_pending_reviews(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select e.*
                from events e
                where e.status in ({placeholders})
                  and e.event_type in ({event_type_placeholders})
                  and not exists (
                    select 1
                    from events decision
                    where decision.reviewed_event_id = e.event_id
                      and decision.status in ('integrator_accepted',
                                              'integrator_rejected',
                                              'needs_fix')
                  )
                order by e.created_at, e.sequence
                """.format(
                    placeholders=",".join("?" for _ in REVIEWABLE_EVENT_STATUSES),
                    event_type_placeholders=",".join("?" for _ in REVIEWABLE_EVENT_TYPES),
                ),
                (
                    *tuple(sorted(REVIEWABLE_EVENT_STATUSES)),
                    *tuple(sorted(REVIEWABLE_EVENT_TYPES)),
                ),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def review_event(
        self,
        *,
        event_id: str,
        decision_status: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        self._require_integrator(actor_role)
        if decision_status not in DECISION_STATUSES:
            raise ValidationError(f"invalid decision status: {decision_status}")
        now = self._now()
        with self._connect() as conn:
            target = conn.execute(
                "select * from events where event_id = ?",
                (event_id,),
            ).fetchone()
            if target is None:
                raise ValidationError(f"event not found: {event_id}")
            target_event = self._event_from_row(target)
            if (
                target_event["event_type"] not in REVIEWABLE_EVENT_TYPES
                or target_event["status"] not in REVIEWABLE_EVENT_STATUSES
            ):
                raise ValidationError(f"event is not reviewable: {event_id}")
            assignment = self._require_current_assignment(
                conn, target_event["assignment_id"], base_revision
            )
            existing_decision = conn.execute(
                """
                select 1 from events
                where reviewed_event_id = ?
                  and status in ('integrator_accepted',
                                 'integrator_rejected',
                                 'needs_fix')
                """,
                (event_id,),
            ).fetchone()
            if existing_decision:
                raise ValidationError(f"event already reviewed: {event_id}")
            next_revision = assignment["revision"] + 1
            decision = self._insert_event(
                conn,
                assignment_id=target_event["assignment_id"],
                event_type="integrator_review",
                status=decision_status,
                actor_id=actor_id,
                actor_role=actor_role,
                payload={
                    "decision_note": decision_note,
                    "reviewed_event": target_event,
                },
                reviewed_event_id=event_id,
                assignment_revision=next_revision,
                created_at=now,
            )
            assignment_status = {
                "integrator_accepted": "accepted",
                "integrator_rejected": "rejected",
                "needs_fix": "needs_fix",
            }[decision_status]
            completed_at = None if decision_status == "needs_fix" else now
            if assignment["active_run_id"] is not None:
                run_status = (
                    "completed_gate_passed"
                    if decision_status == "integrator_accepted"
                    else "completed_gate_failed"
                )
                conn.execute(
                    """
                    update runs
                    set status = ?,
                        ended_at = ?,
                        updated_at = ?
                    where run_id = ?
                    """,
                    (run_status, now, now, assignment["active_run_id"]),
                )
            conn.execute(
                """
                update assignments
                set status = ?,
                    revision = ?,
                    updated_at = ?,
                    completed_at = ?
                where assignment_id = ?
                """,
                (
                    assignment_status,
                    next_revision,
                    now,
                    completed_at,
                    target_event["assignment_id"],
                ),
            )
        return decision

    def accept_event(
        self,
        *,
        event_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        return self.review_event(
            event_id=event_id,
            decision_status="integrator_accepted",
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            decision_note=decision_note,
        )

    def reject_event(
        self,
        *,
        event_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        return self.review_event(
            event_id=event_id,
            decision_status="integrator_rejected",
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            decision_note=decision_note,
        )

    def cancel_assignment(
        self,
        *,
        assignment_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        """Integrator voids an assignment that should not be worked (mistake, scope dropped)."""
        return self._close_assignment(
            assignment_id=assignment_id,
            new_status="cancelled",
            event_type="assignment_cancelled",
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            payload={"reason": reason},
            extra_metadata=None,
        )

    def supersede_assignment(
        self,
        *,
        assignment_id: str,
        superseded_by: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        """Integrator retires an assignment replaced by another one (``superseded_by``)."""
        self._require_integrator(actor_role)
        if superseded_by == assignment_id:
            raise ValidationError("an assignment cannot supersede itself")
        # Validate the replacement exists (raises ValidationError if missing).
        self._get_assignment(superseded_by)
        return self._close_assignment(
            assignment_id=assignment_id,
            new_status="superseded",
            event_type="assignment_superseded",
            actor_id=actor_id,
            actor_role=actor_role,
            base_revision=base_revision,
            payload={"reason": reason, "superseded_by": superseded_by},
            extra_metadata={"superseded_by": superseded_by},
        )

    def _close_assignment(
        self,
        *,
        assignment_id: str,
        new_status: str,
        event_type: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        payload: dict[str, Any],
        extra_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self._require_integrator(actor_role)
        now = self._now()
        with self._connect() as conn:
            assignment = self._require_current_assignment(conn, assignment_id, base_revision)
            if assignment["status"] in {"accepted", "rejected", "cancelled", "superseded"}:
                raise ValidationError(
                    f"assignment already terminal: {assignment_id} is {assignment['status']}"
                )
            next_revision = assignment["revision"] + 1
            active_run_id = assignment["active_run_id"]
            if active_run_id is not None:
                conn.execute(
                    """
                    update runs
                    set status = 'cancelled',
                        ended_at = ?,
                        updated_at = ?
                    where run_id = ?
                      and status not in ('completed_gate_passed', 'completed_gate_failed',
                                         'failed', 'cancelled', 'superseded')
                    """,
                    (now, now, active_run_id),
                )
            metadata = assignment["metadata"]
            if extra_metadata:
                metadata = {**metadata, **extra_metadata}
            self._insert_event(
                conn,
                assignment_id=assignment_id,
                event_type=event_type,
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload=payload,
                reviewed_event_id=None,
                assignment_revision=next_revision,
                created_at=now,
                run_id=active_run_id,
            )
            conn.execute(
                """
                update assignments
                set status = ?,
                    revision = ?,
                    updated_at = ?,
                    completed_at = ?,
                    active_run_id = null,
                    claimed_by = null,
                    lease_expires_at = null,
                    metadata_json = ?
                where assignment_id = ?
                """,
                (new_status, next_revision, now, now, self._json(metadata), assignment_id),
            )
        return self._get_assignment(assignment_id)

    def get_run_detail(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from runs where run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ValidationError(f"run not found: {run_id}")
            run = self._run_from_row(row)
            events = conn.execute(
                """
                select *
                from events
                where run_id = ?
                order by sequence
                """,
                (run_id,),
            ).fetchall()
        run["events"] = [self._event_from_row(event) for event in events]
        return run

    def get_assignment_detail(self, assignment_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from assignments where assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                raise ValidationError(f"assignment not found: {assignment_id}")
            runs = conn.execute(
                """
                select *
                from runs
                where assignment_id = ?
                order by attempt, started_at, run_id
                """,
                (assignment_id,),
            ).fetchall()
            events = conn.execute(
                """
                select *
                from events
                where assignment_id = ?
                order by sequence
                """,
                (assignment_id,),
            ).fetchall()
        return {
            "assignment": self._assignment_from_row(row),
            "runs": [self._run_from_row(run) for run in runs],
            "events": [self._event_from_row(event) for event in events],
        }

    def get_team_board(self, team_id: str) -> dict[str, Any]:
        team = self._get_team(team_id)
        lanes: dict[str, list[dict[str, Any]]] = {
            "ready": [],
            "running": [],
            "awaiting_human": [],
            "awaiting_review": [],
            "needs_fix": [],
            "accepted": [],
            "rejected": [],
            "blocked": [],
        }
        lane_by_status = {
            "proposed": "ready",
            "ready": "ready",
            "claimed": "running",
            "running": "running",
            "awaiting_human": "awaiting_human",
            "awaiting_approval": "awaiting_review",
            "awaiting_review": "awaiting_review",
            "needs_fix": "needs_fix",
            "accepted": "accepted",
            "rejected": "rejected",
            "stalled": "blocked",
            "blocked": "blocked",
        }
        with self._connect() as conn:
            rows = conn.execute(
                """
                select *
                from assignments
                where team_id = ?
                order by priority desc, created_at, assignment_id
                """,
                (team_id,),
            ).fetchall()
        for row in rows:
            assignment = self._assignment_from_row(row)
            lane = lane_by_status.get(assignment["status"])
            if lane is not None:
                lanes[lane].append(assignment)
        return {"team": team, "lanes": lanes}

    def get_snapshot(self) -> dict[str, Any]:
        accepted_events = self._accepted_events()
        active_assignments: dict[str, Any] = {}
        for decision in accepted_events:
            reviewed = decision["payload"]["reviewed_event"]
            assignment = self._get_assignment(reviewed["assignment_id"])
            active_assignments[reviewed["assignment_id"]] = {
                "status": "integrator_accepted",
                "title": assignment["title"],
                "revision": assignment["revision"],
                "accepted_event_id": reviewed["event_id"],
                "accepted_by": decision["actor_id"],
                "accepted_at": decision["created_at"],
                "payload": reviewed["payload"],
            }
        accepted_contracts, open_governance = self._contract_projection()
        return {
            "schema_version": "agent_team.collaboration.snapshot.v1",
            "ledger_version": "coordination-memory-six-table-core",
            "generated_at": self._now(),
            "workspaces": self._workspace_map(),
            "teams": self._team_map(),
            "accepted_contracts": accepted_contracts,
            # kept as an empty placeholder for backward-compatible projection
            # schema (P2/P3 accepted-state.json); superseded by open_governance.
            "contract_statuses": {},
            "open_governance": open_governance,
            "active_assignments": active_assignments,
            "accepted_events": [
                decision["payload"]["reviewed_event"] for decision in accepted_events
            ],
            "single_writer_rules": {
                "accepted_ledger_writer": "Integrator",
                "module_agent_shared_state": "handoff_or_append_only_event_only",
                "proposal_is_truth": False,
            },
        }

    def _contract_projection(self) -> tuple[dict[str, Any], dict[str, Any]]:
        accepted: dict[str, Any] = {}
        open_gov: dict[str, Any] = {}
        open_statuses = {"repair_ready", "awaiting_acceptor", "awaiting_human", "verifying"}
        with self._connect() as conn:
            rows = conn.execute("select * from acceptance_contracts").fetchall()
        for row in rows:
            contract = self._contract_from_row(row)
            cid = contract["contract_id"]
            invariants = self._invariants(cid)
            if contract["status"] == "accepted":
                latest = self._latest_verifications(cid)
                accepted[cid] = {
                    "status": "accepted",
                    "title": contract["title"],
                    "goal_statement": contract["goal_statement"],
                    "acceptor_actor_id": contract["acceptor_actor_id"],
                    "decided_at": contract["decided_at"],
                    "invariants": [i["key"] for i in invariants],
                    "verification_outcomes": latest,
                    "deviations": self._deviations(cid),
                }
            elif contract["status"] in open_statuses:
                open_gov[cid] = {
                    "status": contract["status"],
                    "title": contract["title"],
                    "failing_invariants": sorted(self._failing_required_keys(cid)),
                    "open_blocker": self._has_open_blocker(cid),
                    "repair_attempt": contract["repair_attempt"],
                }
        return accepted, open_gov

    def get_contract_detail(self, contract_id: str) -> dict[str, Any]:
        contract = self._get_contract(contract_id)
        with self._connect() as conn:
            vers = conn.execute(
                """
                select v.*, i.key as invariant_key
                from contract_verifications v
                join contract_invariants i on i.invariant_id = v.invariant_id
                where v.contract_id = ?
                order by v.created_at, v.rowid
                """,
                (contract_id,),
            ).fetchall()
            bound = conn.execute(
                """
                select assignment_id, title, status, active_run_id
                from assignments
                where contract_id = ?
                order by created_at, assignment_id
                """,
                (contract_id,),
            ).fetchall()
            event_rows = conn.execute(
                "select * from events where assignment_id is null order by sequence"
            ).fetchall()
        contract_events = [
            self._event_from_row(r)
            for r in event_rows
            if json.loads(r["payload_json"]).get("contract_id") == contract_id
        ]
        return {
            "contract": contract,
            "invariants": self._invariants(contract_id),
            "deviations": self._deviations(contract_id),
            "verifications": [
                {
                    "invariant_key": r["invariant_key"],
                    "outcome": r["outcome"],
                    "reporter_actor_id": r["reporter_actor_id"],
                    "repair_attempt": r["repair_attempt"],
                    "created_at": r["created_at"],
                }
                for r in vers
            ],
            "latest_verifications": self._latest_verifications(contract_id),
            "failing_required": sorted(self._failing_required_keys(contract_id)),
            "bound_assignments": [
                {
                    "assignment_id": r["assignment_id"],
                    "title": r["title"],
                    "status": r["status"],
                    "active_run_id": r["active_run_id"],
                }
                for r in bound
            ],
            "events": contract_events,
        }

    def list_contracts(
        self,
        workspace_id: str | None = None,
        team_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if team_id is not None:
            clauses.append("team_id = ?")
            params.append(team_id)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"select * from acceptance_contracts {where} order by created_at",
                params,
            ).fetchall()
        return [self._contract_from_row(r) for r in rows]

    def create_acceptance_contract(
        self,
        *,
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
        self._require_integrator(actor_role)
        if base_revision != 0:
            raise StaleRevisionError("new contracts must use base_revision=0")
        now = self._now()
        with self._connect() as conn:
            exists = conn.execute(
                "select 1 from acceptance_contracts where contract_id = ?",
                (contract_id,),
            ).fetchone()
            if exists:
                raise ValidationError(f"contract already exists: {contract_id}")
            self._ensure_actor_record(conn, actor_id, actor_role)
            conn.execute(
                """
                insert into acceptance_contracts (
                    contract_id, workspace_id, team_id, title, goal_statement,
                    status, revision, created_by_actor_id, author_actor_id,
                    acceptor_actor_id, max_repair_attempts, repair_attempt,
                    last_failing_keys_json, metadata_json, created_at, updated_at,
                    sealed_at, decided_at
                )
                values (?, ?, ?, ?, ?, 'drafting', 1, ?, ?, null, ?, 0, '[]', ?, ?, ?, null, null)
                """,
                (
                    contract_id,
                    workspace_id,
                    team_id,
                    title,
                    goal_statement,
                    actor_id,
                    author_actor_id or actor_id,
                    max_repair_attempts,
                    self._json(metadata or {}),
                    now,
                    now,
                ),
            )
            self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="contract_created",
                status="proposed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"title": title, "goal_statement": goal_statement},
            )
        return self._get_contract(contract_id)

    def _get_contract(self, contract_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from acceptance_contracts where contract_id = ?",
                (contract_id,),
            ).fetchone()
        if row is None:
            raise ValidationError(f"contract not found: {contract_id}")
        return self._contract_from_row(row)

    def _require_current_contract(
        self, conn: sqlite3.Connection, contract_id: str, base_revision: int
    ) -> dict[str, Any]:
        row = conn.execute(
            "select * from acceptance_contracts where contract_id = ?",
            (contract_id,),
        ).fetchone()
        if row is None:
            raise ValidationError(f"contract not found: {contract_id}")
        contract = self._contract_from_row(row)
        if contract["revision"] != base_revision:
            raise StaleRevisionError(
                f"stale base_revision for {contract_id}: "
                f"expected {contract['revision']}, got {base_revision}"
            )
        return contract

    def _bump_contract(
        self,
        conn: sqlite3.Connection,
        contract_id: str,
        *,
        status: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        fields = ["revision = revision + 1", "updated_at = ?"]
        params: list[Any] = [self._now()]
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        for column, value in (extra or {}).items():
            fields.append(f"{column} = ?")
            params.append(value)
        params.append(contract_id)
        conn.execute(
            f"update acceptance_contracts set {', '.join(fields)} where contract_id = ?",
            params,
        )

    def _insert_contract_event(
        self,
        conn: sqlite3.Connection,
        *,
        contract_id: str,
        event_type: str,
        status: str,
        actor_id: str,
        actor_role: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        row = conn.execute(
            "select workspace_id, team_id from acceptance_contracts where contract_id = ?",
            (contract_id,),
        ).fetchone()
        if row is None:
            raise ValidationError(f"contract not found: {contract_id}")
        self._ensure_actor_record(conn, actor_id, actor_role)
        event_id = f"evt_{uuid.uuid4().hex}"
        enriched = {"contract_id": contract_id, **payload}
        conn.execute(
            """
            insert into events (
                event_id, workspace_id, team_id, assignment_id, run_id, event_type,
                status, actor_id, actor_role, payload_json, reviewed_event_id,
                assignment_revision, safety_label, created_at
            )
            values (?, ?, ?, null, null, ?, ?, ?, ?, ?, null, null, 'internal', ?)
            """,
            (
                event_id,
                row["workspace_id"],
                row["team_id"],
                event_type,
                status,
                actor_id,
                actor_role,
                self._json(enriched),
                self._now(),
            ),
        )
        return {"event_id": event_id, "event_type": event_type, "status": status}

    def _contract_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "contract_id": row["contract_id"],
            "workspace_id": row["workspace_id"],
            "team_id": row["team_id"],
            "title": row["title"],
            "goal_statement": row["goal_statement"],
            "status": row["status"],
            "revision": row["revision"],
            "created_by_actor_id": row["created_by_actor_id"],
            "author_actor_id": row["author_actor_id"],
            "acceptor_actor_id": row["acceptor_actor_id"],
            "max_repair_attempts": row["max_repair_attempts"],
            "repair_attempt": row["repair_attempt"],
            "last_failing_keys": json.loads(row["last_failing_keys_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "sealed_at": row["sealed_at"],
            "decided_at": row["decided_at"],
        }

    def add_invariant(
        self,
        *,
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
        self._require_known_role(actor_role)
        if probe_kind not in PROBE_KINDS:
            raise ValidationError(f"invalid probe_kind: {probe_kind}")
        now = self._now()
        with self._connect() as conn:
            contract = self._require_current_contract(conn, contract_id, base_revision)
            if contract["status"] not in CONTRACT_MUTABLE_STATUSES:
                raise ValidationError(
                    f"invariants are frozen: {contract_id} is {contract['status']}"
                )
            dup = conn.execute(
                "select 1 from contract_invariants where contract_id = ? and key = ?",
                (contract_id, key),
            ).fetchone()
            if dup:
                raise ValidationError(f"invariant key already exists: {key}")
            conn.execute(
                """
                insert into contract_invariants (
                    invariant_id, contract_id, key, description, probe_kind,
                    probe_spec_json, required, is_negative, is_second_instance,
                    created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"inv_{uuid.uuid4().hex}",
                    contract_id,
                    key,
                    description,
                    probe_kind,
                    self._json(probe_spec),
                    int(required),
                    int(is_negative),
                    int(is_second_instance),
                    now,
                    now,
                ),
            )
            self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="invariant_added",
                status="proposed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"key": key, "probe_kind": probe_kind},
            )
            self._bump_contract(conn, contract_id)
        return self._get_contract(contract_id)

    def raise_deviation(
        self,
        *,
        contract_id: str,
        title: str,
        description: str,
        disposition: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        if disposition not in DEVIATION_DISPOSITIONS:
            raise ValidationError(f"invalid disposition: {disposition}")
        now = self._now()
        with self._connect() as conn:
            self._require_current_contract(conn, contract_id, base_revision)
            conn.execute(
                """
                insert into contract_deviations (
                    deviation_id, contract_id, title, description, disposition,
                    status, raised_by_actor_id, raised_role, disposed_by_actor_id,
                    waiver_event_id, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, 'open', ?, ?, null, null, ?, ?)
                """,
                (
                    f"dev_{uuid.uuid4().hex}",
                    contract_id,
                    title,
                    description,
                    disposition,
                    actor_id,
                    actor_role,
                    now,
                    now,
                ),
            )
            self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="deviation_raised",
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"title": title, "disposition": disposition},
            )
            self._bump_contract(conn, contract_id)
        return self._get_contract(contract_id)

    def _deviations(self, contract_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from contract_deviations where contract_id = ? order by created_at",
                (contract_id,),
            ).fetchall()
        return [
            {
                "deviation_id": r["deviation_id"],
                "title": r["title"],
                "description": r["description"],
                "disposition": r["disposition"],
                "status": r["status"],
                "raised_by_actor_id": r["raised_by_actor_id"],
                "disposed_by_actor_id": r["disposed_by_actor_id"],
                "waiver_event_id": r["waiver_event_id"],
            }
            for r in rows
        ]

    def _has_open_blocker(self, contract_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1 from contract_deviations
                where contract_id = ? and disposition = 'blocker' and status = 'open'
                limit 1
                """,
                (contract_id,),
            ).fetchone()
        return row is not None

    def bind_assignment_to_contract(
        self,
        *,
        contract_id: str,
        assignment_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
    ) -> dict[str, Any]:
        self._require_integrator(actor_role)
        with self._connect() as conn:
            self._require_current_contract(conn, contract_id, base_revision)
            assignment = conn.execute(
                "select 1 from assignments where assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if assignment is None:
                raise ValidationError(f"assignment not found: {assignment_id}")
            conn.execute(
                "update assignments set contract_id = ? where assignment_id = ?",
                (contract_id, assignment_id),
            )
            self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="assignment_bound",
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"assignment_id": assignment_id},
            )
            self._bump_contract(conn, contract_id)
        return self._get_contract(contract_id)

    def _bound_runner_actor_ids(self, contract_id: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select distinct r.actor_id
                from runs r
                join assignments a on a.assignment_id = r.assignment_id
                where a.contract_id = ?
                """,
                (contract_id,),
            ).fetchall()
        return {r["actor_id"] for r in rows}

    def seal_contract(
        self,
        *,
        contract_id: str,
        acceptor_actor_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
    ) -> dict[str, Any]:
        if actor_role not in {"integrator", "human"}:
            raise AuthorizationError("seal requires actor_role integrator or human")
        with self._connect() as conn:
            contract = self._require_current_contract(conn, contract_id, base_revision)
            if contract["status"] != "drafting":
                raise ValidationError(
                    f"only drafting contracts can be sealed: {contract_id} is {contract['status']}"
                )
            invariants = self._invariants(contract_id)
            if not invariants:
                raise ValidationError("cannot seal a contract with no invariants")
            if not any(i["is_negative"] for i in invariants):
                raise ValidationError("seal requires at least one negative (deny) test")
            if not any(i["is_second_instance"] for i in invariants):
                raise ValidationError("seal requires at least one second-instance test")
            for inv in invariants:
                if not inv["probe_spec"]:
                    raise ValidationError(f"invariant has empty probe_spec: {inv['key']}")
            if acceptor_actor_id in self._bound_runner_actor_ids(contract_id):
                raise AuthorizationError(
                    f"acceptor must be independent: {acceptor_actor_id} ran a bound assignment"
                )
            self._ensure_actor_record(conn, acceptor_actor_id, "human")
            self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="contract_sealed",
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={
                    "acceptor_actor_id": acceptor_actor_id,
                    "invariant_count": len(invariants),
                },
            )
            self._bump_contract(
                conn,
                contract_id,
                status="criteria_sealed",
                extra={"acceptor_actor_id": acceptor_actor_id, "sealed_at": self._now()},
            )
        return self._get_contract(contract_id)

    def _invariants(self, contract_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from contract_invariants where contract_id = ? order by created_at",
                (contract_id,),
            ).fetchall()
        return [
            {
                "invariant_id": r["invariant_id"],
                "key": r["key"],
                "description": r["description"],
                "probe_kind": r["probe_kind"],
                "probe_spec": json.loads(r["probe_spec_json"]),
                "required": bool(r["required"]),
                "is_negative": bool(r["is_negative"]),
                "is_second_instance": bool(r["is_second_instance"]),
            }
            for r in rows
        ]

    def report_verification(
        self,
        *,
        contract_id: str,
        invariant_key: str,
        outcome: str,
        actor_id: str,
        actor_role: str,
        evidence: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        if outcome not in VERIFICATION_OUTCOMES:
            raise ValidationError(f"invalid outcome: {outcome}")
        now = self._now()
        with self._connect() as conn:
            row = conn.execute(
                "select * from acceptance_contracts where contract_id = ?",
                (contract_id,),
            ).fetchone()
            if row is None:
                raise ValidationError(f"contract not found: {contract_id}")
            contract = self._contract_from_row(row)
            if contract["status"] not in {
                "criteria_sealed",
                "verifying",
                "repair_ready",
            }:
                raise ValidationError(
                    f"contract is not sealed for verification: {contract_id} is "
                    f"{contract['status']}"
                )
            inv = conn.execute(
                "select invariant_id from contract_invariants where contract_id = ? and key = ?",
                (contract_id, invariant_key),
            ).fetchone()
            if inv is None:
                raise ValidationError(f"unknown invariant: {invariant_key}")
            conn.execute(
                """
                insert into contract_verifications (
                    verification_id, invariant_id, contract_id, run_id,
                    reporter_actor_id, reporter_role, outcome, evidence_json,
                    repair_attempt, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"ver_{uuid.uuid4().hex}",
                    inv["invariant_id"],
                    contract_id,
                    run_id,
                    actor_id,
                    actor_role,
                    outcome,
                    self._json(evidence or {}),
                    contract["repair_attempt"],
                    now,
                ),
            )
            self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="verification_reported",
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"invariant_key": invariant_key, "outcome": outcome},
            )
            if contract["status"] == "criteria_sealed":
                conn.execute(
                    "update acceptance_contracts set status = 'verifying', updated_at = ? "
                    "where contract_id = ?",
                    (now, contract_id),
                )
        return self._get_contract(contract_id)

    def _latest_verifications(self, contract_id: str) -> dict[str, str]:
        """Map invariant key -> latest reported outcome (by created_at, then rowid)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                select i.key as key, v.outcome as outcome
                from contract_verifications v
                join contract_invariants i on i.invariant_id = v.invariant_id
                where v.contract_id = ?
                order by v.created_at asc, v.rowid asc
                """,
                (contract_id,),
            ).fetchall()
        latest: dict[str, str] = {}
        for row in rows:
            latest[row["key"]] = row["outcome"]
        return latest

    def _failing_required_keys(self, contract_id: str) -> set[str]:
        latest = self._latest_verifications(contract_id)
        failing: set[str] = set()
        for inv in self._invariants(contract_id):
            if not inv["required"]:
                continue
            if latest.get(inv["key"]) != "passed":
                failing.add(inv["key"])
        return failing

    def evaluate_contract(
        self,
        *,
        contract_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
    ) -> dict[str, Any]:
        self._require_known_role(actor_role)
        with self._connect() as conn:
            contract = self._require_current_contract(conn, contract_id, base_revision)
            if actor_id in self._bound_runner_actor_ids(contract_id):
                raise AuthorizationError(
                    f"evaluate must be independent: {actor_id} ran a bound assignment"
                )
            if contract["status"] not in {"verifying", "repair_ready", "criteria_sealed"}:
                raise ValidationError(
                    f"contract is not evaluable: {contract_id} is {contract['status']}"
                )
            failing = self._failing_required_keys(contract_id)
            blocked = self._has_open_blocker(contract_id)
            if not failing and not blocked:
                self._insert_contract_event(
                    conn,
                    contract_id=contract_id,
                    event_type="contract_evaluated",
                    status="observed",
                    actor_id=actor_id,
                    actor_role=actor_role,
                    payload={"result": "green"},
                )
                self._bump_contract(conn, contract_id, status="awaiting_acceptor")
            else:
                # Not green: drive the bounded self-healing repair loop.
                self._drive_repair_loop(
                    conn,
                    contract,
                    failing=failing,
                    blocked=blocked,
                    actor_id=actor_id,
                    actor_role=actor_role,
                )
        return self._get_contract(contract_id)

    def _drive_repair_loop(
        self,
        conn: sqlite3.Connection,
        contract: dict[str, Any],
        *,
        failing: set[str],
        blocked: bool,
        actor_id: str,
        actor_role: str,
    ) -> None:
        contract_id = contract["contract_id"]
        failing_sorted = sorted(failing)
        last_failing = set(contract["last_failing_keys"])
        next_attempt = contract["repair_attempt"] + 1

        # Bounded-attempts brake.
        if next_attempt > contract["max_repair_attempts"]:
            self._escalate_to_human(
                conn,
                contract,
                failing_sorted,
                blocked,
                "max_attempts_exceeded",
                actor_id,
                actor_role,
            )
            return

        # No-progress brake: a repair must strictly shrink the failing set.
        if last_failing and not (set(failing) < last_failing):
            self._escalate_to_human(
                conn,
                contract,
                failing_sorted,
                blocked,
                "no_progress",
                actor_id,
                actor_role,
            )
            return

        repair_assignment_id = f"{contract_id}-repair-{next_attempt}"
        now = self._now()
        conn.execute(
            """
            insert into assignments (
                assignment_id, workspace_id, team_id, title, status, priority,
                created_by_actor_id, active_run_id, revision, allowed_paths_json,
                acceptance_criteria_json, metadata_json, created_at, updated_at,
                completed_at, claimed_by, lease_expires_at, contract_id
            )
            values (?, ?, ?, ?, 'ready', 0, ?, null, 1, '[]', ?, ?, ?, ?, null, null, null, ?)
            """,
            (
                repair_assignment_id,
                contract["workspace_id"],
                contract["team_id"],
                f"Repair: {contract['title']} (attempt {next_attempt})",
                contract["created_by_actor_id"],
                self._json(failing_sorted),
                self._json(
                    {
                        "contract_id": contract_id,
                        "failing_invariants": failing_sorted,
                        "blocked_by_deviation": blocked,
                        "repair_attempt": next_attempt,
                    }
                ),
                now,
                now,
                contract_id,
            ),
        )
        self._insert_contract_event(
            conn,
            contract_id=contract_id,
            event_type="repair_dispatched",
            status="observed",
            actor_id=actor_id,
            actor_role=actor_role,
            payload={
                "repair_assignment_id": repair_assignment_id,
                "attempt": next_attempt,
                "failing": failing_sorted,
            },
        )
        self._bump_contract(
            conn,
            contract_id,
            status="repair_ready",
            extra={
                "repair_attempt": next_attempt,
                "last_failing_keys_json": self._json(failing_sorted),
            },
        )

    def _escalate_to_human(
        self,
        conn: sqlite3.Connection,
        contract: dict[str, Any],
        failing_sorted: list[str],
        blocked: bool,
        reason: str,
        actor_id: str,
        actor_role: str,
    ) -> None:
        self._insert_contract_event(
            conn,
            contract_id=contract["contract_id"],
            event_type="contract_escalated",
            status="observed",
            actor_id=actor_id,
            actor_role=actor_role,
            payload={"reason": reason, "failing": failing_sorted, "blocked": blocked},
        )
        self._bump_contract(
            conn,
            contract["contract_id"],
            status="awaiting_human",
            extra={"last_failing_keys_json": self._json(failing_sorted)},
        )

    def accept_contract(
        self,
        *,
        contract_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            contract = self._require_current_contract(conn, contract_id, base_revision)
            if actor_id in self._bound_runner_actor_ids(contract_id):
                raise AuthorizationError(
                    f"acceptance must be independent: {actor_id} ran a bound assignment"
                )
            if actor_id != contract["acceptor_actor_id"]:
                raise AuthorizationError(
                    f"only the bound acceptor may accept: {contract['acceptor_actor_id']}"
                )
            if contract["status"] != "awaiting_acceptor":
                raise ValidationError(
                    f"contract is not awaiting acceptance: {contract_id} is {contract['status']}"
                )
            # Re-assert the objective gate has not regressed since awaiting_acceptor.
            if self._failing_required_keys(contract_id) or self._has_open_blocker(contract_id):
                raise ValidationError("objective gate regressed; re-evaluate before acceptance")
            self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="contract_accepted",
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"decision_note": decision_note},
            )
            self._bump_contract(
                conn,
                contract_id,
                status="accepted",
                extra={"decided_at": self._now()},
            )
        return self._get_contract(contract_id)

    def reject_contract(
        self,
        *,
        contract_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        decision_note: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            contract = self._require_current_contract(conn, contract_id, base_revision)
            if actor_id != contract["acceptor_actor_id"]:
                raise AuthorizationError(
                    f"only the bound acceptor may reject: {contract['acceptor_actor_id']}"
                )
            if contract["status"] != "awaiting_acceptor":
                raise ValidationError(
                    f"contract is not awaiting acceptance: {contract_id} is {contract['status']}"
                )
            self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="contract_rejected",
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"decision_note": decision_note, "reason": "criteria_inadequate"},
            )
            self._bump_contract(conn, contract_id, status="awaiting_human")
        return self._get_contract(contract_id)

    def waive_deviation(
        self,
        *,
        contract_id: str,
        deviation_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            contract = self._require_current_contract(conn, contract_id, base_revision)
            if actor_id != contract["acceptor_actor_id"]:
                raise AuthorizationError(
                    f"only the bound acceptor may waive a blocker: {contract['acceptor_actor_id']}"
                )
            row = conn.execute(
                "select * from contract_deviations where deviation_id = ? and contract_id = ?",
                (deviation_id, contract_id),
            ).fetchone()
            if row is None:
                raise ValidationError(f"deviation not found: {deviation_id}")
            if row["status"] != "open":
                raise ValidationError(f"deviation is not open: {deviation_id}")
            waiver = self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="deviation_waived",
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"deviation_id": deviation_id, "reason": reason},
            )
            conn.execute(
                """
                update contract_deviations
                set status = 'waived', disposition = 'acceptable_this_phase',
                    disposed_by_actor_id = ?, waiver_event_id = ?, updated_at = ?
                where deviation_id = ?
                """,
                (actor_id, waiver["event_id"], self._now(), deviation_id),
            )
            self._bump_contract(conn, contract_id)
        return self._get_contract(contract_id)

    def reopen_contract(
        self,
        *,
        contract_id: str,
        actor_id: str,
        actor_role: str,
        base_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        self._require_integrator(actor_role)
        with self._connect() as conn:
            contract = self._require_current_contract(conn, contract_id, base_revision)
            if contract["status"] in {"accepted", "cancelled"}:
                raise ValidationError(
                    f"cannot reopen a {contract['status']} contract: {contract_id}"
                )
            # Invalidate prior probe results — the criteria are about to change.
            conn.execute(
                "delete from contract_verifications where contract_id = ?",
                (contract_id,),
            )
            self._insert_contract_event(
                conn,
                contract_id=contract_id,
                event_type="contract_reopened",
                status="observed",
                actor_id=actor_id,
                actor_role=actor_role,
                payload={"reason": reason},
            )
            self._bump_contract(
                conn,
                contract_id,
                status="drafting",
                extra={
                    "acceptor_actor_id": None,
                    "sealed_at": None,
                    "repair_attempt": 0,
                    "last_failing_keys_json": "[]",
                },
            )
        return self._get_contract(contract_id)

    def export_git_projection(
        self,
        *,
        output_dir: str | Path,
        actor_role: str,
    ) -> dict[str, str]:
        self._require_integrator(actor_role)
        output_root = Path(output_dir)
        snapshot_dir = output_root / "coordination-memory" / "snapshots"
        events_dir = output_root / "coordination-memory" / "events"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        events_dir.mkdir(parents=True, exist_ok=True)

        snapshot = self.get_snapshot()
        accepted_state_path = snapshot_dir / "accepted-state.json"
        accepted_state_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        accepted_events_path = events_dir / "accepted-events.md"
        accepted_events_path.write_text(
            self._accepted_events_markdown(snapshot["accepted_events"]),
            encoding="utf-8",
        )
        return {
            "accepted_state_path": str(accepted_state_path),
            "accepted_events_path": str(accepted_events_path),
        }

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists workspaces (
                    workspace_id text primary key,
                    name text not null,
                    repo_root text,
                    default_branch text,
                    status text not null,
                    metadata_json text not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists actors (
                    actor_id text primary key,
                    actor_kind text not null,
                    display_name text not null,
                    provider text not null,
                    status text not null,
                    capabilities_json text not null,
                    last_seen_at text,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists teams (
                    team_id text primary key,
                    workspace_id text not null,
                    name text not null,
                    phase_key text,
                    owner_actor_id text,
                    status text not null,
                    settings_json text not null,
                    created_at text not null,
                    updated_at text not null,
                    foreign key (workspace_id) references workspaces(workspace_id),
                    foreign key (owner_actor_id) references actors(actor_id)
                )
                """
            )
            conn.execute(
                """
                create table if not exists assignments (
                    assignment_id text primary key,
                    workspace_id text not null,
                    team_id text not null,
                    title text not null,
                    status text not null,
                    priority integer not null,
                    created_by_actor_id text,
                    active_run_id text,
                    revision integer not null,
                    allowed_paths_json text not null,
                    acceptance_criteria_json text not null,
                    metadata_json text not null,
                    created_at text not null,
                    updated_at text not null,
                    completed_at text,
                    claimed_by text,
                    lease_expires_at text,
                    foreign key (workspace_id) references workspaces(workspace_id),
                    foreign key (team_id) references teams(team_id),
                    foreign key (created_by_actor_id) references actors(actor_id)
                )
                """
            )
            conn.execute(
                """
                create table if not exists runs (
                    run_id text primary key,
                    assignment_id text not null,
                    team_id text not null,
                    actor_id text not null,
                    attempt integer not null,
                    status text not null,
                    lease_expires_at text,
                    heartbeat_at text,
                    started_at text,
                    ended_at text,
                    updated_at text not null,
                    session_kind text,
                    session_ref text,
                    interactive_url text,
                    worktree_path text,
                    branch text,
                    base_commit text,
                    head_commit text,
                    resume_of_run_id text,
                    metadata_json text not null,
                    foreign key (assignment_id) references assignments(assignment_id),
                    foreign key (team_id) references teams(team_id),
                    foreign key (actor_id) references actors(actor_id),
                    foreign key (resume_of_run_id) references runs(run_id)
                )
                """
            )
            conn.execute(
                """
                create table if not exists events (
                    sequence integer primary key autoincrement,
                    event_id text not null unique,
                    workspace_id text not null,
                    team_id text not null,
                    assignment_id text,
                    run_id text,
                    event_type text not null,
                    status text not null,
                    actor_id text not null,
                    actor_role text not null,
                    payload_json text not null,
                    reviewed_event_id text,
                    assignment_revision integer,
                    safety_label text not null,
                    created_at text not null,
                    foreign key (workspace_id) references workspaces(workspace_id),
                    foreign key (team_id) references teams(team_id),
                    foreign key (assignment_id) references assignments(assignment_id),
                    foreign key (run_id) references runs(run_id),
                    foreign key (actor_id) references actors(actor_id),
                    foreign key (reviewed_event_id) references events(event_id)
                )
                """
            )
            conn.execute(
                """
                create table if not exists acceptance_contracts (
                    contract_id text primary key,
                    workspace_id text not null,
                    team_id text not null,
                    title text not null,
                    goal_statement text not null,
                    status text not null,
                    revision integer not null,
                    created_by_actor_id text,
                    author_actor_id text,
                    acceptor_actor_id text,
                    max_repair_attempts integer not null,
                    repair_attempt integer not null,
                    last_failing_keys_json text not null,
                    metadata_json text not null,
                    created_at text not null,
                    updated_at text not null,
                    sealed_at text,
                    decided_at text
                )
                """
            )
            conn.execute(
                """
                create table if not exists contract_invariants (
                    invariant_id text primary key,
                    contract_id text not null,
                    key text not null,
                    description text not null,
                    probe_kind text not null,
                    probe_spec_json text not null,
                    required integer not null,
                    is_negative integer not null,
                    is_second_instance integer not null,
                    created_at text not null,
                    updated_at text not null,
                    unique (contract_id, key),
                    foreign key (contract_id) references acceptance_contracts(contract_id)
                )
                """
            )
            conn.execute(
                """
                create table if not exists contract_verifications (
                    verification_id text primary key,
                    invariant_id text not null,
                    contract_id text not null,
                    run_id text,
                    reporter_actor_id text not null,
                    reporter_role text not null,
                    outcome text not null,
                    evidence_json text not null,
                    repair_attempt integer not null,
                    created_at text not null,
                    foreign key (invariant_id) references contract_invariants(invariant_id),
                    foreign key (contract_id) references acceptance_contracts(contract_id)
                )
                """
            )
            conn.execute(
                """
                create table if not exists contract_deviations (
                    deviation_id text primary key,
                    contract_id text not null,
                    title text not null,
                    description text not null,
                    disposition text not null,
                    status text not null,
                    raised_by_actor_id text not null,
                    raised_role text not null,
                    disposed_by_actor_id text,
                    waiver_event_id text,
                    created_at text not null,
                    updated_at text not null,
                    foreign key (contract_id) references acceptance_contracts(contract_id)
                )
                """
            )
            self._ensure_core_columns(conn)
            conn.execute(
                """
                create index if not exists idx_events_team_created
                on events(team_id, created_at)
                """
            )
            conn.execute(
                """
                create index if not exists idx_events_assignment_sequence
                on events(assignment_id, sequence)
                """
            )
            conn.execute(
                """
                create index if not exists idx_events_run_sequence
                on events(run_id, sequence)
                """
            )
            conn.execute(
                """
                create index if not exists idx_events_type_status_created
                on events(event_type, status, created_at)
                """
            )
            conn.execute(
                """
                create index if not exists idx_events_reviewed
                on events(reviewed_event_id)
                """
            )
            self._ensure_default_records(conn)

    def _ensure_core_columns(self, conn: sqlite3.Connection) -> None:
        for column, definition in {
            "workspace_id": "text not null default 'default'",
            "team_id": "text not null default 'default'",
            "priority": "integer not null default 0",
            "created_by_actor_id": "text",
            "active_run_id": "text",
            "allowed_paths_json": "text not null default '[]'",
            "acceptance_criteria_json": "text not null default '[]'",
            "completed_at": "text",
            "contract_id": "text",
        }.items():
            self._ensure_column(conn, "assignments", column, definition)
        for column, definition in {
            "workspace_id": "text not null default 'default'",
            "team_id": "text not null default 'default'",
            "run_id": "text",
            "safety_label": "text not null default 'internal'",
        }.items():
            self._ensure_column(conn, "events", column, definition)

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"alter table {table} add column {column} {definition}")

    def _ensure_default_records(self, conn: sqlite3.Connection) -> None:
        now = self._now()
        conn.execute(
            """
            insert or ignore into workspaces (
                workspace_id, name, repo_root, default_branch, status,
                metadata_json, created_at, updated_at
            )
            values ('default', 'Default Workspace', null, null, 'active', ?, ?, ?)
            """,
            (self._json({}), now, now),
        )
        conn.execute(
            """
            insert or ignore into actors (
                actor_id, actor_kind, display_name, provider, status,
                capabilities_json, last_seen_at, created_at, updated_at
            )
            values (
                'integrator', 'integrator', 'Integrator', 'local', 'active',
                ?, ?, ?, ?
            )
            """,
            (self._json({}), now, now, now),
        )
        conn.execute(
            """
            insert or ignore into teams (
                team_id, workspace_id, name, phase_key, owner_actor_id, status,
                settings_json, created_at, updated_at
            )
            values (
                'default', 'default', 'Default Team', null, 'integrator', 'active',
                ?, ?, ?
            )
            """,
            (self._json({"heartbeat_stale_seconds": 3600}), now, now),
        )

    def _ensure_actor_record(
        self,
        conn: sqlite3.Connection,
        actor_id: str,
        actor_role: str,
    ) -> None:
        actor_kind = {
            "integrator": "integrator",
            "agent": "coding_agent",
            "human": "human",
            "supervisor": "supervisor",
            "system": "script",
        }.get(actor_role, "script")
        now = self._now()
        conn.execute(
            """
            insert or ignore into actors (
                actor_id, actor_kind, display_name, provider, status,
                capabilities_json, last_seen_at, created_at, updated_at
            )
            values (?, ?, ?, 'local', 'active', ?, ?, ?, ?)
            """,
            (actor_id, actor_kind, actor_id, self._json({}), now, now, now),
        )

    def _ensure_workspace_record(
        self,
        conn: sqlite3.Connection,
        workspace_id: str,
    ) -> None:
        now = self._now()
        conn.execute(
            """
            insert or ignore into workspaces (
                workspace_id, name, repo_root, default_branch, status,
                metadata_json, created_at, updated_at
            )
            values (?, ?, null, null, 'active', ?, ?, ?)
            """,
            (workspace_id, workspace_id, self._json({}), now, now),
        )

    def _connect(self) -> sqlite3.Connection:
        if self._readonly:
            db_uri = f"file:{quote(str(self.db_path), safe='/:')}?mode=ro"
            conn = sqlite3.connect(db_uri, uri=True)
            conn.execute("pragma query_only = on")
        else:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _require_current_assignment(
        self,
        conn: sqlite3.Connection,
        assignment_id: str,
        base_revision: int,
    ) -> dict[str, Any]:
        row = conn.execute(
            "select * from assignments where assignment_id = ?",
            (assignment_id,),
        ).fetchone()
        if row is None:
            raise ValidationError(f"assignment not found: {assignment_id}")
        assignment = self._assignment_from_row(row)
        if assignment["revision"] != base_revision:
            raise StaleRevisionError(
                "stale base_revision for "
                f"{assignment_id}: expected {assignment['revision']}, got {base_revision}"
            )
        return assignment

    def _get_actor(self, actor_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from actors where actor_id = ?",
                (actor_id,),
            ).fetchone()
        if row is None:
            raise ValidationError(f"actor not found: {actor_id}")
        return self._actor_from_row(row)

    def _get_team(self, team_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from teams where team_id = ?",
                (team_id,),
            ).fetchone()
        if row is None:
            raise ValidationError(f"team not found: {team_id}")
        return self._team_from_row(row)

    def _get_workspace(self, workspace_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from workspaces where workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            raise ValidationError(f"workspace not found: {workspace_id}")
        return {
            "workspace_id": row["workspace_id"],
            "name": row["name"],
            "repo_root": row["repo_root"],
            "default_branch": row["default_branch"],
            "status": row["status"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _get_assignment(self, assignment_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from assignments where assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        if row is None:
            raise ValidationError(f"assignment not found: {assignment_id}")
        return self._assignment_from_row(row)

    def _require_assignment_accepts_writes(
        self,
        assignment: dict[str, Any],
    ) -> None:
        if assignment["status"] in {
            "accepted",
            "rejected",
            "cancelled",
            "blocked",
            "needs_fix",
        }:
            raise ValidationError(
                "assignment does not accept append/handoff writes: "
                f"{assignment['assignment_id']} is {assignment['status']}"
            )

    def _require_agent_owns_assignment_active_run(
        self,
        conn: sqlite3.Connection,
        *,
        assignment: dict[str, Any],
        actor_id: str,
        actor_role: str,
    ) -> None:
        active_run_id = assignment["active_run_id"]
        if actor_role != "agent" or active_run_id is None:
            return
        row = conn.execute(
            "select actor_id from runs where run_id = ?",
            (active_run_id,),
        ).fetchone()
        if row is None:
            raise ValidationError(f"active run not found: {active_run_id}")
        if row["actor_id"] != actor_id:
            raise AuthorizationError(
                f"agent does not own active run: {active_run_id} belongs to {row['actor_id']}"
            )

    def _require_agent_owns_run(
        self,
        run: dict[str, Any],
        actor_id: str,
        actor_role: str,
    ) -> None:
        if actor_role == "agent" and run["actor_id"] != actor_id:
            raise AuthorizationError(
                f"agent does not own run: {run['run_id']} belongs to {run['actor_id']}"
            )

    def _require_active_mutable_run(
        self,
        conn: sqlite3.Connection,
        run_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        run_row = conn.execute(
            "select * from runs where run_id = ?",
            (run_id,),
        ).fetchone()
        if run_row is None:
            raise ValidationError(f"run not found: {run_id}")
        run = self._run_from_row(run_row)
        assignment_row = conn.execute(
            "select * from assignments where assignment_id = ?",
            (run["assignment_id"],),
        ).fetchone()
        if assignment_row is None:
            raise ValidationError(f"assignment not found: {run['assignment_id']}")
        assignment = self._assignment_from_row(assignment_row)
        if assignment["active_run_id"] != run_id:
            raise ValidationError(f"run is not active for assignment: {run_id}")
        if assignment["status"] in {
            "accepted",
            "rejected",
            "needs_fix",
            "cancelled",
            "blocked",
        }:
            raise ValidationError(f"assignment is not mutable: {run_id}")
        if (
            run["status"]
            in {
                "superseded",
                "failed",
                "cancelled",
                "completed_gate_passed",
                "completed_gate_failed",
            }
            or run["ended_at"] is not None
        ):
            raise ValidationError(f"run is not mutable: {run_id}")
        return run, assignment

    def _validate_intervention_review_target(
        self,
        conn: sqlite3.Connection,
        *,
        run: dict[str, Any],
        assignment: dict[str, Any],
        reviewed_event_id: str | None,
    ) -> None:
        if reviewed_event_id is None:
            raise ValidationError("reviewed_event_id is required for intervention response")
        if run["status"] not in {"awaiting_human", "awaiting_approval"}:
            raise ValidationError(f"run is not awaiting intervention response: {run['run_id']}")
        target_row = conn.execute(
            "select * from events where event_id = ?",
            (reviewed_event_id,),
        ).fetchone()
        if target_row is None:
            raise ValidationError(f"reviewed event not found: {reviewed_event_id}")
        target = self._event_from_row(target_row)
        if target["event_type"] != "intervention_requested":
            raise ValidationError(
                f"reviewed event is not an intervention request: {reviewed_event_id}"
            )
        if (
            target["run_id"] != run["run_id"]
            or target["assignment_id"] != assignment["assignment_id"]
        ):
            raise ValidationError(f"reviewed event does not match run: {reviewed_event_id}")

    def _insert_run_event(
        self,
        conn: sqlite3.Connection,
        *,
        run: dict[str, Any],
        assignment: dict[str, Any],
        event_type: str,
        actor_id: str,
        actor_role: str,
        payload: dict[str, Any],
        reviewed_event_id: str | None,
        created_at: str,
    ) -> dict[str, Any]:
        return self._insert_event(
            conn,
            assignment_id=assignment["assignment_id"],
            event_type=event_type,
            status="observed",
            actor_id=actor_id,
            actor_role=actor_role,
            payload=payload,
            reviewed_event_id=reviewed_event_id,
            assignment_revision=assignment["revision"],
            created_at=created_at,
            run_id=run["run_id"],
        )

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        *,
        assignment_id: str,
        event_type: str,
        status: str,
        actor_id: str,
        actor_role: str,
        payload: dict[str, Any],
        reviewed_event_id: str | None,
        assignment_revision: int,
        created_at: str,
        run_id: str | None = None,
        safety_label: str = "internal",
    ) -> dict[str, Any]:
        self._require_event_status(status)
        event_id = f"evt_{uuid.uuid4().hex}"
        self._ensure_actor_record(conn, actor_id, actor_role)
        assignment = conn.execute(
            """
            select workspace_id, team_id
            from assignments
            where assignment_id = ?
            """,
            (assignment_id,),
        ).fetchone()
        if assignment is None:
            raise ValidationError(f"assignment not found: {assignment_id}")
        conn.execute(
            """
            insert into events (
                event_id, workspace_id, team_id, assignment_id, run_id, event_type,
                status, actor_id, actor_role, payload_json, reviewed_event_id,
                assignment_revision, safety_label, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                assignment["workspace_id"],
                assignment["team_id"],
                assignment_id,
                run_id,
                event_type,
                status,
                actor_id,
                actor_role,
                self._json(payload),
                reviewed_event_id,
                assignment_revision,
                safety_label,
                created_at,
            ),
        )
        row = conn.execute(
            "select * from events where event_id = ?",
            (event_id,),
        ).fetchone()
        return self._event_from_row(row)

    def _accepted_events(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select *
                from events
                where event_type = 'integrator_review'
                  and status = 'integrator_accepted'
                order by created_at, sequence
                """
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _workspace_map(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select *
                from workspaces
                order by workspace_id
                """
            ).fetchall()
        return {row["workspace_id"]: self._workspace_from_row(row) for row in rows}

    def _team_map(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select *
                from teams
                order by team_id
                """
            ).fetchall()
        return {row["team_id"]: self._team_from_row(row) for row in rows}

    def _actor_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "actor_id": row["actor_id"],
            "actor_kind": row["actor_kind"],
            "display_name": row["display_name"],
            "provider": row["provider"],
            "status": row["status"],
            "capabilities": json.loads(row["capabilities_json"]),
            "last_seen_at": row["last_seen_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _workspace_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "workspace_id": row["workspace_id"],
            "name": row["name"],
            "repo_root": row["repo_root"],
            "default_branch": row["default_branch"],
            "status": row["status"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _inferred_workspace(
        self,
        workspace_id: str,
        *,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        if workspace_id == UNASSIGNED_WORKSPACE_ID:
            return {
                "workspace_id": workspace_id,
                "name": "Unassigned teams",
                "repo_root": None,
                "default_branch": None,
                "status": "active",
                "metadata": {"virtual": True},
                "created_at": created_at,
                "updated_at": updated_at,
            }
        return {
            "workspace_id": workspace_id,
            "name": workspace_id,
            "repo_root": None,
            "default_branch": None,
            "status": "active",
            "metadata": {},
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def _display_workspace_id(self, workspace_id: str | None) -> str:
        return workspace_id or UNASSIGNED_WORKSPACE_ID

    def _storage_workspace_id(self, workspace_id: str) -> str:
        if workspace_id == UNASSIGNED_WORKSPACE_ID:
            return ""
        return workspace_id

    def _team_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "team_id": row["team_id"],
            "workspace_id": row["workspace_id"],
            "name": row["name"],
            "phase_key": row["phase_key"],
            "owner_actor_id": row["owner_actor_id"],
            "status": row["status"],
            "settings": json.loads(row["settings_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _inferred_team(self, workspace_id: str, team_id: str) -> dict[str, Any]:
        return {
            "team_id": team_id,
            "workspace_id": workspace_id,
            "name": team_id,
            "phase_key": None,
            "owner_actor_id": None,
            "status": "inferred",
            "settings": {},
            "created_at": None,
            "updated_at": None,
        }

    def _team_with_assignment_counts(
        self,
        team: dict[str, Any],
        assignment_counts: dict[str, int],
    ) -> dict[str, Any]:
        enriched = dict(team)
        enriched["assignment_counts"] = dict(assignment_counts)
        enriched["assignment_total"] = sum(assignment_counts.values())
        return enriched

    def _assignment_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "assignment_id": row["assignment_id"],
            "workspace_id": row["workspace_id"],
            "team_id": row["team_id"],
            "title": row["title"],
            "status": row["status"],
            "priority": row["priority"],
            "created_by_actor_id": row["created_by_actor_id"],
            "active_run_id": row["active_run_id"],
            "revision": row["revision"],
            "allowed_paths": json.loads(row["allowed_paths_json"]),
            "acceptance_criteria": json.loads(row["acceptance_criteria_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "claimed_by": row["claimed_by"],
            "lease_expires_at": row["lease_expires_at"],
            "contract_id": row["contract_id"],
        }

    def _run_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "assignment_id": row["assignment_id"],
            "team_id": row["team_id"],
            "actor_id": row["actor_id"],
            "attempt": row["attempt"],
            "status": row["status"],
            "lease_expires_at": row["lease_expires_at"],
            "heartbeat_at": row["heartbeat_at"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "updated_at": row["updated_at"],
            "session_kind": row["session_kind"],
            "session_ref": row["session_ref"],
            "interactive_url": row["interactive_url"],
            "worktree_path": row["worktree_path"],
            "branch": row["branch"],
            "base_commit": row["base_commit"],
            "head_commit": row["head_commit"],
            "resume_of_run_id": row["resume_of_run_id"],
            "metadata": json.loads(row["metadata_json"]),
        }

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "sequence": row["sequence"],
            "event_id": row["event_id"],
            "workspace_id": row["workspace_id"],
            "team_id": row["team_id"],
            "assignment_id": row["assignment_id"],
            "run_id": row["run_id"],
            "event_type": row["event_type"],
            "status": row["status"],
            "actor_id": row["actor_id"],
            "actor_role": row["actor_role"],
            "payload": json.loads(row["payload_json"]),
            "reviewed_event_id": row["reviewed_event_id"],
            "assignment_revision": row["assignment_revision"],
            "safety_label": row["safety_label"],
            "created_at": row["created_at"],
        }

    def _accepted_events_markdown(self, accepted_events: list[dict[str, Any]]) -> str:
        lines = [
            "# Accepted Coordination Events",
            "",
            "This file is generated by `export_git_projection` and is not the live "
            "coordination store.",
            "",
        ]
        if not accepted_events:
            lines.append("No Integrator-accepted events.")
            lines.append("")
            return "\n".join(lines)
        for event in accepted_events:
            summary = event["payload"].get("summary", "")
            lines.extend(
                [
                    f"## {event['assignment_id']}",
                    "",
                    f"- Event: `{event['event_id']}`",
                    f"- Status: `{event['status']}`",
                    f"- Actor: `{event['actor_id']}`",
                    f"- Summary: {summary}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _require_integrator(self, actor_role: str) -> None:
        if actor_role != "integrator":
            raise AuthorizationError("operation requires actor_role=integrator")

    def _require_known_role(self, actor_role: str) -> None:
        if actor_role not in {"agent", "integrator", "human"}:
            raise AuthorizationError(f"unknown actor_role: {actor_role}")

    def _require_event_status(self, status: str) -> None:
        if status not in EVENT_STATUSES:
            raise ValidationError(f"invalid event status: {status}")

    def _require_claim_available(
        self,
        assignment: dict[str, Any],
        actor_id: str,
    ) -> None:
        claimed_by = assignment["claimed_by"]
        lease_expires_at = assignment["lease_expires_at"]
        if not claimed_by or claimed_by == actor_id or not lease_expires_at:
            return
        if self._parse_timestamp(lease_expires_at) <= datetime.now(UTC):
            return
        raise LeaseConflictError(
            f"assignment is leased by another actor until {lease_expires_at}: {claimed_by}"
        )

    def _parse_timestamp(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _merge_json_object(
        self,
        current: dict[str, Any],
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(current)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._merge_json_object(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _normalize_assignment_metadata(
        self,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        normalized = dict(metadata or {})
        session_bind = normalized.get("session_bind")
        if session_bind is not None and not isinstance(session_bind, dict):
            raise ValidationError("metadata.session_bind must be a JSON object")

        bind = dict(session_bind or {})
        actor_hint = normalized.get("assigned_actor_hint")
        if not isinstance(actor_hint, str):
            actor_hint = None
        actor_hint = actor_hint.strip() if actor_hint else None

        if session_bind is None and actor_hint:
            bind["target_actor_id"] = actor_hint
            bind["status"] = "pending"
            bind["session_kind"] = "codex_thread"
        elif session_bind is not None:
            if "target_actor_id" not in bind and actor_hint:
                bind["target_actor_id"] = actor_hint
            bind.setdefault("status", "pending")
            bind.setdefault("session_kind", "codex_thread")

        if bind:
            normalized["session_bind"] = bind
        return normalized

    def _json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()
