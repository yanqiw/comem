from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import tomllib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from coordination_memory_mcp.server import DEFAULT_DB_PATH
from coordination_memory_mcp.store import CoordinationMemory, CoordinationMemoryError

STATIC_DIR = Path(__file__).resolve().parent / "static"
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


def _source_project_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError:
        return "dev"
    version = data.get("project", {}).get("version")
    return version if isinstance(version, str) and version else "dev"


def package_version() -> str:
    try:
        return importlib.metadata.version("coordination-memory-mcp")
    except importlib.metadata.PackageNotFoundError:
        return _source_project_version()


def _version_info() -> dict[str, str]:
    digest = hashlib.sha256()
    for name in ("index.html", "app.js", "styles.css"):
        path = STATIC_DIR / name
        if path.is_file():
            digest.update(path.read_bytes())
    return {"version": package_version(), "build": digest.hexdigest()[:8]}


def _next_action_hint(status: str, open_blockers: list[str]) -> str:
    if status == "awaiting_human":
        return (
            "acceptor may waive_deviation the blocker, "
            "or Integrator may reopen_contract to widen criteria"
        )
    if status == "repair_ready":
        return "repair assignment dispatched; will re-evaluate"
    if status == "awaiting_acceptor":
        return "independent sign-off pending (accept_contract)"
    if status == "verifying":
        return "probes in progress"
    if status == "accepted":
        return "accepted"
    return ""


def _contract_card(detail: dict[str, Any]) -> dict[str, Any]:
    contract = detail["contract"]
    required = [i for i in detail["invariants"] if i.get("required")]
    failing = set(detail.get("failing_required", []))
    open_blockers = [
        d["title"]
        for d in detail.get("deviations", [])
        if d.get("disposition") == "blocker" and d.get("status") == "open"
    ]
    return {
        "contract_id": contract["contract_id"],
        "title": contract["title"],
        "status": contract["status"],
        "probes_total": len(required),
        "probes_passed": len([i for i in required if i["key"] not in failing]),
        "repair_attempt": contract["repair_attempt"],
        "max_repair_attempts": contract["max_repair_attempts"],
        "open_blockers": open_blockers,
        "acceptor_actor_id": contract["acceptor_actor_id"],
        "next_action_hint": _next_action_hint(contract["status"], open_blockers),
    }


def shape_governance(details: list[dict[str, Any]]) -> dict[str, Any]:
    cards = [_contract_card(d) for d in details]
    needs_attention = [
        c for c in cards if c["status"] in {"awaiting_human", "repair_ready"} or c["open_blockers"]
    ]
    needs_ids = {c["contract_id"] for c in needs_attention}
    in_flight = [
        c
        for c in cards
        if c["contract_id"] not in needs_ids and c["status"] in {"verifying", "awaiting_acceptor"}
    ]
    accepted = [c for c in cards if c["status"] == "accepted"]
    counts = {
        "contracts": len(cards),
        "awaiting_human": len([c for c in cards if c["status"] == "awaiting_human"]),
        "open_blockers": len([c for c in cards if c["open_blockers"]]),
        "in_repair": len([c for c in cards if c["status"] == "repair_ready"]),
        "accepted": len(accepted),
    }
    return {
        "counts": counts,
        "needs_attention": needs_attention,
        "in_flight": in_flight,
        "accepted": accepted,
    }


