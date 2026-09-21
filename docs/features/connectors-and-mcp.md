# Connectors and MCP

**Problem.** Users add MCP servers (Model Context Protocol connectors) to extend
the agent with third-party tools. In a standalone, local-first product the flow
was broken in several places: locally-added servers never reached the agent, the
picker listed cloud connectors that did not exist locally, and OAuth-based remote
servers could not be authenticated at all.

**Solution.** Make `~/.undisclosed/mcp.json` the single source of truth for local
connectors, give the agent the same file, and add a guided remote-server flow with
a working OAuth bridge.

---

## One source of truth

Local MCP servers are written to `~/.undisclosed/mcp.json`. The agent's MCP config
(`_mcp_config` in `brain/app/agent/factory/toolkit_assembler.py`) merges that file
with any request-provided servers (request wins on name clash), for both single
agent and workforce. Previously it only read the request's `installed_mcp` (a cloud
Connector Gateway), which is null in local mode, so a locally added server never
reached the agent.

The composer picker and the Manage screen both list from the brain
(`/mcp/list`), not from Eigent's hosted cloud account, which also kills the
confusing "4 vs 3 connectors" mismatch and drops an external dependency.

## Adding a connector

`agent-ui/src/components/CodeAgentWorkspace/AgentConnectors.tsx` offers two tabs:

- **Guided**: name + server URL + transport (Streamable HTTP / SSE / OAuth).
  Streamable HTTP and SSE connect directly with an optional Bearer token; OAuth
  generates an `mcp-remote` bridge config (`command: npx mcp-remote <url>`).
- **Paste JSON**: the raw config, for anything the guided form does not cover.

## The OAuth flow (`mcp-remote`)

Many remote MCPs (Notion, Asana, ...) require a browser OAuth consent. The brain's
`/mcp/authenticate` endpoint (`brain/app/controller/mcp_controller.py`) runs the
connector's full configured command (`npx mcp-remote <url> ...`) **outside** the
agent's timeout-bounded task connection, opens the browser for sign-in, and
resolves once the token is cached under `~/.mcp-auth`.

Hard-won details, each a real bug fix:

- **Pre-registered clients** (Asana): dynamic client registration is not always
  allowed, so the guided form collects Client ID/Secret and pins a stable callback
  port (33418), generating
  `mcp-remote <url> 33418 --static-oauth-client-info {client_id,client_secret}`.
- **Redirect URI**: mcp-remote registers `http://localhost:<port>/oauth/callback`,
  not `127.0.0.1`, so the advertised URI must match or the provider rejects it.
- **Success detection**: a re-auth reuses the cached token and mcp-remote stays
  running, so "a new token file appeared" was a false negative. We now detect
  success from mcp-remote's output ("Proxy established" / "Connected to remote
  server") and otherwise surface the real error, including actionable guidance for
  the "does not support dynamic client registration" case.
- **Persisted state**: on success the connector is recorded in
  `~/.undisclosed/mcp_authed.json`; `GET /mcp/auth-status` (filtered to servers
  still in the config) lets the row show a green "Authenticated" button across
  reloads. It stays clickable to re-auth.

## Steganographic failure mode we fixed

Several early bugs made failures look like "nothing happened": mcp-remote output
was sent to `/dev/null`, and the embed never mounted the `<Toaster/>`, so toasts
were invisible. Both are fixed; the embed now portals a Toaster to `<body>`.

## Where it lives

- Backend: `brain/app/controller/mcp_controller.py`, `brain/app/agent/factory/toolkit_assembler.py`
- Frontend: `agent-ui/src/components/CodeAgentWorkspace/AgentConnectors.tsx`, `ChatBox/BottomBox/PickerPanel.tsx`, `api/brain.ts`

## Key commits

`a2a3503` (guided remote form), `d655244` (local-only picker + authenticate),
`ad5f7bd` (pre-registered client), `208b51a` (surface the real error),
`9c5dad3` (stale client id/secret deps), `ffe91d8` (OAuth success detection),
`1c606d3` (Authenticated state), `f6386b6` (persist across reloads),
`87795e5` (mount the Toaster).
