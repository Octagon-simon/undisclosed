# Undisclosed

**An on-device AI coding editor.** At its core it is a customized [Eclipse Theia](https://theia-ide.org/)
editor with an AI coding agent built in as a **native panel that lives inside the
editor** - the agent is not docked next to a separate window the way it works in
other tools. It plans, reads, writes and runs code against your actual
workspace, right where you edit.

Everything runs locally by default: your code, the editor, and the agent "brain"
(the model orchestration). You bring your own model keys (BYOK) and nothing is
sent to a vendor cloud.

The project began as two decoupled halves: the **agent capability** is from
[Eigent](https://eigent.ai), while the **editor shell + on-device packaging** here
are our own. Both are fused here into a single editor-first product - the "Antigravity"
model.

> **Branch:** this is the `upgrade/theia-1.76` branch. The editor stack here is
> **Theia 1.76 on Node 24** (Electron 42), up from Theia 1.60 on Node 20 on `main`.
> Upgrade notes: [`docs/plans/theia-upgrade-plan.md`](docs/plans/theia-upgrade-plan.md);
> override register: [`docs/features/theia-overrides.md`](docs/features/theia-overrides.md).

---

## Highlights

- **Agent-native editor shell** built on Eclipse Theia (not a fork of VS Code), 100%
  open-source (Apache-2.0). The agent panel (a React app) is served and mounted as a
  first-class dock widget by a Theia extension.
- **It can actually touch your workspace**: terminal, file read/write, git, search,
  debugging, browser + screenshots, web search - via selectable "hands". The agent
  plans in your editor and executes changes you can see and review.
- **Runs on-device**. The "brain" is a local FastAPI (uvicorn) agent backend. No SaaS
  runtime, no vendor cloud. Model calls use the keys *you* configure (OpenAI, Gemini,
  and more).
- **Storybook + hot reload** for fast agent-UI iteration, separate from the slow full
  editor rebuild.
- **Installable desktop app** (Electron + frozen Python brain) for macOS / Windows /
  Linux, plus a ready-to-package release pipeline.
- **Extensible**: Monaco/Monarch custom languages, VS Code settings + extension
  import, git extras, and a skill system for the agent.

---

## What's in the box

Two local processes keep the editor and the agent separate:

| Process | What it is | Listens on |
| --- | --- | --- |
| **Editor** | Theia + the `undisclosed-*` extensions + the embedded agent UI | `:3000` (dev, browser) |
| **Brain** | FastAPI / uvicorn agent backend (model routing, toolkits/hands, memory, SSE streaming) | `:5001` |

The agent UI (`agent-ui/`) is a React + Vite app. A self-contained UMD module is built
and copied into the `undisclosed-agent` Theia extension, which serves it and mounts it
in the **right-side panel**. In development the brain runs as its own process
(`scripts/brain.sh`); in the packaged desktop app it is **frozen with PyInstaller** and
auto-launched alongside Electron.

```
┌───────────────────────────────────────────────┐     ┌───────────────────────────────┐
│  Editor surface (Theia + undisclosed-agent)   │     │   Brain  (FastAPI, :5001)      │
│   · editor / terminal / git / file explorer   │     │   · model routing/streaming    │
│   · agent panel = native dock widget (React)  │◄───►│   · hands: shell, files, git,  │
│      ┌──────────┐                             │/api │     browser, search, skills    │
│      │  Agent UI │  ── /api & SSE ─────────────┴────►│   · memory (vector) + history │
└──────┴──────────┴─────────────────────────────┘     └───────────────────────────────┘
       In dev the browser proxies /api on :3000 → brain; in the packaged app the
       Theia/Electron backend proxies /api straight to the bundled brain.
```

---

## Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| **Node** | **24** (use `nvm use 24`) | Theia 1.76 requires Node >= 24; native modules are built for it |
| **Python** | **3.11** | The brain; also node-gyp needs `distutils` (removed in 3.12) when packaging native modules |
| **uv** | latest | Provisions the brain's venv from `brain/pyproject.toml` |

An `.nvmrc` pins Node 24. Copy `.env.sample` → `.env` for any model keys / tuning. Every
variable is optional - the app runs with sane defaults (see [Environment variables](#environment-variables)).

---

## Quick start (development)

From a fresh clone you need three things: **Node 24**, **Python 3.11**, and **uv**
(see [Prerequisites](#prerequisites)). You also need a **workspace folder** open for the
agent to act on.

**0. Point at a model (optional).** Copy the sample env and add any keys you want. Every
variable is optional and the app runs with sane defaults:

```bash
cp .env.sample .env
```

**1. Start the brain** (agent backend, `:5001`):

```bash
./scripts/brain.sh setup      # once - provisions brain/.venv via uv
./scripts/brain.sh start      # start (or: restart | stop | logs | status)
```

**2. Install, build and start the editor** (Theia, `:3000`):

```bash
nvm use 24                    # Node 24 (.nvmrc); Theia 1.76 requires it
npm install                   # root deps (Theia + the file: packages/*)
npm run build                 # compile packages/* then bundle the editor (dev mode)
npm start                     # -> http://127.0.0.1:3000
```

`npm run build` first compiles the four `packages/*` Theia extensions with `tsc`
(`build:packages`: `undisclosed-agent`, `undisclosed-git`, `undisclosed-import`,
`undisclosed-languages`) and then bundles the editor with Theia 1.76's **esbuild**
builder. Both matter: the extensions' `lib/` output is gitignored, so a fresh clone has
nothing for Theia to load until you build them. Open `http://127.0.0.1:3000`, open a
workspace folder, add a model in the agent panel's **Models** UI, then talk to the agent.

> The agent panel's UI bundle is **committed** to the repo
> (`packages/undisclosed-agent/assets/agent-embed/`), so a normal dev build needs
> nothing from `agent-ui/`. Rebuild it only when you are editing the agent UI (below).

Prefer one command? `./scripts/dev.sh start` brings up the brain and the editor
together, and `./scripts/dev.sh rebuild` does a full refresh (it pins Node 24 for you).

### Working on the agent UI

The editor's agent panel is `agent-ui/` (React + Vite). For component work use
**Storybook** (hot reload, no editor rebuild):

```bash
cd agent-ui && npm install && npm run storybook   # -> http://localhost:6006
```

To rebuild the embed bundle that the editor ships, and refresh the committed copy:

```bash
npm run build:agent-ui   # vite build -> packages/undisclosed-agent/assets/agent-embed/
```

> `agent-ui/` uses a locally patched `@stackframe/react` at
> `agent-ui/package/@stackframe/react`. That directory is gitignored, so it is **not**
> in a fresh clone and `npm install` inside `agent-ui/` fails until it is restored.
> The committed embed bundle is exactly why a normal editor dev build does not need it.
> `scripts/release.sh` runs `npm run build:agent-ui` as its pre-tag gate on a machine
> that has the patch.

### Debugging

Set `UNDISCLOSED_DEBUG=1` (in `.env`) to dump each turn's prompt, tool calls, model
response and streamed chunks to the brain log and `~/.undisclosed/debug/<task>.log`.
In the browser devtools console, `localStorage.setItem('undisclosed_debug','1')`
mirrors this on the frontend.

---

## Try a packaged desktop app

`apps/desktop/` is the **Electron** Theia shell that bundles both the editor and the
brain (frozen with PyInstaller) into one installable app and auto-launches the brain on
open - no separate processes, no browser tab. Build artifacts land under
`apps/desktop/dist/` (e.g. a `.dmg` for macOS).

The prebuilt images are **unsigned** (self-install). On first open on macOS:
right-click the app → **Open**, or `xattr -cr /Applications/Undisclosed.app`.

### Building the installer locally

One command freezes the brain, builds the agent UI, and packages:

```bash
nvm use 20
export npm_config_python="$PWD/brain/.venv/bin/python"   # node-gyp needs Python 3.11
npm run desktop:install                                  # once — apps/desktop node_modules
npm --prefix apps/desktop run rebuild                    # native modules → Electron ABI
npm run dist:mac        # also dist:win / dist:linux → apps/desktop/dist/*
```

Full details + troubleshooting: **[docs/PACKAGING.md](docs/PACKAGING.md)**.

---

## Cut a release

Releases are **tag-driven**: CI builds installers on native runners and attaches them to
a GitHub Release.

Before tagging, reproduce CI locally so a broken lockfile / plugin download / build fails
here instead of burning a CI run:

```bash
./scripts/preflight-ci.sh --full            # real install + rebuild + build + plugin download
./scripts/preflight-ci.sh --full --package  # ...and package (electron-builder --dir)
./scripts/preflight-ci.sh                   # fast: workflow YAML + lockfile sync + syntax only
```

`--full` runs the real install/build on THIS machine (host platform only), so it can't see
Windows/Linux-only problems. Then release:

```bash
npm run release [patch|minor|major]
```

This gates on `npm run build:agent-ui`, bumps the version, commits, tags `vX.Y.Z`, and
pushes. The workflow (`.github/workflows/release.yml`) then builds on native runners
(Linux `AppImage`/`deb`, Windows `nsis`, and **macOS for both Apple Silicon and Intel**
via `macos-15` + `macos-15-intel`) and attaches the installers to the Release. macOS
builds are **unsigned**: fine for self-install (right-click -> Open), but they warn
under Gatekeeper until Developer ID signing/notarization is configured. The app id /
product name / copyright used by packaging live in `apps/desktop/electron-builder.yml`.

---

## Repository layout

```
agent-ui/            Agent UI (React + Vite) → built to a self-contained UMD bundle
brain/               FastAPI agent backend ("the brain"); uv + pyproject.toml;
                     the /api surface (providers, spaces, history, chat)
packages/
  undisclosed-agent/       Theia extension: hosts the agent dock panel, the proxy,
                           layout & git extras; brain launcher (desktop)
  undisclosed-git/         SCM fixes: staged changes open editable (save works),
                           plus inline diff / commit-widget styling
  undisclosed-languages/   Monaco/Monarch language support + native media preview
  undisclosed-import/      VS Code settings/extensions import
  agent-net/               Framework-agnostic transport (fetch + SSE) shared by the
                           agent widget and the Electron app
apps/desktop/        Electron Theia app (packaging target; electron-builder.yml)
scripts/             brain.sh, build-brain.sh (PyInstaller), release.sh, dev.sh
docs/                PACKAGING.md, design & dev notes (assistant_message_persistence.md)
docker-compose.yml   Optional containerized brain (dev convenience)
```

---

## Environment variables

Configuration is read from **`.env`** (repo root) or **`brain/.env`** - both are loaded
by the brain at startup and gitignored. Precedence: these files use `override=True`, so
they win over shell `export`s (once a var is here it is the source of truth). See
`.env.sample` for the full annotated list.

Notable groups:

- **Server**: `UNDISCLOSED_BRAIN_PORT` (default `5001`), `UNDISCLOSED_BRAIN_HOST`,
  `UNDISCLOSED_PROXY_TARGET` (override where the Theia backend sends `/api` calls).
- **Agent behavior**: per-step timeout, memory window, extended *thinking* (effort /
  budget), tool-RAG (expose only the tools relevant to a turn) and deferred/lazy
  browser + screenshot toolkits, debug mode (`UNDISCLOSED_DEBUG`), storage overrides
  (`~/.undisclosed/`).
- **Model / LLM keys (BYOK)**: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`.
  Most provider/model setup is configurable inside the app's Models UI; these vars are
  read directly where a toolkit needs a key without a UI-configured provider.
- **Design/dev integrations** (each enables its corresponding agent toolkit **only when
  set**): `FIGMA_ACCESS_TOKEN`, `GITHUB_ACCESS_TOKEN`, `MONGO_URL`. The GitHub toolkit
  (needs the `PyGithub` package declared in `brain/pyproject.toml`) covers issue
  create/update/close/reopen, issue and PR comments, PR create/merge/close, branch
  create/list, repository listing, and cross-repo issue search. The MongoDB toolkit is
  a **read-only** query surface (find/count/distinct/aggregate plus a write-guarded
  escape hatch) run through the `mongosh` CLI; it redacts the connection string from
  every result and error, defaults to the `dev` database (`MONGO_DB` to override), and
  never enables without a connection string.
- **Web search** (any one enables web search): Google PSE (key+engine id), Tavily,
  Brave, Exa, Linkup, Bocha.
- **Productivity/comms**: Notion, Slack, Google Workspace (Gmail/Calendar/Drive OAuth +
  token paths), social (Twitter/X, LinkedIn, Reddit, WhatsApp), Lark/Feishu.
- **Browser (CDP)**: point the brain at a running Chrome via `UNDISCLOSED_CDP_URL`,
  or override the launched browser / command timeout.

> Frontend (build-time) vars live in **`agent-ui/.env`**, not the root `.env` - Vite
> reads only vars prefixed `VITE_` into the browser bundle (`VITE_BRAIN_ENDPOINT`,
> `VITE_BASE_URL`, `VITE_PROXY_URL`, `VITE_APP_VERSION`).

---

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Editor won't build ("Python 3.12 / distutils") | Use Node 24 + Python 3.11; `nvm use 24`, and point node-gyp at the venv python before packaging (`export npm_config_python=...`). |
| Agent panel shows a proxy/api error when adding a model | The `/api` proxy must target the **brain** (`:5001`), not a legacy `:3001` cloud proxy. In dev run via `scripts/dev.sh` (sets the target) or in `.env` set `UNDISCLOSED_PROXY_TARGET=http://127.0.0.1:5001`. |
| Brain won't start | Ctrl+C a prior `uv run ...` may leave `uv_installing.lock`/`uv_installed.lock` in `brain/` - delete them, then `./scripts/brain.sh setup`. |
| Packaged app is unsigned on macOS | Right-click → Open, or `xattr -cr /Applications/Undisclosed.app`. See `docs/PACKAGING.md` for signing/notarization. |
| CI hangs forever at `collecting extension dependencies` | `theia download:plugins` talks to open-vsx over sockets with no timeout, and its "already downloaded - skipping" lines don't stop it running (or hanging) anyway. CI uses `scripts/ci-download-plugins.sh`: it skips the tool entirely when the pinned plugins are already present, bounds each attempt with a hard cap, and stops the tool as soon as the plugins verify. Reproduce locally with `bash scripts/ci-download-plugins.sh`. |

On the browser side you can run the whole stack from one terminal with
`./scripts/dev.sh`, which manages the brain + editor together (and defaults the proxy
target to `:5001`).

---

## License

Apache-2.0. Portions © Eigent.ai (preserved per Apache-2.0); the on-device editor
shell, packaging, and new features © Simon Ugorji. See per-file headers.
