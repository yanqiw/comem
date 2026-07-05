# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html): tag a
release `vMAJOR.MINOR.PATCH`, which triggers the build-and-publish workflow.

## [Unreleased]

### Added
- `cancel_assignment` and `supersede_assignment` MCP tools (integrator-only):
  give an assignment a clean terminal exit besides accept/reject. Both release
  any active lease, end the in-flight run, and append an audit event;
  `supersede_assignment` also records `superseded_by` on the assignment.
- Unified `comem` CLI with `serve`, `dashboard`, `init`, and `loop`
  subcommands.
- `comem init` scaffolds agent-onboarding files into a repo: a
  canonical `AGENTS.md` protocol section (idempotent, between markers) plus
  Claude skill / Cursor / Copilot adapters. Supports `--tools`, `--dir`,
  `--force`.
- Code-quality tooling: ruff (lint + format), mypy, pre-commit, and CI lint +
  typecheck gates.
- Release workflow: build + publish to PyPI on a `v*` tag via Trusted
  Publishing.

### Documentation
- Restructured README for OSS (badges, one-command quickstart, "Set up your
  agent") and added a `docs/` set (quickstart, concepts, tool reference,
  examples) with a dashboard screenshot.
- Community health: `CONTRIBUTING.md` (dev setup, lint/type, PR flow),
  `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md`, and GitHub
  issue/PR templates.

### Changed
- Dashboard detail pages restructured for readability (acceptance criteria as a
  checklist, structured event rows, richer cards).
- **Breaking:** replaced the two flat console scripts
  (`coordination-memory-mcp`, `coordination-memory-console`) with the single
  `comem` entry point. Update MCP client configs to
  `command: "comem", args: ["serve"]`.

## [0.1.0]

- Initial coordination-memory MCP server, read-only console, goal-level
  acceptance contracts, and the integrator-owned accepted Git projection.
