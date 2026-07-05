import pytest

from coordination_memory_mcp.loop_adapters import (
    CodexAppServerAdapter,
    CodexAppServerUnavailable,
)


def test_codex_app_server_adapter_reports_unavailable_without_endpoint() -> None:
    adapter = CodexAppServerAdapter()

    capabilities = adapter.probe()

    assert capabilities.adapter_kind == "codex_app_server"
    assert capabilities.can_start_thread is False
    assert capabilities.can_resume_thread is False
    assert capabilities.can_start_turn is False
    assert capabilities.can_steer_turn is False
    assert capabilities.local_only is True
    with pytest.raises(CodexAppServerUnavailable):
        adapter.start_thread(actor_id="worker", assignment_id="assignment")
