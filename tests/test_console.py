from __future__ import annotations

import sqlite3
import sys
import threading
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coordination_memory_mcp.console import ConsoleHandler, shape_governance
from coordination_memory_mcp.store import CoordinationMemory, CoordinationMemoryError


def _detail(
    status,
    *,
    required_keys,
    failing,
    blockers_open=0,
    acceptor="acceptor-1",
    attempt=0,
    max_attempts=3,
    title="C",
    cid="c1",
):
    invariants = [{"key": k, "required": True} for k in required_keys]
    deviations = [
        {"title": f"b{i}", "disposition": "blocker", "status": "open"} for i in range(blockers_open)
    ]
    return {
        "contract": {
            "contract_id": cid,
            "title": title,
            "status": status,
            "acceptor_actor_id": acceptor,
            "repair_attempt": attempt,
            "max_repair_attempts": max_attempts,
        },
        "invariants": invariants,
        "deviations": deviations,
        "failing_required": list(failing),
    }


def test_shape_governance_counts_and_buckets() -> None:
    details = [
        _detail(
            "awaiting_human",
            required_keys=["a", "b"],
            failing=["a"],
            blockers_open=1,
            attempt=3,
            cid="c-human",
            title="Human",
        ),
        _detail(
            "repair_ready",
            required_keys=["a", "b"],
            failing=["a"],
            attempt=1,
            cid="c-repair",
            title="Repair",
        ),
        _detail(
            "awaiting_acceptor", required_keys=["a"], failing=[], cid="c-accept", title="Accept"
        ),
        _detail(
            "verifying",
            required_keys=["a", "b"],
            failing=["a", "b"],
            cid="c-verify",
            title="Verify",
        ),
        _detail("accepted", required_keys=["a"], failing=[], cid="c-done", title="Done"),
        _detail("drafting", required_keys=[], failing=[], cid="c-draft", title="Draft"),
    ]

    out = shape_governance(details)

    assert out["counts"] == {
        "contracts": 6,
        "awaiting_human": 1,
        "open_blockers": 1,
        "in_repair": 1,
        "accepted": 1,
    }
    assert {c["contract_id"] for c in out["needs_attention"]} == {"c-human", "c-repair"}
    assert {c["contract_id"] for c in out["in_flight"]} == {"c-accept", "c-verify"}
    assert {c["contract_id"] for c in out["accepted"]} == {"c-done"}
    human = next(c for c in out["needs_attention"] if c["contract_id"] == "c-human")
    assert human["probes_total"] == 2 and human["probes_passed"] == 1
    assert human["open_blockers"] == ["b0"]
    assert "waive_deviation" in human["next_action_hint"]


def test_shape_governance_blocker_puts_verifying_in_needs_attention() -> None:
    details = [_detail("verifying", required_keys=["a"], failing=[], blockers_open=1, cid="c-x")]
    out = shape_governance(details)
    assert [c["contract_id"] for c in out["needs_attention"]] == ["c-x"]
    assert out["in_flight"] == []
    assert out["counts"]["open_blockers"] == 1


def test_readonly_open_missing_db_does_not_create_files(tmp_path: Path) -> None:
    db_path = tmp_path / "missing-parent" / "coordination.sqlite3"

    memory = CoordinationMemory.open_readonly(db_path)

    with pytest.raises(sqlite3.OperationalError):
        memory.get_team_board("default")
    assert not db_path.exists()
    assert not db_path.parent.exists()


@pytest.mark.parametrize("exc", [BrokenPipeError(), ConnectionResetError()])
def test_client_disconnect_during_request_is_quiet(exc: OSError) -> None:
    handler = object.__new__(ConsoleHandler)
    handler._route_get = lambda: (_ for _ in ()).throw(exc)  # type: ignore[method-assign]

    handler.do_GET()


def test_client_disconnect_while_sending_error_response_is_quiet() -> None:
    handler = object.__new__(ConsoleHandler)
    handler._route_get = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
        CoordinationMemoryError("boom")
    )
    handler._send_json = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        BrokenPipeError()
    )

    handler.do_GET()


