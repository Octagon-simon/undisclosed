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
| **Node** | **18-20** (use `nvm use 20`) | Theia + its native modules don't build on Node 22/24 |
| **Python** | **3.11** | The brain; also node-gyp needs `distutils` (removed in 3.12) when packaging native modules |
| **uv** | latest | Provisions the brain's venv from `brain/pyproject.toml` |

An `.nvmrc` pins Node 20. Copy `.env.sample` → `.env` for any model keys / tuning. Every
variable is optional - the app runs with sane defaults (see [Environment variables](#environment-variables)).

---

## Quick start (development)

Run the brain in the background (it auto-restarts), then start the editor. You need a
**workspace folder** open for the agent to act on.

**1. Start the brain** (agent backend, `:5001`):

```bash
./scripts/brain.sh setup      # once — provisions brain/.venv via uv
./scripts/brain.sh start      # start (or: restart | stop | logs | status)
```

**2. Build the agent UI bundle** and sync it into the editor extension (needed once,
or after UI changes in `agent-ui/`):

```bash
npm run build:agent-ui
```

**3. Install, build & start the editor** (Theia, `:3000`):

```bash
nvm use 20
npm install
npm run build                 # webpack the frontend + generate the backend
npm start                     # → http://127.0.0.1:3000
```

Open `http://127.0.0.1:3000` and open a workspace folder. Add a model (providers can be
configured in the agent panel's Models UI), then talk to the agent.

> **Tip:** after `npm install`, also run `npm install` inside each `packages/*` (
> `undisclosed-agent`, `undisclosed-languages`, `undisclosed-import`) and `tsc` them if
> the extension sources changed. The package.json at root wires these as
> `file:` dependencies, but watch/watch-free rebuild still needs them built once.

### Faster inner loop for the agent UI

Rebuilding the whole Theia editor to see one UI change is slow. For component work use
**Storybook** (hot reload, no rebuild):

```bash
cd agent-ui && npm run storybook   # → http://localhost:6006
```

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

```bash
npm run release [patch|minor|major]
```

This gates on a build, bumps the version, commits, tags `vX.Y.Z`, and pushes. The
workflow (`.github/workflows/release.yml`) does the rest. **macOS is disabled in CI**
until code-signing is configured - build it locally instead (above). The app id /
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
  undisclosed-languages/   Monaco/Monarch language support (see its add-language.cjs)
  undisclosed-import/      VS Code settings/extensions import
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
  set**): `FIGMA_ACCESS_TOKEN`, `GITHUB_ACCESS_TOKEN`.
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
| Editor won't build ("Python 3.12 / distutils") | Use Node 20 + Python 3.11; `nvm use 20`, and point node-gyp at the venv python before packaging (`export npm_config_python=...`). |
| Agent panel shows a proxy/api error when adding a model | The `/api` proxy must target the **brain** (`:5001`), not a legacy `:3001` cloud proxy. In dev run via `scripts/dev.sh` (sets the target) or in `.env` set `UNDISCLOSED_PROXY_TARGET=http://127.0.0.1:5001`. |
| Brain won't start | Ctrl+C a prior `uv run ...` may leave `uv_installing.lock`/`uv_installed.lock` in `brain/` - delete them, then `./scripts/brain.sh setup`. |
| Packaged app is unsigned on macOS | Right-click → Open, or `xattr -cr /Applications/Undisclosed.app`. See `docs/PACKAGING.md` for signing/notarization. |

On the browser side you can run the whole stack from one terminal with
`./scripts/dev.sh`, which manages the brain + editor together (and defaults the proxy
target to `:5001`).

---

## License

Apache-2.0. Portions © Eigent.ai (preserved per Apache-2.0); the on-device editor
shell, packaging, and new features © Simon Ugorji. See per-file headers.
