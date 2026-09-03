# @eigent/agent-net

Framework-agnostic transport for Eigent's agent — the seam that makes the agent
UI portable. Everything is **injected**: backend base URL, auth token, user id,
and host capabilities. **No Electron, no `authStore`, no IPC.** The Theia agent
widget and the Electron app both drive the same code.

## Exports

- `createHttpClient(config)` — fetch client; attaches `Authorization: Bearer`
  only to Brain-relative paths (absolute URLs stay tokenless), mirroring the
  app's `shouldAttachAuthHeader` rule.
- `openAgentStream(config, path, handlers, options)` — SSE via
  `@microsoft/fetch-event-source` (`openWhenHidden`), config-injected auth,
  fast-fails on a non-`text/event-stream` open.
- `AppHost` + `noopHost` — the complete host-capability surface the agent stack
  uses (audited); adapters implement only what they can. Callers feature-detect.
- `AgentNetConfig` — `{ baseUrl, getToken?, getUserId?, getSessionId? }`.

## Probe (proof it drives the backend standalone)

```bash
nvm use
npm install && npm run build

# transport + client, no auth needed (Brain /health is open):
UNDISCLOSED_BASE_URL=http://localhost:5001 npm run probe

# a REAL streaming turn (starts a billable agent run — your call):
UNDISCLOSED_BASE_URL=http://localhost:5001 \
UNDISCLOSED_TOKEN=<token> UNDISCLOSED_USER_ID=<id> \
UNDISCLOSED_SSE_PATH=/chat UNDISCLOSED_SSE_BODY='<the /chat json body>' \
npm run probe
```

> `src/node-shim.ts` is a node-only `window`/`document` stub for the probe
> (fetch-event-source is browser-targeted). The Theia target is a browser and
> never imports it.

## Status

First cut proven against a live Brain (2026-08-28): transport `GET /` 200;
`get('/health')` parsed JSON; SSE open + content-type guard. Next: lift the
auth/project/space stores behind this layer, then bring `ChatBox`.
