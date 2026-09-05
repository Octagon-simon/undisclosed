# Undisclosed

An **on-device AI coding editor**. A custom [Eclipse Theia](https://theia-ide.org/)
editor with an agent built in as a native panel — the agent lives *inside* the
editor, not in a separate window. Everything runs locally: your code, the editor,
and the agent "brain" all stay on your machine (bring your own model keys).

Built as a decoupled fork of [Eigent](https://eigent.ai) — the agent capability
is Eigent's; the editor shell and on-device packaging are ours.

---

## What's in the box

Two local processes:

| Process | What it is | Port |
| --- | --- | --- |
| **Editor** | Theia + our `undisclosed-*` extensions + the embedded agent UI | 3000 |
| **Brain** | FastAPI/uvicorn agent backend (models, toolkits, SSE) | 5001 |

The agent UI (`agent-ui/`) is built into a self-contained bundle that the
`undisclosed-agent` Theia extension serves and mounts as a right-side panel. The
brain runs separately in dev (`scripts/brain.sh`) and is bundled + auto-launched
in the packaged desktop app.

---

## Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| **Node** | **18–20** (use `nvm use 20`) | Theia + its native modules don't build on Node 22/24 |
| **Python** | **3.11** | The brain; also node-gyp needs `distutils` (removed in 3.12) when packaging |
| **uv** | latest | Provisions the brain's venv from `pyproject.toml` |

An `.nvmrc` pins Node 20. Copy `.env.sample` → `.env` for any model keys /
tuning (all optional — see the file).

---

## Run locally (development)

Three terminals, or run the brain in the background.

**1. Brain** (agent backend, `:5001`):
```bash
./scripts/brain.sh setup      # once — provisions brain/.venv via uv
./scripts/brain.sh start      # start (or: restart | stop | logs | status)
```

**2. Agent UI bundle** (build + sync into the editor extension):
```bash
npm run build:agent-ui
```

**3. Editor** (Theia, `:3000`):
```bash
nvm use 20
npm install
npm run build                 # webpack the frontend + generate the backend
npm start                     # → http://127.0.0.1:3000
```

### Faster inner loop for the agent UI
Rebuilding the whole bundle to see a UI change is slow. For component work, use
**Storybook** (hot reload, no rebuild):
```bash
cd agent-ui && npm run storybook   # → http://localhost:6006
```

### Debugging
Set `UNDISCLOSED_DEBUG=1` (in `.env`) to dump each turn's prompt, tool calls,
model response, and streaming chunks to the brain log and
`~/.undisclosed/debug/<task>.log`. In the browser devtools console,
`localStorage.setItem('undisclosed_debug','1')` mirrors this on the frontend.

---

## Build a desktop app (installable)

The desktop app (`apps/desktop/`) is an Electron Theia shell that bundles the
editor **and** the brain (frozen with PyInstaller) and auto-launches it. One
command freezes the brain, builds the frontend, and packages an installer:

```bash
nvm use 20
export npm_config_python="$PWD/brain/.venv/bin/python"   # node-gyp needs Python 3.11
npm run desktop:install                                  # once
npm --prefix apps/desktop run rebuild                    # native modules → Electron ABI
npm run dist:mac       # → apps/desktop/dist/Undisclosed-*.dmg  (also dist:win / dist:linux)
```

The `.dmg` is **unsigned** (self-install). On first open: right-click → Open, or
`xattr -cr /Applications/Undisclosed.app`. Full details + troubleshooting:
**[docs/PACKAGING.md](docs/PACKAGING.md)**.

---

## Cut a release

Releases are tag-driven — CI builds installers on native runners and attaches
them to a GitHub Release.

```bash
npm run release [patch|minor|major]
```

This gates (build), bumps the version, commits, tags `vX.Y.Z`, and pushes. The
workflow (`.github/workflows/release.yml`) does the rest. macOS is disabled in
CI until code-signing is set up (build it locally instead — see above). See
[docs/PACKAGING.md](docs/PACKAGING.md) for the signing/notarization path.

---

## Repo layout

```
agent-ui/            The agent UI (React + Vite) → built to a self-contained bundle
brain/               FastAPI agent backend ("the brain"); uv + pyproject.toml
packages/
  undisclosed-agent/       Theia extension: serves + mounts the agent panel; brain launcher
  undisclosed-languages/   Monaco/Monarch language support (see its add-language.cjs)
  undisclosed-import/       VS Code settings/extensions import
apps/desktop/        Electron Theia app (packaging target)
scripts/             brain.sh, build-brain.sh, release.sh
docs/                PACKAGING.md and design notes
```

---

## License

Apache-2.0. Portions © Eigent.ai (preserved per Apache-2.0); on-device editor,
packaging, and new features © Simon Ugorji. See per-file headers.
