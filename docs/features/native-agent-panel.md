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

## The transport seam (`packages/agent-net`)

`@undisclosed/agent-net` is the decoupling: a framework-agnostic fetch HTTP client
and an SSE client whose base URL, auth token, user id, session id, and host
capabilities are all **injected** (no Electron, no authStore, no IPC).

- `AgentNetConfig(baseUrl, getToken, getUserId, getSessionId)`
- `AppHost` interface (the audited host surface) + a `noopHost`
- `http: fetch client` (Bearer only on brain-relative paths)
- `sse: fetch-event-source` with injected auth, `openWhenHidden`, content-type guard

This is the seam the Theia widget and the Electron app both drive. Host
capabilities the panel needs (`openFile`, `readFileAsDataUrl`,
`getSystemLanguage`, and so on) are implemented by the widget, so a file chip or
path in chat opens a real Theia editor tab (`OpenerService`).

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

`1dbcdc2` (native panel), `4759561` (`@undisclosed/agent-net`),
`23f139a` (mount the real UI), `e8166d0` (webviews/auto-login/theme),
`deff604` (vendor the brain), `00a5a82` (vendor the UI), `b078ccf` (CDP Chromium),
`228c7bc` (follow agent tabs, brain stop/restart).
