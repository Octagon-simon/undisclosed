# Hands and deployments

**Problem.** The brain can run in several places: on the user's own machine (the
default), on a cloud VM, or inside a sandbox/Docker container. What it is *allowed
to touch* must differ. A container must not have full filesystem or a browser; a
local install should. Hardcoding capabilities would either break the sandbox or
over-grant it.

**Solution.** A capability model ("hands") derived from the deployment type, with
env overrides, deciding filesystem scope, terminal, browser, and MCP access.

---

## The capability set

`brain/app/hands/capabilities.py` defines `BrainCapabilities`, detected once at
startup:

| Dimension | Values |
| --- | --- |
| filesystem | `full` \| `workspace_only` \| `none` |
| terminal | on / off |
| browser | on / off (CDP) |
| mcp | `all` \| `allowlist` |

The decision is two-layer:

1. **Deployment** (`UNDISCLOSED_DEPLOYMENT_TYPE` / Docker auto-detect):
   - `local` / `cloud_vm` (or unset) -> full capabilities.
   - `sandbox` / `docker` / `container` -> limited (workspace-only filesystem, no browser; MCP still available).
   - Docker auto-detect: a container is downgraded to limited **unless** the
     operator explicitly sets `UNDISCLOSED_DEPLOYMENT_TYPE=local` as an escape
     hatch (for a container on your own machine with a mounted project folder).
     Without the explicit override, workspace/folder binding 412s because binding
     requires `deployment == "local"`.
2. **Env overrides** (`UNDISCLOSED_HANDS_*`): `TERMINAL`, `BROWSER`, `FILESYSTEM`,
   `MCP`, `MCP_ALLOWLIST`. These win over detection.

The browser hand is advertised only when a CDP endpoint is configured/reachable
(`UNDISCLOSED_CDP_URL`, `~/.undisclosed/cdp.json`, or the Electron CDP pool),
the runtime is Electron, or a local browser can be provisioned (see
[browser-automation.md](browser-automation.md)).

## Remote cluster mode

`UNDISCLOSED_HANDS_MODE=remote` switches to `RemoteHands`, where resources live on
a remote cluster. The recommended configuration is a TOML file:

```bash
cp backend/config/hands_clusters.example.toml ~/.undisclosed/hands_clusters.toml
export UNDISCLOSED_HANDS_MODE=remote
export UNDISCLOSED_HANDS_CLUSTER_CONFIG_FILE=~/.undisclosed/hands_clusters.toml
```

The hands implementations live in `brain/app/hands/`: `full_hands.py`,
`sandbox_hands.py`, `remote_hands.py`, `environment_hands.py`, plus the cluster
interfaces (`cluster_interface.py`, `http_hands_cluster.py`,
`routed_hands_cluster.py`, `cluster_config.py`).

## Why a channel is not a capability

An explicit design principle in the module: a *channel* (Slack, email, the panel)
only affects how messages are displayed, never what the brain can reach. Keeping
those orthogonal is what lets the same brain serve the editor panel and a chat
channel with one capability policy.

## Where it lives

- `brain/app/hands/capabilities.py` (detection)
- `brain/app/hands/*.py` (implementations)
- Documented in `.env.sample` and `brain/README.md`.

## Key references

`UNDISCLOSED_DEPLOYMENT_TYPE`, `UNDISCLOSED_HANDS_*`, `UNDISCLOSED_WORKSPACE`,
`UNDISCLOSED_CDP_URL`, `UNDISCLOSED_HANDS_CLUSTER_CONFIG_FILE`. See `.env.sample`.
