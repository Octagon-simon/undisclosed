# Native agent panel in Theia

**Problem.** The product began as two decoupled halves: the **agent capability**
from Eigent, and the **editor shell + packaging** that is ours. The agent UI was
an Electron app. To be an editor-first product, the agent had to live *inside* the
editor as a first-class panel, not in a separate window docked next to it.

**Solution.** Host the agent UI as a native Theia dock widget, over a portable
transport seam, with the brain and the UI vendored into this repo so the whole
product builds and runs on its own.

---

## The Theia extension (`packages/undisclosed-agent`)

- `src/browser/undisclosed-agent-widget.tsx`: a `ReactWidget` mounted in the
  **right dock**. `AbstractViewContribution` + a `WidgetFactory` wire it in; it
  opens by default on first run (an `introduced` flag), then Theia layout
  persistence remembers the user's show/hide choice.
- `src/browser/undisclosed-agent-contribution.ts`: the toggle command and menu
  (keybinding `Cmd/Ctrl+Shift+A`; `Cmd+L` was avoided because Monaco uses it).
- `src/browser/undisclosed-agent-layout-contribution.ts`: the panel title/theme.
- `src/browser/git-extras-contribution.ts`, `undisclosed-welcome-*`: see
  [editor-extras.md](editor-extras.md).
- `src/node/undisclosed-agent-backend-module.ts`: the `/api` **proxy** to the
  brain, with retry for transient GETs.
- `src/node/brain-launcher.ts`, `src/electron-main/brain-teardown.ts`: launch and
  tear down the bundled brain in the desktop app.

## The UI bundle

`agent-ui/` is a React + Vite app. It builds to a **self-contained UMD bundle**
(`npm run build:agent-ui`) that is synced into
`packages/undisclosed-agent/assets/agent-embed/`, served by the extension, and
mounted into the dock widget's DOM. The same source runs in the Electron app; the
embed entry (`agent-ui/src/agent-embed/`) is the panel-specific bootstrap.

## The host seam (`agent-ui/src/host/types.ts`)

The decoupling lives inside the UI, not in a separate transport package.
`AppHost` in `agent-ui/src/host/types.ts` is the single host contract, and
`useHost()` (`agent-ui/src/host/context.tsx`) is the only way a component reaches
the host. A mount supplies the capabilities it has and omits the rest; every
capability is optional except the two preload handles.

- `electronAPI`, `ipcRenderer` — the desktop preload bridge. `null` in every
  other mount (the Theia panel, the web build). Only code that legitimately
  cannot work without a desktop shell should read them.
- `openFile(path)` — open a file the agent touched. The widget resolves it
  (`file://`, POSIX/Windows absolute, or workspace-relative) and opens a real
  Theia editor tab through `OpenerService`.
- `readFileAsDataUrl(path)` — the bytes of an agent-output image, as a `data:`
  URL, read through Theia's `FileService`. Used by the markdown renderer when
  `electronAPI.readFileAsDataUrl` is absent.
- `getActiveEditor()` / `onActiveEditorChanged(cb)` — the file and selection the
  user is looking at, so the agent gets editor context without shell calls.
- `getTheme()` / `onThemeChanged(cb)` — the host's own light/dark answer. The
  editor theme is the surface the panel sits on (`theme.css`), so it wins over
  the panel's stored appearance.
- `openSkillFolder(name)` — a `#skill` chip. Desktop reveals the folder in the
  OS file manager; the widget has no shell, so it asks the brain for the skill's
  folder (`GET /skills/path`) and opens `SKILL.md` in an editor tab. Skills live
  under `~/.undisclosed/skills`, outside the workspace, so the navigator cannot
  reveal them.

`packages/agent-net` (an earlier `AppHost` + fetch/SSE client) was retired: no
`package.json` or source file ever imported it, so it described a seam nothing
crossed, with a second, stale copy of the host contract. `agent-ui/src/api/http.ts`
owns the transport, and the table above owns the host surface.

## Self-contained build

- **Brain vendored** into `brain/` and run in its standalone mode
  (`python main.py`, uvicorn on `:5001`) against a repo-owned `uv` venv.
  `scripts/brain.sh` (start/stop/restart/logs) and `scripts/dev.sh` bring up both.
- **Agent UI vendored** into `agent-ui/`; `build:agent-ui` builds the bundle and
  syncs it.
- In dev, the browser proxies `/api` on `:3000` to the brain; in the packaged app
  the Theia/Electron backend proxies straight to the bundled brain.

## Caveats worth knowing

- The panel runs in the **same DOM/window** as Theia (no iframe). That is what
  makes file-open and live view work, and it is also why keyboard clashes happen:
  Theia's global keybindings can intercept shortcuts typed in the panel's
  `contenteditable`. We added a window-capture guard for `Cmd/Ctrl+A` (see
  [editor-extras.md](editor-extras.md)).
- The theme is reconciled via `assets/agent-embed/theme.css`, which maps the
  design-system (`--ds-*`) tokens onto Theia variables. Unmapped tokens were the
  cause of several "invisible in dark mode" bugs (brand buttons, toggles).

## Key commits

`1dbcdc2` (native panel), `4759561` (`@undisclosed/agent-net`, since retired),
`23f139a` (mount the real UI), `e8166d0` (webviews/auto-login/theme),
`deff604` (vendor the brain), `00a5a82` (vendor the UI), `b078ccf` (CDP Chromium),
`228c7bc` (follow agent tabs, brain stop/restart).
