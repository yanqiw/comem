"""Scaffold agent-onboarding files into a target repository.

`comem init` writes a canonical ``AGENTS.md`` protocol section
(idempotently, between markers) plus thin per-tool adapters that point back to
it. Templates ship as package data under ``templates/``.
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from pathlib import Path

MARKER_START = "<!-- coordination-memory:start -->"
MARKER_END = "<!-- coordination-memory:end -->"

# tool -> (template filename, output path relative to the target repo)
ADAPTERS: dict[str, tuple[str, str]] = {
    "claude": ("claude-skill.md", ".claude/skills/coordination-memory/SKILL.md"),
    "cursor": ("cursor.mdc", ".cursor/rules/coordination-memory.mdc"),
    "copilot": ("copilot-instructions.md", ".github/copilot-instructions.md"),
}
# codex and opencode read AGENTS.md directly; they need no separate adapter file.
ALL_TOOLS: list[str] = ["claude", "codex", "cursor", "copilot", "opencode"]


@dataclass
class InitResult:
    agents_action: str  # "created" | "updated" | "appended"
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    mcp_config: str = ""


def _read_template(name: str) -> str:
    return (
        importlib.resources.files("coordination_memory_mcp")
        .joinpath("templates", name)
        .read_text(encoding="utf-8")
    )


def _protocol_block() -> str:
    body = _read_template("AGENTS.section.md").rstrip("\n")
    return f"{MARKER_START}\n{body}\n{MARKER_END}\n"


def _upsert_agents_md(path: Path) -> str:
    """Create/update the protocol block in AGENTS.md without duplicating it."""
    block = _protocol_block()
    if not path.exists():
        path.write_text("# Agent instructions\n\n" + block, encoding="utf-8")
        return "created"

    text = path.read_text(encoding="utf-8")
    if MARKER_START in text and MARKER_END in text:
        pre = text[: text.index(MARKER_START)]
        post = text[text.index(MARKER_END) + len(MARKER_END) :]
        path.write_text(pre + block.rstrip("\n") + post, encoding="utf-8")
        return "updated"

    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    path.write_text(text + sep + block, encoding="utf-8")
    return "appended"


def normalize_tools(tools: list[str] | None) -> list[str]:
    if not tools:
        return list(ALL_TOOLS)
    parts = [p.strip() for raw in tools for p in str(raw).split(",")]
    parts = [p for p in parts if p]
    if not parts or "all" in parts:
        return list(ALL_TOOLS)
    out: list[str] = []
    for part in parts:
        if part not in ALL_TOOLS:
            raise ValueError(f"unknown tool: {part!r} (choose from {', '.join(ALL_TOOLS)})")
        if part not in out:
            out.append(part)
    return out


def run_init(
    target_dir: str | Path,
    tools: list[str] | None = None,
    force: bool = False,
) -> InitResult:
    base = Path(target_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    selected = normalize_tools(tools)

    result = InitResult(agents_action=_upsert_agents_md(base / "AGENTS.md"))
    result.written.append("AGENTS.md")

    for tool in selected:
        if tool not in ADAPTERS:
            continue  # codex / opencode use AGENTS.md directly
        template_name, rel = ADAPTERS[tool]
        out = base / rel
        if out.exists() and not force:
            result.skipped.append(rel)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_read_template(template_name), encoding="utf-8")
        result.written.append(rel)

    result.mcp_config = _read_template("mcp-config.json")
    return result
