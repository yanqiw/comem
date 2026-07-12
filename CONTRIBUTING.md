# Contributing

Thanks for your interest in improving coordination-memory-mcp.

## Development setup

This project uses [uv](https://github.com/astral-sh/uv) for environment and task
management (a `uv.lock` is committed for reproducible installs).

```bash
# from the project root
uv sync            # create the venv and install deps + dev tools
uv run pytest -q   # run the test suite
```

The package has one runtime dependency (`mcp`) and uses only the Python standard
library beyond that (SQLite, `http.server`). The dashboard source is Svelte/Vite;
the built static assets are checked into `src/coordination_memory_mcp/static/`.

## Running locally

```bash
# MCP server (stdio; usually launched by an MCP client)
uv run comem serve

# Local dashboard / console
COORDINATION_MEMORY_DB=/absolute/path/to/coordination.sqlite3 \
  uv run comem dashboard --host 127.0.0.1 --port 8765
```

## Tests

Write tests with `pytest`. The store layer is pure synchronous SQLite and is the
unit-test surface; the console is covered by HTTP round-trip tests. Run the full
suite before opening a pull request:

```bash
uv run pytest -q
```

When you change the dashboard source, also run the frontend checks if you have
Node available:

```bash
npm run check
node --check src/coordination_memory_mcp/static/app.js
```

## Lint and types

CI gates on ruff and mypy in addition to tests. Run them locally before pushing:

```bash
uv run ruff check src tests          # lint
uv run ruff format --check src tests # formatting
uv run mypy src                      # type check
```

Optionally install the git hooks so lint/format run on every commit:

```bash
uv run pre-commit install
```

## Invariants to preserve

These are not style preferences; they are the project's guarantees. PRs that break
them will be rejected:

- **Dashboard read APIs are read-only.** They open the DB with `mode=ro` +
  `query_only`. The only dashboard write is **Archive workspace**, a soft
  `workspaces.status` update; it must never delete data, run shell commands,
  deploy, or push.
- **No secrets in the store.** Coordination payloads, contract `probe_spec`,
  verification `evidence`, and audit events record references only (paths,
  commits, hashes) — never `.env` contents, tokens, passwords, private keys, or
  credential-bearing logs.
- **The dashboard never injects untrusted data via application-authored
  `innerHTML`.** Bind data as text. Read APIs use `GET`; the workspace archive
  action uses `POST` only for the soft status update.
- **Acceptance-contract gates live in `store.py`, not in any prompt or client.**
  Enforcement must be in the store layer so it cannot be bypassed.
- **Optimistic concurrency.** Every mutating assignment/contract write carries a
  `base_revision` and bumps the revision; append-only probe results do not.
- **Human projections do not become workflow state.** `checkpoint_run` never
  changes assignment/run status or creates Attention. Yellow/green Attention is
  non-blocking; red is derived only from an unresolved intervention on the
  active run. Resume Briefs are for people, not agent execution recovery.

## Pull requests

- Keep changes focused; one logical change per PR.
- Include tests for behavior changes.
- Make sure `uv run pytest -q`, `uv run ruff check`, and `uv run mypy src` are
  all green.
- Update `CHANGELOG.md` (Unreleased) for user-facing changes.
- Describe what changed and why in the PR body.

## License

By contributing, you agree that your contributions are licensed under the MIT
License (see `LICENSE`).
