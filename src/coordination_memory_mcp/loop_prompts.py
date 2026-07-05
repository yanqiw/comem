from __future__ import annotations

from typing import Any


def _format_context_refs(metadata: dict[str, Any]) -> str:
    refs = metadata.get("context_refs") or []
    if not refs:
        return (
            "No context_refs were provided. "
            "Read the nearest AGENTS.md and README.md before changing files."
        )
    lines: list[str] = []
    for index, ref in enumerate(refs, start=1):
        path = ref.get("path", "")
        sections = ref.get("read") or []
        if sections:
            lines.append(f"{index}. {path} - sections: {', '.join(sections)}")
        else:
            lines.append(f"{index}. {path}")
    return "\n".join(lines)


def build_worker_prompt(
    *,
    actor_id: str,
    assignment: dict[str, Any],
    command_id: str,
    plan_path: str,
) -> str:
    allowed_paths = assignment.get("allowed_paths") or []
    acceptance = assignment.get("acceptance_criteria") or []
    metadata = assignment.get("metadata") or {}
    return "\n".join(
        [
            f"You are Codex worker actor {actor_id}.",
            (
                f"Your assignment is {assignment['assignment_id']} "
                f"in workspace {assignment['workspace_id']}."
            ),
            f"The loop command id is {command_id}.",
            "",
            "Read context in this order:",
            _format_context_refs(metadata),
            (
                f"{len(metadata.get('context_refs') or []) + 1}. "
                f"{plan_path} - section matching this assignment."
            ),
            "",
            "Use Coordination Memory:",
            f"- Register actor {actor_id} if needed.",
            "- Confirm assignment detail and current revision before writing.",
            (
                "- Claim the assignment using the current base_revision "
                "if it is not already claimed by you."
            ),
            "- Heartbeat while working.",
            "- Append evidence for meaningful progress.",
            "- Submit a handoff when complete.",
            "- Do not accept your own work.",
            "",
            "Allowed paths:",
            *(f"- {path}" for path in allowed_paths),
            "",
            "Acceptance criteria:",
            *(f"- {criterion}" for criterion in acceptance),
        ]
    )


def build_review_prompt(
    *,
    actor_id: str,
    workspace_id: str,
    team_id: str,
    pending_events: list[dict[str, Any]],
) -> str:
    event_lines = [
        f"- {event['event_id']} for assignment {event['assignment_id']} status {event['status']}"
        for event in pending_events
    ]
    return "\n".join(
        [
            f"You are Codex integrator actor {actor_id}.",
            f"Review pending handoffs for workspace {workspace_id}, team {team_id}.",
            "",
            "Pending review events:",
            *event_lines,
            "",
            "For each event, inspect assignment detail and choose exactly one action:",
            "- accept_event",
            "- reject_event",
            "- review_event with needs_fix",
            "- create follow-up assignment",
            "- request human intervention",
            "",
            (
                "Do not approve deployment, push, Secret changes, or live-cluster "
                "changes without explicit human authorization."
            ),
        ]
    )
