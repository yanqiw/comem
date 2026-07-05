<!-- Thanks for contributing! Keep PRs focused: one logical change per PR. -->

## What and why

What does this change, and why?

Closes #

## Checklist

- [ ] `uv run pytest -q` is green
- [ ] `uv run ruff check src tests` and `uv run ruff format --check src tests` pass
- [ ] `uv run mypy src` passes
- [ ] Updated `CHANGELOG.md` (Unreleased) for user-facing changes
- [ ] Updated docs (`README.md` / `docs/`) if behavior or interfaces changed
- [ ] Preserves project invariants (dashboard read APIs are read-only; archive is
      a soft local status update; acceptance gates; no secrets in payloads) —
      see [CONTRIBUTING.md](../CONTRIBUTING.md)

## Notes for reviewers

Anything that needs special attention, follow-ups, or known limitations.
