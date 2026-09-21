# Remote sub-agent

**Problem.** Some tasks are better delegated to a hosted agent runtime (long
horizon, provider-specific strengths) than run locally. We want that as an opt-in
capability without coupling the local agent to a vendor.

**Solution.** `brain/app/remote_sub_agent/` is a small provider abstraction: the
local agent can hand a bounded task to a remote agent provider and get the result
back, gated by config and policy.

**Status:** present in the codebase but **disabled by default**
(`RemoteSubAgentConfig.enabled = False`). Treat this doc as orientation, and read
the module before wiring it on.

---

## Shape

```
brain/app/remote_sub_agent/
  config.py             RemoteSubAgentConfig(enabled, provider, providers...)
  constants.py          DEFAULT_REMOTE_SUB_AGENT_PROVIDER = "gemini_agents"
  provider_registry.py  maps provider name -> provider impl
  providers/            provider implementations
  runtime.py            the delegation runtime (session lifecycle)
  session_store.py      durable session state
  policy.py             limits: snapshot size, download allowance, time
  types.py
```

`config.py` shows the config model: a top-level `enabled` flag, a `provider`
name, and per-provider config (e.g. `gemini_agents` with `api_key`, `base_url`,
`agent_name`, `max_wall_time_seconds`, `poll_interval_seconds`).

## Policy limits

`policy.py` bounds the delegation so it cannot become an unbounded or
data-exfiltrating channel:

- `max_snapshot_bytes` default 50 MB
  (`UNDISCLOSED_REMOTE_SUB_AGENT_MAX_SNAPSHOT_MB`)
- snapshot download allowance
  (`UNDISCLOSED_REMOTE_SUB_AGENT_ALLOW_SNAPSHOT_DOWNLOAD`)

The runtime polls the provider session (with `poll_interval_seconds`) up to
`max_wall_time_seconds`, and `session_store.py` persists session state so a
restart does not orphan an in-flight delegation.

## Config

All `UNDISCLOSED_REMOTE_SUB_AGENT_*` (see `.env.sample`). Off unless enabled.

## Where it lives

`brain/app/remote_sub_agent/` and the `remote_sub_agent_toolkit.py` that exposes
it to the agent.
