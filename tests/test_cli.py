from __future__ import annotations

import pytest

from coordination_memory_mcp import cli, scaffold


def test_help_runs(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for sub in ("serve", "dashboard", "init", "loop"):
        assert sub in out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0


def test_no_subcommand_errors() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code != 0


def test_serve_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}
    monkeypatch.setattr(cli.server, "main", lambda: called.setdefault("serve", True))
    assert cli.main(["serve"]) == 0
    assert called.get("serve") is True


def test_dashboard_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake(host: str, port: int, db: str | None) -> None:
        captured.update(host=host, port=port, db=db)

    monkeypatch.setattr(cli.console, "serve_console", fake)
    assert cli.main(["dashboard", "--host", "0.0.0.0", "--port", "9000"]) == 0
    assert captured == {"host": "0.0.0.0", "port": 9000, "db": None}


def test_loop_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    captured = {}

    class FakeRunner:
        def __init__(self, *, memory, config) -> None:
            captured["config"] = config

        def run_once(self):
            from coordination_memory_mcp.loop_runner import LoopResult

            return LoopResult(commands=[], dispatched=0)

    monkeypatch.setattr(cli.loop_runner, "LoopRunner", FakeRunner)
    assert (
        cli.main(["loop", "--db", str(tmp_path / "coordination.sqlite3"), "--once", "--dry-run"])
        == 0
    )
    assert captured["config"].dry_run is True
    assert captured["config"].once is True


def test_loop_accepts_codex_app_server_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    captured = {}

    class FakeRunner:
        def __init__(self, *, memory, config) -> None:
            captured["config"] = config

        def run_once(self):
            from coordination_memory_mcp.loop_runner import LoopResult

            return LoopResult(commands=[], dispatched=0)

    monkeypatch.setattr(cli.loop_runner, "LoopRunner", FakeRunner)
    assert (
        cli.main(
            [
                "loop",
                "--db",
                str(tmp_path / "coordination.sqlite3"),
                "--adapter",
                "codex-app-server",
                "--once",
            ]
        )
        == 0
    )
    assert captured["config"].adapter == "codex-app-server"


def test_init_writes_all_tools(tmp_path) -> None:
    result = scaffold.run_init(tmp_path)
    assert result.agents_action == "created"
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".claude/skills/coordination-memory/SKILL.md").exists()
    assert (tmp_path / ".cursor/rules/coordination-memory.mdc").exists()
    assert (tmp_path / ".github/copilot-instructions.md").exists()
    text = (tmp_path / "AGENTS.md").read_text()
    assert scaffold.MARKER_START in text
    assert scaffold.MARKER_END in text


def test_init_idempotent_no_duplicate_block(tmp_path) -> None:
    scaffold.run_init(tmp_path)
    first = (tmp_path / "AGENTS.md").read_text()
    result2 = scaffold.run_init(tmp_path, force=True)
    second = (tmp_path / "AGENTS.md").read_text()
    assert result2.agents_action == "updated"
    assert first == second
    assert second.count(scaffold.MARKER_START) == 1


def test_init_appends_to_existing_agents(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("# My project\n\nExisting guidance.\n")
    result = scaffold.run_init(tmp_path)
    assert result.agents_action == "appended"
    text = (tmp_path / "AGENTS.md").read_text()
    assert "Existing guidance." in text
    assert text.count(scaffold.MARKER_START) == 1


def test_init_tools_subset(tmp_path) -> None:
    scaffold.run_init(tmp_path, tools=["claude"])
    assert (tmp_path / ".claude/skills/coordination-memory/SKILL.md").exists()
    assert not (tmp_path / ".cursor/rules/coordination-memory.mdc").exists()


def test_init_skips_existing_without_force(tmp_path) -> None:
    scaffold.run_init(tmp_path, tools=["cursor"])
    result = scaffold.run_init(tmp_path, tools=["cursor"])
    assert ".cursor/rules/coordination-memory.mdc" in result.skipped


def test_init_unknown_tool(tmp_path) -> None:
    with pytest.raises(ValueError):
        scaffold.run_init(tmp_path, tools=["bogus"])


def test_agents_md_documents_protocol(tmp_path) -> None:
    scaffold.run_init(tmp_path, tools=["codex"])
    text = (tmp_path / "AGENTS.md").read_text().lower()
    for token in (
        "integrator",
        "completed_gate_passed",
        "claim_assignment",
        "accept_event",
        "base_revision",
        "acceptance contract",
        "context_refs",
        "session_bind",
        "execution mode",
        "codex_subagent",
        "comem_loop",
        "record_run_binding",
        "session_kind",
        "coordination_memory_db",
        "dry-run",
        "one active loop",
        "codex-app-server",
    ):
        assert token in text, f"AGENTS.md missing protocol token: {token!r}"


def test_init_via_main(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["init", "--dir", str(tmp_path), "--tools", "codex"]) == 0
    out = capsys.readouterr().out
    assert "AGENTS.md created" in out
    assert "coordination-memory" in out  # MCP config snippet printed
    assert (tmp_path / "AGENTS.md").exists()
