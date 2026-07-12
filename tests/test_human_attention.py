from copy import deepcopy
from datetime import datetime

import pytest

from coordination_memory_mcp import human_attention

MANDATORY_CHECKPOINT_TRIGGERS = human_attention.MANDATORY_CHECKPOINT_TRIGGERS
TERMINAL_ASSIGNMENT_STATUSES = human_attention.TERMINAL_ASSIGNMENT_STATUSES
normalize_human_brief = human_attention.normalize_human_brief


def valid_brief() -> dict[str, object]:
    return {
        "schema_version": 1,
        "current_goal": "Ship attention projection",
        "current_stage": "implementing",
        "recent_progress": ["Added contract tests"],
        "decisions_and_risks": [],
        "human_intervention": {"needed": False, "blocking": False},
        "next_steps": ["Implement store projection"],
        "context_refs": ["docs/design.docx"],
    }


def valid_attention() -> dict[str, object]:
    return {
        "level": "yellow",
        "target": "human",
        "blocking": False,
        "dedupe_key": "retry-budget",
        "reason_code": "retry_risk",
        "why_now": "Retry budget is nearly exhausted",
        "recommended_action": "Review the fallback",
        "source_event_ids": ["evt_1"],
    }


def test_normalize_human_brief_requires_fixed_human_fields() -> None:
    brief = normalize_human_brief(
        {
            "schema_version": 1,
            "current_goal": "Ship attention projection",
            "current_stage": "implementing",
            "recent_progress": ["Added contract tests"],
            "decisions_and_risks": [],
            "human_intervention": {"needed": False, "blocking": False},
            "next_steps": ["Implement store projection"],
            "context_refs": [
                "docs/design/comem-human-attention-and-status-brief-system-design.docx"
            ],
        }
    )

    assert brief["schema_version"] == 1
    assert brief["current_stage"] == "implementing"
    assert brief["recent_progress"] == ["Added contract tests"]


def test_domain_status_constants_have_the_canonical_values() -> None:
    assert (
        frozenset(
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
        == MANDATORY_CHECKPOINT_TRIGGERS
    )
    assert (
        frozenset({"accepted", "rejected", "cancelled", "superseded", "blocked"})
        == TERMINAL_ASSIGNMENT_STATUSES
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("current_goal", "   "),
        ("current_stage", "planning"),
        ("recent_progress", "not-a-list"),
        ("recent_progress", [""]),
        ("decisions_and_risks", ["not-an-object"]),
        ("human_intervention", {"needed": False}),
        ("human_intervention", {"needed": 0, "blocking": False}),
        ("next_steps", []),
        ("next_steps", ["  "]),
        ("context_refs", [1]),
    ],
)
def test_normalize_human_brief_rejects_invalid_field_values(field: str, value: object) -> None:
    brief = valid_brief()
    brief[field] = value

    with pytest.raises(ValueError):
        normalize_human_brief(brief)


def test_normalize_human_brief_requires_every_canonical_field() -> None:
    brief = valid_brief()
    del brief["current_goal"]

    with pytest.raises(ValueError, match="brief missing required fields: current_goal"):
        normalize_human_brief(brief)


def test_normalize_human_brief_rejects_non_object_input() -> None:
    with pytest.raises(ValueError, match="brief must be a JSON object"):
        normalize_human_brief([])  # type: ignore[arg-type]


def test_normalize_human_brief_preserves_extra_fields_in_an_independent_copy() -> None:
    brief = valid_brief()
    brief["extension"] = {"labels": ["domain"]}
    original = deepcopy(brief)

    normalized = normalize_human_brief(brief)
    normalized["recent_progress"].append("Mutated output")  # type: ignore[union-attr]
    normalized["extension"]["labels"].append("mutated")  # type: ignore[index,union-attr]

    assert brief == original


def test_default_attention_timing_constants_have_canonical_values() -> None:
    assert human_attention.DEFAULT_FRESHNESS_WINDOW_MINUTES == 30
    assert human_attention.DEFAULT_YELLOW_DIGEST_MINUTES == 60


def test_attention_green_closes_same_issue_without_blocking() -> None:
    item = human_attention.normalize_attention_item(
        {
            "level": "green",
            "target": "human",
            "blocking": False,
            "dedupe_key": "retry-budget",
            "reason_code": "risk_resolved",
            "why_now": "Fallback succeeded",
            "recommended_action": "None",
            "source_event_ids": [],
        }
    )

    assert item["level"] == "green"


def test_attention_rejects_red_from_nonblocking_raise_path() -> None:
    with pytest.raises(ValueError, match="yellow or green"):
        human_attention.normalize_attention_item({**valid_attention(), "level": "red"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("level", []),
        ("target", "operator"),
        ("target", []),
        ("blocking", True),
        ("blocking", 0),
        ("dedupe_key", ""),
        ("reason_code", "  "),
        ("why_now", 1),
        ("recommended_action", None),
        ("source_event_ids", "evt_1"),
        ("source_event_ids", [""]),
    ],
)
def test_normalize_attention_item_rejects_invalid_fields(field: str, value: object) -> None:
    item = valid_attention()
    item[field] = value

    with pytest.raises(ValueError):
        human_attention.normalize_attention_item(item)