class ConsoleHandler(BaseHTTPRequestHandler):
    memory: CoordinationMemory | None = None
    write_memory: CoordinationMemory | None = None

    def do_GET(self) -> None:
        try:
            self._route_get()
        except CoordinationMemoryError as exc:
            try:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except CLIENT_DISCONNECT_ERRORS:
                return
        except CLIENT_DISCONNECT_ERRORS:
            return

    def do_POST(self) -> None:
        try:
            self._route_post()
        except CoordinationMemoryError as exc:
            try:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except CLIENT_DISCONNECT_ERRORS:
                return
        except CLIENT_DISCONNECT_ERRORS:
            return

    def _route_get(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            self._send_static("index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._send_static("app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._send_static("styles.css", "text/css; charset=utf-8")
            return

        if parsed.path == "/api/board":
            team_id = query.get("team_id", ["default"])[0] or "default"
            self._send_json(self._memory().get_team_board(team_id))
            return

        if parsed.path == "/api/attention":
            team_id = query.get("team_id", ["default"])[0] or "default"
            target = query.get("target", ["human"])[0] or "human"
            include_green = query.get("include_green", ["false"])[0].lower() == "true"
            self._send_json(
                self._memory().get_attention_board(
                    team_id=team_id,
                    target=target,
                    include_green=include_green,
                )
            )
            return

        if parsed.path == "/api/workspaces":
            self._send_json(self._memory().list_workspaces())
            return

        workspace_prefix = "/api/workspaces/"
        if parsed.path.startswith(workspace_prefix):
            workspace_id = unquote(parsed.path[len(workspace_prefix) :])
            if workspace_id:
                self._send_json(self._memory().get_workspace_detail(workspace_id))
                return

        assignment_prefix = "/api/assignments/"
        if parsed.path.startswith(assignment_prefix):
            assignment_id = unquote(parsed.path[len(assignment_prefix) :])
            if assignment_id:
                self._send_json(self._memory().get_assignment_detail(assignment_id))
                return

        run_prefix = "/api/runs/"
        if parsed.path.startswith(run_prefix):
            run_suffix = parsed.path[len(run_prefix) :]
            if run_suffix.endswith("/brief"):
                run_id = unquote(run_suffix[: -len("/brief")])
                if run_id:
                    self._send_json(self._memory().get_human_brief(run_id))
                    return
            run_id = unquote(run_suffix)
            if run_id:
                self._send_json(self._memory().get_run_detail(run_id))
                return

        if parsed.path == "/api/governance":
            team_id = query.get("team_id", ["default"])[0] or "default"
            contracts = self._memory().list_contracts(team_id=team_id)
            details = [self._memory().get_contract_detail(c["contract_id"]) for c in contracts]
            self._send_json(shape_governance(details))
            return

        if parsed.path == "/api/contracts":
            team_id = query.get("team_id", ["default"])[0] or "default"
            workspace_values = query.get("workspace_id")
            workspace_filter = workspace_values[0] if workspace_values else None
            self._send_json(
                self._memory().list_contracts(workspace_id=workspace_filter, team_id=team_id)
            )
            return

        contract_prefix = "/api/contracts/"
        if parsed.path.startswith(contract_prefix):
            contract_id = unquote(parsed.path[len(contract_prefix) :])
            if contract_id:
                self._send_json(self._memory().get_contract_detail(contract_id))
                return

        if parsed.path == "/api/teams":
            snapshot = self._memory().get_snapshot()
            self._send_json(list(snapshot["teams"].values()))
            return

        if parsed.path == "/api/reviews":
            self._send_json(self._memory().list_pending_reviews())
            return

        if parsed.path == "/api/version":
            self._send_json(_version_info())
            return

        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _route_post(self) -> None:
        parsed = urlparse(self.path)
        workspace_prefix = "/api/workspaces/"
        if parsed.path.startswith(workspace_prefix):
            suffix = parsed.path[len(workspace_prefix) :]
            if suffix.endswith("/archive"):
                workspace_id = unquote(suffix[: -len("/archive")])
                if workspace_id:
                    self._send_json(
                        self._write_memory().archive_workspace(
                            workspace_id=workspace_id,
                            actor_role="integrator",
                        )
                    )
                    return

        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _memory(self) -> CoordinationMemory:
        if self.memory is None:
            raise CoordinationMemoryError("coordination memory is not configured")
        return self.memory

    def _write_memory(self) -> CoordinationMemory:
        if self.write_memory is None:
            raise CoordinationMemoryError("coordination memory write access is not configured")
        return self.write_memory

    def _send_static(self, name: str, content_type: str) -> None:
        path = STATIC_DIR / name
        if not path.is_file():
            self._send_json({"error": f"asset not found: {name}"}, HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Assets are read fresh from disk each request; tell the browser not to
        # cache them so edits show on a normal refresh (no hard-reload needed).
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve a local coordination memory management console."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--db",
        default=os.environ.get("COORDINATION_MEMORY_DB", DEFAULT_DB_PATH),
        help="SQLite database path.",
    )
    args = parser.parse_args()
    serve_console(host=args.host, port=args.port, db=args.db)


def serve_console(
    host: str = "127.0.0.1",
    port: int = 8765,
    db: str | os.PathLike[str] | None = None,
) -> None:
    """Run the local console HTTP server until interrupted."""
    db_path = (
        Path(db)
        if db is not None
        else Path(os.environ.get("COORDINATION_MEMORY_DB", DEFAULT_DB_PATH))
    )
    memory = CoordinationMemory.open_readonly(db_path)
    memory.get_team_board("default")
    write_memory = CoordinationMemory(db_path)
    ConsoleHandler.memory = memory
    ConsoleHandler.write_memory = write_memory
    server = HTTPServer((host, port), ConsoleHandler)
    url = f"http://{host}:{port}/"
    print(f"Coordination memory console: {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
