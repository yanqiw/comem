from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class AdapterCapabilities:
    adapter_kind: str
    can_start_thread: bool
    can_resume_thread: bool
    can_start_turn: bool
    can_steer_turn: bool
    local_only: bool = True


@dataclass
class AdapterThread:
    thread_id: str
    interactive_url: str
    active_turn_id: str | None = None
    completed_turn_ids: list[str] = field(default_factory=list)


class CodexAdapter(Protocol):
    adapter_kind: str

    def probe(self) -> AdapterCapabilities:
        raise NotImplementedError

    def start_thread(self, *, actor_id: str, assignment_id: str | None) -> AdapterThread:
        raise NotImplementedError

    def resume_thread(self, *, thread_id: str) -> AdapterThread:
        raise NotImplementedError

    def start_turn(
        self,
        *,
        thread_id: str,
        prompt: str,
        client_user_message_id: str,
    ) -> str:
        raise NotImplementedError


class FakeCodexAdapter:
    adapter_kind = "fake_codex"

    def __init__(self) -> None:
        self._thread_counter = itertools.count(1)
        self._turn_counter = itertools.count(1)
        self.threads: dict[str, AdapterThread] = {}
        self.prompts: dict[str, str] = {}

    def probe(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_kind=self.adapter_kind,
            can_start_thread=True,
            can_resume_thread=True,
            can_start_turn=True,
            can_steer_turn=False,
        )

    def start_thread(self, *, actor_id: str, assignment_id: str | None) -> AdapterThread:
        thread_id = f"fake-thread-{next(self._thread_counter)}"
        thread = AdapterThread(
            thread_id=thread_id,
            interactive_url=f"codex://threads/{thread_id}",
        )
        self.threads[thread_id] = thread
        return thread

    def resume_thread(self, *, thread_id: str) -> AdapterThread:
        return self.threads[thread_id]

    def start_turn(
        self,
        *,
        thread_id: str,
        prompt: str,
        client_user_message_id: str,
    ) -> str:
        thread = self.threads[thread_id]
        turn_id = f"fake-turn-{next(self._turn_counter)}"
        thread.active_turn_id = turn_id
        thread.completed_turn_ids.append(turn_id)
        self.prompts[client_user_message_id] = prompt
        return turn_id


class CodexAppServerUnavailable(RuntimeError):
    pass


class CodexAppServerAdapter:
    adapter_kind = "codex_app_server"

    def __init__(self, *, endpoint: str | None = None) -> None:
        self.endpoint = endpoint

    def probe(self) -> AdapterCapabilities:
        if not self.endpoint:
            return AdapterCapabilities(
                adapter_kind=self.adapter_kind,
                can_start_thread=False,
                can_resume_thread=False,
                can_start_turn=False,
                can_steer_turn=False,
            )
        return AdapterCapabilities(
            adapter_kind=self.adapter_kind,
            can_start_thread=True,
            can_resume_thread=True,
            can_start_turn=True,
            can_steer_turn=True,
        )

    def _require_endpoint(self) -> str:
        if not self.endpoint:
            raise CodexAppServerUnavailable("Codex app-server endpoint is not configured")
        return self.endpoint

    def start_thread(self, *, actor_id: str, assignment_id: str | None) -> AdapterThread:
        endpoint = self._require_endpoint()
        raise CodexAppServerUnavailable(
            f"Codex app-server JSON-RPC client is not implemented for {endpoint}"
        )

    def resume_thread(self, *, thread_id: str) -> AdapterThread:
        endpoint = self._require_endpoint()
        raise CodexAppServerUnavailable(
            f"Codex app-server JSON-RPC client is not implemented for {endpoint}"
        )

    def start_turn(
        self,
        *,
        thread_id: str,
        prompt: str,
        client_user_message_id: str,
    ) -> str:
        endpoint = self._require_endpoint()
        raise CodexAppServerUnavailable(
            f"Codex app-server JSON-RPC client is not implemented for {endpoint}"
        )
