# Quickstart

## 1. Install

```bash
uv tool install coordination-memory-mcp   # or: pipx install coordination-memory-mcp
comem --help
```

The package is `coordination-memory-mcp`; the command is `comem`.
To run without installing: `uvx --from coordination-memory-mcp comem --help`.

## 2. Run the MCP server

```bash
COORDINATION_MEMORY_DB=/absolute/path/coordination.sqlite3 comem serve
```

`serve` speaks stdio and is normally launched by an MCP client, not by hand. Pick
a database path **outside** every worktree so collaborating agents share one
store. Never commit the SQLite file.

## 3. Configure your MCP client

```json
{
  "mcpServers": {
    "coordination-memory": {
      "command": "comem",
      "args": ["serve"],
      "env": { "COORDINATION_MEMORY_DB": "/absolute/path/coordination.sqlite3" }
    }
  }
}
```

## 4. Teach your agents the protocol

```bash
comem init                 # AGENTS.md + all tool adapters
comem init --tools claude  # just the Claude Code skill
```

This writes a canonical protocol section into `AGENTS.md` (idempotently) plus
per-tool adapters. See [Set up your agent](https://github.com/yanqiw/comem#set-up-your-agent)
table for what lands where.

## 5. Open the dashboard

```bash
comem dashboard --db /absolute/path/coordination.sqlite3
```

Open <http://127.0.0.1:8765/>. Read APIs are read-only; the only write action is
**Archive workspace**, a local soft status update.

## Next

- Understand the model: [Concepts & governance](concepts.md).
- See it end-to-end: [Examples](examples.md).
