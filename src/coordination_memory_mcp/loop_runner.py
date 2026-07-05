from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass

from coordination_memory_mcp.loop_adapters import (
    CodexAdapter,
    CodexAppServerAdapter,
    FakeCodexAdapter,
)
from coordination_memory_mcp.loop_models import LoopCommand, LoopConfig, build_command_id
from coordination_memory_mcp.loop_prompts import build_review_prompt, build_worker_prompt
from coordination_memory_mcp.store import CoordinationMemory, LeaseConflictError, StaleRevisionError

DEFAULT_DB_PATH = ".coordination-memory/coordination.sqlite3"
PLAN_PATH = "docs/superpowers/plans/2026-07-05-local-codex-loop.md"


@dataclass(frozen=True)
class LoopResult:
    commands: list[LoopCommand]
    dispatched: int


def adapter_from_name(name: str) -> CodexAdapter:
    if name == "fake":
        return FakeCodexAdapter()
    if name == "codex-app-server":
        return CodexAppServerAdapter()
    raise ValueError(f"unsupported loop adapter: {name}")


class LoopRunner:
    def __init__(
        self,
        *,
        memory: CoordinationMemory,
        config: LoopConfig,
        adapter: CodexAdapter | None = None,
    ) -> None:
        self.memory = memory
        self.config = config
        self.adapter = adapter or adapter_from_name(config.adapter)

    def select_commands(self) -> list[LoopCommand]:
        commands: list[LoopCommand] = []
        for team_id in self._team_ids():
            board = self.memory.get_team_board(team_id)
            ready = sorted(
                board["lanes"].get("ready", []),
                key=lambda item: (
                    -item.get("priority", 0),
                    item.get("updated_at") or "",
                    item["assignment_id"],
                ),
            )
            for item in ready[: self.config.max_concurrent_runs]:
                if self.config.workspace_id and item["workspace_id"] != self.config.workspace_id:
                    continue
                detail = self.memory.get_assignment_detail(item["assignment_id"])
                commands.append(self._start_command(detail["assignment"]))
        commands.extend(self._review_commands())
        return commands

    def run_once(self) -> LoopResult:
        capabilities = self.adapter.probe()
        if not capabilities.can_start_thread:
            return LoopResult(commands=[], dispatched=0)

        commands = self.select_commands()
        if self.config.dry_run:
            return LoopResult(commands=commands, dispatched=0)

        dispatched = 0
        for command in commands:
            if command.command_type == "start_assignment":
                self._dispatch_start_assignment(command)
                dispatched += 1
            elif command.command_type == "nudge_review":
                self._dispatch_review_nudge(command)
                dispatched += 1
        return LoopResult(commands=commands, dispatched=dispatched)

    def run_forever(self) -> None:
        while True:
            self.run_once()
            if self.config.once:
                return
            time.sleep(self.config.poll_interval)

    def _team_ids(self) -> Iterable[str]:
        if self.config.team_id:
            return [self.config.team_id]
        return ["default"]

    def _start_command(self, assignment: dict) -> LoopCommand:
        actor_id = self._target_actor_id(assignment)
        command_id = build_command_id(
            command_type="start_assignment",
            assignment_id=assignment["assignment_id"],
            assignment_revision=assignment["revision"],
            attempt=1,
        )
        return LoopCommand(
            command_id=command_id,
            command_type="start_assignment",
            workspace_id=assignment["workspace_id"],
            team_id=assignment["team_id"],
            assignment_id=assignment["assignment_id"],
            assignment_revision=assignment["revision"],
            run_id=assignment["active_run_id"],
            target_actor_id=actor_id,
            adapter_kind=self.adapter.adapter_kind,
            prompt_kind="worker_assignment",
            payload={"assignment": assignment},
        )

    def _target_actor_id(self, assignment: dict) -> str:
        metadata = assignment.get("metadata") or {}
        session_bind = metadata.get("session_bind")
        if isinstance(session_bind, dict):
            target_actor_id = session_bind.get("target_actor_id")
            if isinstance(target_actor_id, str) and target_actor_id.strip():
                return target_actor_id.strip()

        actor_hint = metadata.get("assigned_actor_hint")
        if isinstance(actor_hint, str) and actor_hint.strip():
            return actor_hint.strip()

        return f"{self.config.actor_prefix}-{assignment['assignment_id']}"

    def _review_commands(self) -> list[LoopCommand]:
        pending = self.memory.list_pending_reviews()
        grouped: dict[tuple[str, str], list[dict]] = {}
        for event in pending:
            if self.config.workspace_id and event["workspace_id"] != self.config.workspace_id:
                continue
            if self.config.team_id and event["team_id"] != self.config.team_id:
                continue
            grouped.setdefault((event["workspace_id"], event["team_id"]), []).append(event)

        commands: list[LoopCommand] = []
        for (workspace_id, team_id), events in grouped.items():
            events = [event for event in events if not self._already_nudged(event)]
            if not events:
                continue
            first = events[0]
            command_id = build_command_id(
                command_type="nudge_review",
                assignment_id=first["assignment_id"],
                event_id=first["event_id"],
                attempt=1,
            )
            commands.append(
                LoopCommand(
                    command_id=command_id,
                    command_type="nudge_review",
                    workspace_id=workspace_id,
                    team_id=team_id,
                    assignment_id=first["assignment_id"],
                    assignment_revision=first["assignment_revision"],
                    run_id=first["run_id"],
                    target_actor_id=self.config.integrator_actor_id,
                    adapter_kind=self.adapter.adapter_kind,
                    prompt_kind="integrator_review",
                    payload={"pending_events": events},
                )
            )
        return commands

    def _already_nudged(self, event: dict) -> bool:
        detail = self.memory.get_assignment_detail(event["assignment_id"])
        for existing in detail["events"]:
            if existing["event_type"] != "review_nudge_dispatched":
                continue
            pending_ids = existing["payload"].get("pending_event_ids") or []
            if event["event_id"] in pending_ids:
                return True
        return False

    def _dispatch_start_assignment(self, command: LoopCommand) -> None:
        assignment = command.payload["assignment"]
        thread = self.adapter.start_thread(
            actor_id=command.target_actor_id,
            assignment_id=command.assignment_id,
        )
        try:
            claimed = self.memory.claim_assignment(
                assignment_id=assignment["assignment_id"],
                actor_id=command.target_actor_id,
                actor_role="agent",
                base_revision=assignment["revision"],
                session_kind="codex_thread",
                session_ref=thread.thread_id,
                interactive_url=thread.interactive_url,
            )
        except (LeaseConflictError, StaleRevisionError):
            return

        prompt = build_worker_prompt(
            actor_id=command.target_actor_id,
            assignment=assignment,
            command_id=command.command_id,
            plan_path=PLAN_PATH,
        )
        turn_id = self.adapter.start_turn(
            thread_id=thread.thread_id,
            prompt=prompt,
            client_user_message_id=command.command_id,
        )
        self.memory.record_run_binding(
            run_id=claimed["active_run_id"],
            actor_id=command.target_actor_id,
            actor_role="agent",
            binding_patch={
                "adapter": {"kind": self.adapter.adapter_kind},
                "communication_cursor": {
                    "last_command_id": command.command_id,
                    "last_client_user_message_id": command.command_id,
                    "last_seen_turn_id": turn_id,
                },
            },
            event_payload={"summary": "loop dispatched worker turn"},
        )
        self.memory.append_event(
            assignment_id=assignment["assignment_id"],
            event_type="loop_command_dispatched",
            status="observed",
            actor_id=command.target_actor_id,
            actor_role="agent",
            base_revision=claimed["revision"],
            payload={
                "command_id": command.command_id,
                "command_type": command.command_type,
                "adapter_kind": self.adapter.adapter_kind,
                "thread_id": thread.thread_id,
                "turn_id": turn_id,
            },
        )

    def _dispatch_review_nudge(self, command: LoopCommand) -> None:
        thread = self.adapter.start_thread(
            actor_id=command.target_actor_id,
            assignment_id=command.assignment_id,
        )
        prompt = build_review_prompt(
            actor_id=command.target_actor_id,
            workspace_id=command.workspace_id,
            team_id=command.team_id,
            pending_events=command.payload["pending_events"],
        )
        turn_id = self.adapter.start_turn(
            thread_id=thread.thread_id,
            prompt=prompt,
            client_user_message_id=command.command_id,
        )
        event = command.payload["pending_events"][0]
        self.memory.append_event(
            assignment_id=event["assignment_id"],
            event_type="review_nudge_dispatched",
            status="observed",
            actor_id=command.target_actor_id,
            actor_role="integrator",
            base_revision=event["assignment_revision"],
            payload={
                "command_id": command.command_id,
                "pending_event_ids": [
                    item["event_id"] for item in command.payload["pending_events"]
                ],
                "thread_id": thread.thread_id,
                "turn_id": turn_id,
            },
        )
