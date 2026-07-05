"""Unified ``comem`` command-line interface.

Subcommands:
- ``serve``     run the stdio MCP server (for an MCP client to launch)
- ``dashboard`` run the local web console
- ``init``      scaffold agent-onboarding files into a repository
- ``loop``      run the local scheduler loop
"""

from __future__ import annotations

import argparse
import os

from coordination_memory_mcp import console, loop_runner, scaffold, server
from coordination_memory_mcp.loop_models import LoopConfig
from coordination_memory_mcp.store import CoordinationMemory


def _version() -> str:
    return console.package_version()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comem",
        description=(
            "Local multi-agent coordination memory: MCP server, dashboard, and project setup."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Run the stdio MCP server.")

    dash = sub.add_parser(
        "dashboard",
        help="Run the local web console.",
        description=(
            "Run the local web console. Read APIs are read-only; the only write "
            "action is Archive workspace, a soft status update."
        ),
    )
    dash.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    dash.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765).")
    dash.add_argument(
        "--db",
        default=None,
        help="SQLite database path (defaults to $COORDINATION_MEMORY_DB).",
    )

    init = sub.add_parser("init", help="Scaffold agent-onboarding files into a repo.")
    init.add_argument("--dir", default=".", help="Target repository directory (default: cwd).")
    init.add_argument(
        "--tools",
        default="all",
        help="Comma-separated: claude,codex,cursor,copilot,opencode (default: all).",
    )
    init.add_argument("--force", action="store_true", help="Overwrite existing adapter files.")

    loop = sub.add_parser("loop", help="Run the local Coordination Memory scheduler loop.")
    loop.add_argument("--workspace", default=None, help="Workspace id to schedule (default: all).")
    loop.add_argument("--team", default=None, help="Team id to schedule (default: all).")
    loop.add_argument(
        "--adapter",
        default="fake",
        choices=["fake", "codex-app-server"],
        help="Dispatch adapter to use (default: fake).",
    )
    loop.add_argument(
        "--poll-interval",
        type=float,
        default=10.0,
        help="Seconds between scheduler polls (default: 10).",
    )
    loop.add_argument(
        "--max-concurrent-runs",
        type=int,
        default=1,
        help="Maximum active dispatches per loop tick (default: 1).",
    )
    loop.add_argument(
        "--review-nudge-interval",
        type=float,
        default=60.0,
        help="Seconds before nudging pending integrator reviews (default: 60).",
    )
    loop.add_argument("--dry-run", action="store_true", help="Print planned commands only.")
    loop.add_argument("--once", action="store_true", help="Run one scheduler tick and exit.")
    loop.add_argument(
        "--db",
        default=None,
        help="SQLite database path (defaults to $COORDINATION_MEMORY_DB).",
    )
    return parser


def _run_init(target_dir: str, tools: str, force: bool) -> None:
    result = scaffold.run_init(target_dir, tools=tools.split(","), force=force)
    print(f"AGENTS.md {result.agents_action}.")
    for path in result.written:
        if path != "AGENTS.md":
            print(f"  wrote {path}")
    for path in result.skipped:
        print(f"  skipped {path} (exists; use --force)")
    print("\nAdd this to your MCP client config:\n")
    print(result.mcp_config)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        server.main()
    elif args.command == "dashboard":
        console.serve_console(host=args.host, port=args.port, db=args.db)
    elif args.command == "init":
        _run_init(args.dir, args.tools, args.force)
    elif args.command == "loop":
        db_path = args.db or os.environ.get("COORDINATION_MEMORY_DB", loop_runner.DEFAULT_DB_PATH)
        memory = CoordinationMemory(db_path)
        config = LoopConfig(
            workspace_id=args.workspace,
            team_id=args.team,
            adapter=args.adapter,
            poll_interval=args.poll_interval,
            max_concurrent_runs=args.max_concurrent_runs,
            review_nudge_interval=args.review_nudge_interval,
            dry_run=args.dry_run,
            once=args.once,
        )
        result = loop_runner.LoopRunner(memory=memory, config=config).run_once()
        for command in result.commands:
            print(f"{command.command_id} {command.command_type} {command.assignment_id or '-'}")
    else:  # pragma: no cover - argparse enforces a valid subcommand
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
