# OSS Launch Checklist

This checklist captures the week-one launch work for Coordination Memory MCP.

## Current Public State

- GitHub repository: `https://github.com/yanqiw/comem`
- Current package version in `pyproject.toml`: `0.2.4`
- Public GitHub description observed through the API: `Agent Team coordination memory`
- Public GitHub topics observed through the API: none
- Public GitHub Discussions observed through the API: disabled
- Public GitHub releases/tags observed through the API: none
- PyPI package `coordination-memory-mcp`: not found at the JSON endpoint before
  release
- PyPI pending Trusted Publisher: configured by the project owner for GitHub
  Actions release workflow
- Local GitHub CLI auth: invalid token; authenticated repository settings and
  release actions require owner re-authentication
- `mcp-publisher`: not installed locally

## Repository Settings

Set these in GitHub before announcing broadly:

- Description:
  `Local MCP coordination layer for multi-agent coding: task leases, auditable handoffs, independent acceptance contracts.`
- Website:
  `https://github.com/yanqiw/comem`
- Topics:
  `mcp`, `model-context-protocol`, `ai-agents`, `multi-agent`,
  `agent-orchestration`, `local-first`, `sqlite`, `developer-tools`,
  `governance`
- Enable Discussions.
- Keep Issues enabled.
- Keep the security advisory link active.

## Release Path

1. Re-authenticate GitHub CLI or use the GitHub UI with owner permissions.
2. Configure PyPI Trusted Publishing for:
   - PyPI project: `coordination-memory-mcp`
   - Repository: `yanqiw/comem`
   - Workflow: `.github/workflows/release.yml`
   - Environment: `pypi`
   - Status: configured
3. Ensure the release commit includes:
   - `pyproject.toml` version `0.2.4`
   - `CHANGELOG.md` release section `0.2.4`
   - README install instructions
   - README MCP Registry marker: `mcp-name: io.github.yanqiw/comem`
   - `server.json`
4. Tag and push:

```bash
git tag v0.2.4
git push origin v0.2.4
```

5. Wait for the Release workflow to publish to PyPI.
6. Verify:

```bash
curl https://pypi.org/pypi/coordination-memory-mcp/json
uvx --from coordination-memory-mcp comem --help
```

## MCP Registry

The MCP Registry uses metadata only; the PyPI package must exist first.

```bash
mcp-publisher login github
mcp-publisher publish
```

The committed `server.json` is prepared for the registry name
`io.github.yanqiw/comem` and package `coordination-memory-mcp`.

## Directory Submissions

- MCP Registry: publish with `mcp-publisher` after PyPI is live.
- Glama: submit the GitHub repository and package metadata.
- `awesome-mcp-servers`: open a PR with one concise entry under the most relevant
  agent/developer-tools section.

## Launch Gate

Do not post the launch announcement until these are true:

- PyPI package resolves.
- `uvx --from coordination-memory-mcp comem --help` works on a clean machine.
- GitHub description/topics are set.
- Discussions is enabled.
- README links to launch resources and demo script.
- The dashboard screenshot renders in GitHub.
