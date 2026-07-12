from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

DEFAULT_FRESHNESS_WINDOW_MINUTES = 30
DEFAULT_YELLOW_DIGEST_MINUTES = 60

MANDATORY_CHECKPOINT_TRIGGERS = frozenset(
    {
        "phase_changed",
        "milestone_completed",
        "plan_changed",
        "decision_made",
        "risk_changed",
        "intervention_requested",
        "handoff",
        "run_finished",
    }
)
TERMINAL_ASSIGNMENT_STATUSES = frozenset(
    {"accepted", "rejected", "cancelled", "superseded", "blocked"}
)
SUPPORTED_BRIEF_STAGES = frozenset(
    {"investigating", "implementing", "verifying", "waiting", "handing_off", "completed"}
)

_REQUIRED_BRIEF_FIELDS = {
    "schema_version",
    "current_goal",
    "current_stage",
    "recent_progress",
    "decisions_and_risks",
    "human_intervention",
    "next_steps",
    "context_refs",
}
_REQUIRED_ATTENTION_FIELDS = {
    "level",
    "target",
    "blocking",
    "dedupe_key",
    "reason_code",
    "why_now",
    "recommended_action",
    "source_event_ids",
}


def _require_non_empty_string(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_string_list(value: object, *, field: str, non_empty: bool = False) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of non-empty strings")
    if non_empty and not value:
        raise ValueError(f"{field} must not be empty")
    for element in value:
        _require_non_empty_string(element, field=f"{field} item")


def normalize_human_brief(brief: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(brief, dict):
        raise ValueError("brief must be a JSON object")

    missing = sorted(_REQUIRED_BRIEF_FIELDS - brief.keys())
    if missing:
        raise ValueError(f"brief missing required fields: {', '.join(missing)}")

    schema_version = brief["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ValueError("schema_version must be integer 1")
    if schema_version != 1:
        raise ValueError("schema_version must be 1")

    _require_non_empty_string(brief["current_goal"], field="current_goal")
    _require_non_empty_string(brief["current_stage"], field="current_stage")
    if brief["current_stage"] not in SUPPORTED_BRIEF_STAGES:
        raise ValueError("current_stage is not supported")

    _require_string_list(brief["recent_progress"], field="recent_progress")
    _require_string_list(brief["next_steps"], field="next_steps", non_empty=True)
    _require_string_list(brief["context_refs"], field="context_refs")

    decisions_and_risks = brief["decisions_and_risks"]
    if not isinstance(decisions_and_risks, list) or not all(
        isinstance(entry, dict) for entry in decisions_and_risks
    ):
        raise ValueError("decisions_and_risks must be a list of objects")

    human_intervention = brief["human_intervention"]
    if not isinstance(human_intervention, dict):
        raise ValueError("human_intervention must be an object")
    for field in ("needed", "blocking"):
        if not isinstance(human_intervention.get(field), bool):
            raise ValueError(f"human_intervention.{field} must be a boolean")

    return deepcopy(brief)


def normalize_attention_item(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("attention item must be a JSON object")

    missing = sorted(_REQUIRED_ATTENTION_FIELDS - item.keys())
    if missing:
        raise ValueError(f"attention item missing required fields: {', '.join(missing)}")

    if not isinstance(item["level"], str) or item["level"] not in {"yellow", "green"}:
        raise ValueError("attention level must be yellow or green")
    if not isinstance(item["target"], str) or item["target"] not in {
        "human",
        "integrator",
        "agent",
    }:
        raise ValueError("attention target must be human, integrator, or agent")
    if item["blocking"] is not False:
        raise ValueError("attention blocking must be false")

    for field in ("dedupe_key", "reason_code", "why_now", "recommended_action"):
        _require_non_empty_string(item[field], field=field)
    _require_string_list(item["source_event_ids"], field="source_event_ids")

    return deepcopy(item)


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _parse_aware_datetime(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a valid ISO-8601 datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def brief_freshness(
    *,
    updated_at: str,
    source_event_sequence: int,
    latest_event_sequence: int,
    now: datetime,
    freshness_window_minutes: int,
) -> str:
    if (
        isinstance(freshness_window_minutes, bool)
        or not isinstance(freshness_window_minutes, int)
        or freshness_window_minutes <= 0
    ):
        raise ValueError("freshness_window_minutes must be a positive integer")
    _require_non_negative_integer(source_event_sequence, field="source_event_sequence")
    _require_non_negative_integer(latest_event_sequence, field="latest_event_sequence")

    updated = _parse_aware_datetime(updated_at, field="updated_at")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")

    if latest_event_sequence <= source_event_sequence:
        return "fresh"

    elapsed = max(now - updated, timedelta())
    if elapsed > timedelta(minutes=freshness_window_minutes):
        return "stale"
    return "fresh"