def test_root_serves_spa_shell(tmp_path: Path) -> None:
    memory = CoordinationMemory(tmp_path / "coordination.sqlite3")
    memory.create_assignment(
        assignment_id="readonly-console-task",
        title="Read Only Console Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    before = _table_counts(tmp_path / "coordination.sqlite3")
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")

    status, ctype, body = _fetch(readonly, "/")
    assert status == 200 and "text/html" in ctype
    assert 'id="app"' in body and "app.js" in body  # shell, not board data
    assert "Loading..." not in body  # Svelte owns the mounted view
    assert "Read Only Console Task" not in body  # data comes from /api/board now

    status, _ctype, board_body = _fetch(readonly, "/api/board?team_id=default")
    assert "Read Only Console Task" in board_body
    assert _table_counts(tmp_path / "coordination.sqlite3") == before  # read-only


def test_static_assets_served(tmp_path: Path) -> None:
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")
    s, ctype, body = _fetch(readonly, "/app.js")
    assert s == 200 and "javascript" in ctype and "dashboard-shell" in body
    s, ctype, body = _fetch(readonly, "/styles.css")
    assert s == 200 and "text/css" in ctype and ".stat-strip" in body


def _fetch(memory: CoordinationMemory, path: str) -> tuple[int, str, str]:
    return _request(memory, path)


def _request(
    memory: CoordinationMemory,
    path: str,
    *,
    method: str = "GET",
    write_memory: CoordinationMemory | None = None,
) -> tuple[int, str, str]:
    previous = ConsoleHandler.memory
    previous_write = ConsoleHandler.write_memory
    ConsoleHandler.memory = memory
    ConsoleHandler.write_memory = write_memory
    server = HTTPServer(("127.0.0.1", 0), ConsoleHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        host, port = server.server_address
        try:
            request = Request(f"http://{host}:{port}{path}", method=method)
            with urlopen(request, timeout=5) as response:
                return (
                    response.status,
                    response.headers.get("Content-Type", ""),
                    response.read().decode("utf-8"),
                )
        except HTTPError as exc:
            return (exc.code, exc.headers.get("Content-Type", ""), exc.read().decode("utf-8"))
    finally:
        server.server_close()
        thread.join(timeout=5)
        ConsoleHandler.memory = previous
        ConsoleHandler.write_memory = previous_write


def _seed_awaiting_human_contract(memory: CoordinationMemory) -> str:
    c = memory.create_acceptance_contract(
        contract_id="gov-c1",
        title="Gov C1",
        goal_statement="g",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
    )
    for key, neg, second in [("deny", True, False), ("tenant", False, True)]:
        c = memory.add_invariant(
            contract_id="gov-c1",
            key=key,
            description="d",
            probe_kind="http",
            probe_spec={"ref": key},
            actor_id="integrator",
            actor_role="integrator",
            base_revision=c["revision"],
            is_negative=neg,
            is_second_instance=second,
        )
    c = memory.raise_deviation(
        contract_id="gov-c1",
        title="demo admission",
        description="d",
        disposition="blocker",
        actor_id="agent-1",
        actor_role="agent",
        base_revision=c["revision"],
    )
    memory.seal_contract(
        contract_id="gov-c1",
        acceptor_actor_id="acceptor-1",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=c["revision"],
    )
    return "gov-c1"


def test_api_governance_returns_shaped_payload(tmp_path: Path) -> None:
    memory = CoordinationMemory(tmp_path / "coordination.sqlite3")
    _seed_awaiting_human_contract(memory)
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")

    status, ctype, body = _fetch(readonly, "/api/governance?team_id=default")

    assert status == 200
    assert "application/json" in ctype
    import json as _json

    data = _json.loads(body)
    assert data["counts"]["contracts"] == 1
    assert data["counts"]["open_blockers"] == 1
    assert data["needs_attention"][0]["contract_id"] == "gov-c1"


def _table_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: conn.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("workspaces", "actors", "teams", "assignments", "events")
        }


def test_api_contracts_list_and_detail(tmp_path: Path) -> None:
    memory = CoordinationMemory(tmp_path / "coordination.sqlite3")
    _seed_awaiting_human_contract(memory)
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")

    import json as _json

    status, ctype, body = _fetch(readonly, "/api/contracts?team_id=default")
    assert status == 200 and "application/json" in ctype
    listing = _json.loads(body)
    assert [c["contract_id"] for c in listing] == ["gov-c1"]

    status, ctype, body = _fetch(readonly, "/api/contracts/gov-c1")
    assert status == 200
    detail = _json.loads(body)
    assert detail["contract"]["contract_id"] == "gov-c1"
    assert {i["key"] for i in detail["invariants"]} == {"deny", "tenant"}
    assert "bound_assignments" in detail and "events" in detail


def test_api_contract_detail_unknown_id_returns_400(tmp_path: Path) -> None:
    CoordinationMemory(tmp_path / "coordination.sqlite3")
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")
    status, _ctype, body = _fetch(readonly, "/api/contracts/nope")
    assert status == 400
    assert "nope" in body


def test_api_teams_and_reviews(tmp_path: Path) -> None:
    memory = CoordinationMemory(tmp_path / "coordination.sqlite3")
    memory.create_team(
        team_id="t-extra", workspace_id="default", name="Extra", owner_actor_id="integrator"
    )
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")

    import json as _json

    status, ctype, body = _fetch(readonly, "/api/teams")
    assert status == 200 and "application/json" in ctype
    team_ids = {t["team_id"] for t in _json.loads(body)}
    assert {"default", "t-extra"} <= team_ids

    status, _ctype, body = _fetch(readonly, "/api/reviews")
    assert status == 200
    assert isinstance(_json.loads(body), list)


def test_api_workspaces_list_and_detail(tmp_path: Path) -> None:
    memory = CoordinationMemory(tmp_path / "coordination.sqlite3")
    memory.register_workspace(workspace_id="ws-dashboard", name="Workspace Dashboard")
    memory.create_team(
        team_id="team-dashboard",
        workspace_id="ws-dashboard",
        name="Dashboard Team",
        owner_actor_id="integrator",
    )
    memory.create_assignment(
        assignment_id="task-dashboard",
        title="Dashboard Task",
        actor_id="integrator",
        actor_role="integrator",
        base_revision=0,
        workspace_id="ws-dashboard",
        team_id="team-dashboard",
    )
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")

    import json as _json

    status, ctype, body = _fetch(readonly, "/api/workspaces")
    assert status == 200 and "application/json" in ctype
    listing = {w["workspace_id"]: w for w in _json.loads(body)}
    assert listing["ws-dashboard"]["team_count"] == 1
    assert listing["ws-dashboard"]["assignment_counts"] == {"ready": 1}
    assert listing["ws-dashboard"]["teams"][0]["team_id"] == "team-dashboard"
    assert listing["ws-dashboard"]["teams"][0]["assignment_counts"] == {"ready": 1}

    status, ctype, body = _fetch(readonly, "/api/workspaces/ws-dashboard")
    assert status == 200 and "application/json" in ctype
    detail = _json.loads(body)
    assert detail["workspace"]["workspace_id"] == "ws-dashboard"
    assert [t["team_id"] for t in detail["teams"]] == ["team-dashboard"]
    assert detail["teams"][0]["assignment_counts"] == {"ready": 1}
    assert [a["assignment_id"] for a in detail["assignments"]] == ["task-dashboard"]


def test_api_workspace_detail_unknown_id_returns_400(tmp_path: Path) -> None:
    CoordinationMemory(tmp_path / "coordination.sqlite3")
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")

    status, _ctype, body = _fetch(readonly, "/api/workspaces/nope")

    assert status == 400
    assert "nope" in body


def test_api_workspace_archive_post_soft_archives_workspace(tmp_path: Path) -> None:
    writer = CoordinationMemory(tmp_path / "coordination.sqlite3")
    writer.register_workspace(workspace_id="ws-archive-api", name="Archive API")
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")

    import json as _json

    status, ctype, body = _request(
        readonly,
        "/api/workspaces/ws-archive-api/archive",
        method="POST",
        write_memory=writer,
    )

    assert status == 200 and "application/json" in ctype
    archived = _json.loads(body)
    assert archived["status"] == "archived"
    assert writer.get_workspace_detail("ws-archive-api")["workspace"]["status"] == "archived"


def test_api_workspace_archive_requires_write_memory(tmp_path: Path) -> None:
    writer = CoordinationMemory(tmp_path / "coordination.sqlite3")
    writer.register_workspace(workspace_id="ws-no-writer", name="No Writer")
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")

    status, _ctype, body = _request(
        readonly,
        "/api/workspaces/ws-no-writer/archive",
        method="POST",
    )

    assert status == 400
    assert "write access" in body
    assert writer.get_workspace_detail("ws-no-writer")["workspace"]["status"] == "active"


def test_app_js_contains_routes_and_renderers(tmp_path: Path) -> None:
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")
    _s, _c, body = _fetch(readonly, "/app.js")
    for marker in [
        "dashboard-shell",
        "workspace-grid",
        "Raw JSON",
        "#/workspaces",
        "#/teams/",
        "#/contracts/",
        "/api/workspaces",
        "/api/board",
        "team-list",
        "team-switcher",
        "setInterval",
    ]:
        assert marker in body, f"missing marker: {marker}"

    root = Path(__file__).resolve().parents[1]
    app_svelte = (root / "frontend/src/App.svelte").read_text()
    for marker in [
        'route.name === "dashboard"',
        'route.name === "workspaces"',
        'route.name === "workspace"',
        'route.name === "contract"',
        'route.name === "assignment"',
        'route.name === "run"',
        "teamDashboardHref",
        "archiveWorkspace",
    ]:
        assert marker in app_svelte, f"App.svelte missing route marker: {marker!r}"


def test_app_js_assignment_run_views_are_human_friendly(tmp_path: Path) -> None:
    """renderAssignment and renderRun must use structured event rows, not raw JSON dumps."""
    root = Path(__file__).resolve().parents[1]
    app_svelte = (root / "frontend/src/App.svelte").read_text()
    ui_js = (root / "frontend/src/ui.js").read_text()
    for marker in ["eventDetail(event)", "Raw JSON", "Assignment", "Runs"]:
        assert marker in app_svelte, f"App.svelte missing marker: {marker!r}"
    for marker in ["eventDetail", "verification_reported", "repair_dispatched"]:
        assert marker in ui_js, f"ui.js missing marker: {marker!r}"


def test_app_js_polish_markers(tmp_path: Path) -> None:
    """FIX 2 & 3: auto-refresh state preservation + empty/error warmth markers."""
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")
    _s, _c, js_body = _fetch(readonly, "/app.js")
    for marker in [
        "Nothing needs attention",
        "No acceptance contracts yet",
    ]:
        assert marker in js_body, f"app.js missing marker: {marker!r}"
    root = Path(__file__).resolve().parents[1]
    app_svelte = (root / "frontend/src/App.svelte").read_text()
    for marker in ["autoTick", "Retry", "scrollTo", "document.hidden"]:
        assert marker in app_svelte, f"App.svelte missing marker: {marker!r}"

    _s2, _c2, css_body = _fetch(readonly, "/styles.css")
    for marker in ["font-size:13px", "#59636e"]:
        assert marker in css_body, f"styles.css missing marker: {marker!r}"


def test_app_js_baseline_polish(tmp_path: Path) -> None:
    """Baseline open-source-quality polish: a11y focus, responsive, full badge colors, favicon."""
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")
    _s, _c, css_body = _fetch(readonly, "/styles.css")
    assert "focus-visible" in css_body, "styles.css missing focus-visible rule"
    root = Path(__file__).resolve().parents[1]
    source_css = (root / "frontend/src/styles.css").read_text()
    assert "@media (max-width:640px)" in source_css, "styles.css missing responsive media query"

    _s2, _c2, js_body = _fetch(readonly, "/app.js")
    assert "criteria_sealed" in js_body, "app.js missing criteria_sealed in badge map"

    _s3, _c3, html_body = _fetch(readonly, "/")
    assert 'rel="icon"' in html_body, "index.html missing favicon suppression link"
    assert 'id="app"' in html_body and 'id="view"' not in html_body
    assert "Loading..." not in html_body, "index.html should not leave fallback content in #app"
    app_svelte = (root / "frontend/src/App.svelte").read_text()
    assert 'href="#/workspaces"' in app_svelte, "App.svelte missing workspace nav link"
    assert 'href="#/"' in app_svelte and ">Dashboard<" in app_svelte
    assert ">Overview<" not in html_body


def test_workspace_management_docs_and_style_markers() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text()
    for marker in [
        "Dashboard (local management console)",
        "POST /api/workspaces/<id>/archive",
        "Archive workspace",
        "only write action",
    ]:
        assert marker in readme, f"README missing marker: {marker!r}"

    app_svelte = (root / "frontend/src/App.svelte").read_text()
    for marker in ["#/teams/", "teamDashboardHref", "Team dashboard"]:
        assert marker in app_svelte, f"App.svelte missing marker: {marker!r}"

    styles = (root / "src/coordination_memory_mcp/static/styles.css").read_text()
    for marker in [
        "--surface-0",
        "--surface-panel",
        "dashboard-shell",
        "lane-title",
        "team-link",
        "workspace-grid",
        "toolbar",
        "danger",
        "team-list",
    ]:
        assert marker in styles, f"styles.css missing marker: {marker!r}"


def test_dashboard_static_assets_have_no_visible_em_dash(tmp_path: Path) -> None:
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")
    em_dash = chr(8212)
    en_dash = chr(8211)
    for path in ["/", "/app.js", "/styles.css"]:
        _s, _c, body = _fetch(readonly, path)
        assert em_dash not in body, f"{path} contains an em dash"
        assert en_dash not in body, f"{path} contains an en dash separator"


def test_api_version_returns_version_and_build(tmp_path: Path) -> None:
    """GET /api/version must return 200 JSON with 'version' and 8-hex-char 'build'."""
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")
    import json as _json

    status, ctype, body = _fetch(readonly, "/api/version")
    assert status == 200, f"expected 200, got {status}"
    assert "application/json" in ctype
    data = _json.loads(body)
    assert "version" in data, "response must have 'version' key"
    assert "build" in data, "response must have 'build' key"
    build = data["build"]
    assert len(build) == 8, f"build must be 8 chars, got {len(build)!r}: {build!r}"
    assert all(c in "0123456789abcdef" for c in build), f"build must be hex chars, got {build!r}"


def test_version_markers_in_static_assets(tmp_path: Path) -> None:
    """app.js must have loadVersion + /api/version; index.html must have id='version'."""
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")
    _s, _c, js_body = _fetch(readonly, "/app.js")
    assert "/api/version" in js_body, "app.js missing /api/version endpoint reference"

    _s2, _c2, html_body = _fetch(readonly, "/")
    assert 'id="app"' in html_body, 'index.html missing id="app" mount point'
    root = Path(__file__).resolve().parents[1]
    app_svelte = (root / "frontend/src/App.svelte").read_text()
    assert "loadVersion" in app_svelte, "App.svelte missing loadVersion function"
    assert 'id="version"' in app_svelte, 'App.svelte missing id="version" element'


def test_end_to_end_dashboard_api_surface(tmp_path: Path) -> None:
    memory = CoordinationMemory(tmp_path / "coordination.sqlite3")
    cid = _seed_awaiting_human_contract(memory)
    memory.register_workspace(workspace_id="api-surface", name="API Surface")
    readonly = CoordinationMemory.open_readonly(tmp_path / "coordination.sqlite3")
    import json as _json

    # shell + assets
    assert _fetch(readonly, "/")[0] == 200
    assert _fetch(readonly, "/app.js")[0] == 200
    assert _fetch(readonly, "/styles.css")[0] == 200
    # data surface
    assert _fetch(readonly, "/api/board?team_id=default")[0] == 200
    gov = _json.loads(_fetch(readonly, "/api/governance?team_id=default")[2])
    assert gov["needs_attention"][0]["contract_id"] == cid
    detail = _json.loads(_fetch(readonly, "/api/contracts/" + cid)[2])
    assert detail["contract"]["status"] == "criteria_sealed"
    assert "bound_assignments" in detail and "events" in detail
    assert _fetch(readonly, "/api/teams")[0] == 200
    assert _fetch(readonly, "/api/reviews")[0] == 200
    workspaces = _json.loads(_fetch(readonly, "/api/workspaces")[2])
    assert any(w["workspace_id"] == "api-surface" for w in workspaces)
    workspace = _json.loads(_fetch(readonly, "/api/workspaces/api-surface")[2])
    assert workspace["workspace"]["name"] == "API Surface"
    # read-only preserved
    with readonly._connect() as conn:
        assert conn.execute("pragma query_only").fetchone()[0] == 1