@pytest.mark.parametrize("target", ["human", "integrator", "agent"])
def test_normalize_attention_item_accepts_supported_targets(target: str) -> None:
    item = valid_attention()
    item["target"] = target

    assert human_attention.normalize_attention_item(item)["target"] == target


def test_normalize_attention_item_requires_every_canonical_field() -> None:
    item = valid_attention()
    del item["source_event_ids"]

    with pytest.raises(
        ValueError, match="attention item missing required fields: source_event_ids"
    ):
        human_attention.normalize_attention_item(item)


def test_normalize_attention_item_rejects_non_object_input() -> None:
    with pytest.raises(ValueError, match="attention item must be a JSON object"):
        human_attention.normalize_attention_item([])  # type: ignore[arg-type]


def test_normalize_attention_item_preserves_extra_fields_in_independent_copy() -> None:
    item = valid_attention()
    item["extension"] = {"labels": ["attention"]}
    original = deepcopy(item)

    normalized = human_attention.normalize_attention_item(item)
    normalized["source_event_ids"].append("evt_2")  # type: ignore[union-attr]
    normalized["extension"]["labels"].append("mutated")  # type: ignore[index,union-attr]

    assert item == original


def test_brief_is_stale_only_when_newer_events_exist_past_window() -> None:
    assert (
        human_attention.brief_freshness(
            updated_at="2026-07-12T00:00:00+00:00",
            source_event_sequence=4,
            latest_event_sequence=5,
            now=datetime.fromisoformat("2026-07-12T00:31:00+00:00"),
            freshness_window_minutes=30,
        )
        == "stale"
    )


def test_brief_stays_fresh_without_newer_events_regardless_of_age() -> None:
    assert (
        human_attention.brief_freshness(
            updated_at="2026-07-12T00:00:00+00:00",
            source_event_sequence=5,
            latest_event_sequence=5,
            now=datetime.fromisoformat("2026-07-13T00:00:00+00:00"),
            freshness_window_minutes=30,
        )
        == "fresh"
    )


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime.fromisoformat("2026-07-12T00:30:00+00:00"), "fresh"),
        (datetime.fromisoformat("2026-07-12T00:30:00.000001+00:00"), "stale"),
        (datetime.fromisoformat("2026-07-11T23:59:00+00:00"), "fresh"),
    ],
)
def test_brief_freshness_honors_exact_window_and_future_timestamp(
    now: datetime, expected: str
) -> None:
    assert (
        human_attention.brief_freshness(
            updated_at="2026-07-12T00:00:00+00:00",
            source_event_sequence=4,
            latest_event_sequence=5,
            now=now,
            freshness_window_minutes=30,
        )
        == expected
    )


@pytest.mark.parametrize("window", [True, 0, -1, 1.5])
def test_brief_freshness_rejects_invalid_window(window: object) -> None:
    with pytest.raises(ValueError):
        human_attention.brief_freshness(
            updated_at="2026-07-12T00:00:00+00:00",
            source_event_sequence=4,
            latest_event_sequence=5,
            now=datetime.fromisoformat("2026-07-12T00:01:00+00:00"),
            freshness_window_minutes=window,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("source_sequence", "latest_sequence"),
    [(True, 1), (-1, 1), (1.5, 2), (1, False), (1, -1), (1, 2.5)],
)
def test_brief_freshness_rejects_invalid_event_sequences(
    source_sequence: object, latest_sequence: object
) -> None:
    with pytest.raises(ValueError):
        human_attention.brief_freshness(
            updated_at="2026-07-12T00:00:00+00:00",
            source_event_sequence=source_sequence,  # type: ignore[arg-type]
            latest_event_sequence=latest_sequence,  # type: ignore[arg-type]
            now=datetime.fromisoformat("2026-07-12T00:01:00+00:00"),
            freshness_window_minutes=30,
        )


@pytest.mark.parametrize("updated_at", ["not-a-date", "2026-07-12T00:00:00"])
def test_brief_freshness_rejects_invalid_or_naive_updated_at(updated_at: str) -> None:
    with pytest.raises(ValueError):
        human_attention.brief_freshness(
            updated_at=updated_at,
            source_event_sequence=4,
            latest_event_sequence=5,
            now=datetime.fromisoformat("2026-07-12T00:01:00+00:00"),
            freshness_window_minutes=30,
        )


def test_brief_freshness_rejects_naive_now() -> None:
    with pytest.raises(ValueError):
        human_attention.brief_freshness(
            updated_at="2026-07-12T00:00:00+00:00",
            source_event_sequence=4,
            latest_event_sequence=5,
            now=datetime.fromisoformat("2026-07-12T00:01:00"),
            freshness_window_minutes=30,
        )
