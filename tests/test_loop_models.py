from coordination_memory_mcp.loop_adapters import FakeCodexAdapter
from coordination_memory_mcp.loop_models import build_command_id


def test_build_command_id_is_stable_and_sanitized() -> None:
    assert (
        build_command_id(
            command_type="start_assignment",
            assignment_id="task.alpha",
            assignment_revision=7,
            attempt=1,
        )
        == "cmd_start_assignment_task_alpha_rev7_attempt1"
    )


def test_fake_codex_adapter_uses_deterministic_ids() -> None:
    adapter = FakeCodexAdapter()

    thread = adapter.start_thread(actor_id="codex-worker-1", assignment_id="task.alpha")
    turn_id = adapter.start_turn(
        thread_id=thread.thread_id,
        prompt="hello",
        client_user_message_id="cmd_start_assignment_task_alpha_rev7_attempt1",
    )

    assert thread.thread_id == "fake-thread-1"
    assert turn_id == "fake-turn-1"
    assert thread.active_turn_id == "fake-turn-1"
    assert thread.completed_turn_ids == ["fake-turn-1"]
    assert adapter.prompts["cmd_start_assignment_task_alpha_rev7_attempt1"] == "hello"


def test_fake_codex_adapter_can_resume_started_thread() -> None:
    adapter = FakeCodexAdapter()
    thread = adapter.start_thread(actor_id="codex-worker-1", assignment_id="task.alpha")

    assert adapter.resume_thread(thread_id=thread.thread_id) is thread
