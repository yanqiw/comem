from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

LoopCommandType = Literal[
    "start_assignment",
    "resume_assignment",
    "nudge_review",
    "interrupt_run",
    "refresh_capabilities",
]


@dataclass(frozen=True)
class LoopConfig:
    workspace_id: str | None = None
    team_id: str | None = None
    adapter: str = "fake"
    actor_prefix: str = "codex-worker"
    integrator_actor_id: str = "codex-integrator-loop"
    poll_interval: float = 10.0
    max_concurrent_runs: int = 1
    review_nudge_interval: float = 60.0
    dry_run: bool = False
    once: bool = False


@dataclass(frozen=True)
class LoopCommand:
    command_id: str
    command_type: LoopCommandType
    workspace_id: str
    team_id: str
    assignment_id: str | None
    assignment_revision: int | None
    run_id: str | None
    target_actor_id: str
    adapter_kind: str
    prompt_kind: str
    payload: dict[str, Any]


def sanitize_command_part(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_")


def build_command_id(
    *,
    command_type: LoopCommandType,
    assignment_id: str | None,
    assignment_revision: int | None = None,
    event_id: str | None = None,
    attempt: int = 1,
) -> str:
    target = sanitize_command_part(assignment_id or event_id or "none")
    if assignment_revision is not None:
        revision_part = f"rev{assignment_revision}"
    else:
        revision_part = sanitize_command_part(event_id or "no_event")
    return f"cmd_{command_type}_{target}_{revision_part}_attempt{attempt}"
