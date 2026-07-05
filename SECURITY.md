# Security Policy

## Supported versions

coordination-memory-mcp is pre-1.0. Only the latest published release on the
default branch receives fixes. Pin a version you have reviewed if you need
stability.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** — do not open a public
issue for a security problem.

- Preferred: use GitHub's [private vulnerability reporting][gh-advisory]
  ("Report a vulnerability" under the repository's **Security** tab).
- If private vulnerability reporting is unavailable, use the maintainer contact
  listed at <https://yanqiw.github.io/> and include `SECURITY` in the subject.

Please include:

- the version (`comem --version`) and how you run it
  (MCP client, `serve`, or `dashboard`);
- a description of the issue and its impact;
- minimal steps or a proof of concept to reproduce.

We aim to acknowledge a report within a few business days and to agree on a
disclosure timeline with you. Please give us a reasonable window to ship a fix
before any public disclosure.

[gh-advisory]: https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability

## Scope and threat model

coordination-memory-mcp is a **local-first** tool:

- The MCP server runs over **stdio**, launched by your agent/MCP client. It is
  not a network service.
- The dashboard/console (`comem dashboard`) binds to `127.0.0.1` by default.
  Its read APIs open the database read-only. Its only write action is
  **Archive workspace**, a soft status update for local workspace management.
  Do not expose it on a public interface; it has no authentication and is meant
  for local inspection only.
- State lives in a local SQLite database. Treat that file with the same care as
  any local developer data.

### Data handling invariants

These are guarantees the project intends to keep; a break in any of them is a
security-relevant bug worth reporting:

- Coordination payloads, `probe_spec`, and evidence fields are for **references,
  not secrets**. Do not store credentials, tokens, or other secrets in them, and
  the tools are not designed to protect such data if you do.
- Dashboard read APIs are read-only over the coordination store. The only
  dashboard write path is **Archive workspace**, which soft-updates
  `workspaces.status` and must not delete data, run commands, deploy, or push.

## Out of scope

- Vulnerabilities that require write access to the machine already running the
  server or to the SQLite database file.
- Exposing the unauthenticated local dashboard on an untrusted network (a
  deployment choice, not a product flaw).
