from coordination_memory_mcp.loop_prompts import build_worker_prompt


def test_worker_prompt_contains_contract_fields() -> None:
    prompt = build_worker_prompt(
        actor_id="codex-worker-1",
        command_id="cmd_start_assignment_task_rev1_attempt1",
        plan_path="docs/superpowers/plans/2026-07-05-local-codex-loop.md",
        assignment={
            "assignment_id": "task",
            "workspace_id": "example-workspace",
            "allowed_paths": ["coordination-memory-mcp/**"],
            "acceptance_criteria": ["pytest passes"],
            "metadata": {
                "context_refs": [
                    {
                        "path": "docs/design/local-codex-loop-detailed-design.md",
                        "read": ["Data Contracts"],
                    }
                ]
            },
        },
    )

    assert "codex-worker-1" in prompt
    assert "task" in prompt
    assert "cmd_start_assignment_task_rev1_attempt1" in prompt
    assert "docs/design/local-codex-loop-detailed-design.md" in prompt
    assert "coordination-memory-mcp/**" in prompt
    assert "pytest passes" in prompt
    assert "Claim the assignment using the current base_revision" in prompt
    assert "Do not accept your own work." in prompt
