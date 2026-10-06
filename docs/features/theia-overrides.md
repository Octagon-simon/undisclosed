# Theia Overrides Register

Status: **updated 2026-10-06 for the Theia 1.76 upgrade.** `@theia/git` was removed
upstream, so **B4 and B12 are retired** and **B7 was reworked** onto the built-in
`vscode.git` extension (see the rows, and "Theia 1.76 migration" below). The guards
(startup assertion, audit script) are still planned, not implemented.
Owner: Simon Ugorji
Related: `docs/plans/theia-upgrade-plan.md` (the 1.60.0 -> 1.76.0 plan),
`docs/features/webview-blue-background.md` (the defect behind B1).

## Why this file exists

We bolt custom behavior onto Theia by subclassing or injecting upstream symbols and
rebinding them in our DI module. Theia treats most of those symbols as internal,
and it does not guarantee they stay put across releases. This file is the contract
list: every override we own, the exact upstream symbol and file path it depends on,
what behavior we change, and how to prove it still works after a bump.

Read this first when you upgrade Theia. If a row's upstream symbol moved, that row
is the bug you are about to hit.

## Theia 1.76 migration (2026-10-06)

- **`@theia/git` was removed** (last publish 1.60.2; npm-deprecated: "use the built-in
  VS Code Git extension"). Source Control is now the bundled `vscode.git` extension.
  - **B4 retired:** the `MenusContributionPointHandler` suppressor would now blank
    Source Control (no `@theia/git` left to dedupe against).
  - **B7 reworked:** git runs through a new backend `POST /undisclosed-agent/git/exec`;
    the commit box is read from `ScmService` (`selectedRepository.input`).
  - **B12 retired:** the `GitScmProvider.getUriToOpen` patch targeted `@theia/git`; the
    `undisclosed-git` package is now an empty stub. Re-verify the staged-file save.
- **`@theia/scm-extra` was removed** (final 1.74.1); we only depended on it.
- **webpack -> esbuild** (Theia 1.75): B13 moved from `webpack.config.js` to
  `esbuild.mjs` as an `onEnd` plugin.
- **React 19**: `@types/react`/`@types/react-dom` ^19 are now an *optional* peer of
  `@theia/core` and must be supplied by the app; `.tsx` uses a default React import.
- **Path moves**: B5 `navigator-preferences` -> `@theia/navigator/lib/common/...`;
  `PreferenceScope` / `PreferenceService` -> `@theia/core/lib/common/preferences/*`.

See `docs/plans/theia-upgrade-plan.md` section 11 for the full list.

## How to use it

1. Before bumping, run the audit script (see *Guards*, item 3) and read the rows
   whose upstream path it flags.
2. After bumping, walk the per-binding verification steps. Every row must pass on a
   packaged build, not just the dev server.
3. When upstream finally fixes something we override (B1 is the candidate), retire
   the row and its rebind in one commit, and delete it from this file.

## The register

| # | What we override | Our code (package `undisclosed-agent` unless noted) | Upstream dependency | Why it exists | Upgrade risk |
|---|---|---|---|---|---|
| B1 | `WebviewEnvironment` (singleton) | `src/browser/undisclosed-webview-environment.ts` | `@theia/plugin-ext/lib/main/browser/webview/webview-environment` | Rebuilds the `theia-resource/...` template by string concatenation so the `//` before `{{authority}}` survives `URI.resolve()`. Without it every webview resource 404s (pets, media preview). | Deep import path; `resourceRoot(host)` signature; whether the rebind still wins after module ordering. |
| B2 | `SidePanelHandler` | `src/browser/undisclosed-side-panel-handler.ts` | `@theia/core/lib/browser/shell/side-panel-handler` | `refresh()` override keeps the RIGHT tab strip hidden. | Reads protected internals `tabBar.parent`, `topMenu`, `bottomMenu`, `additionalViewsMenu`, `container`, `dockPanel`; the `side` field. Any rename/retype breaks the override at compile time. |
| B3 | `TerminalWidget` (transient) | `src/browser/persistent-terminal-widget.ts` | `@theia/terminal/lib/browser/terminal-widget-impl` (`TerminalWidgetImpl`) + `xterm-addon-serialize` | Serializes the terminal buffer on close and replays it after reload. | **Highest risk.** Terminal internals and the `xterm` -> `@xterm/*` package split both move in this window. `SerializeAddon` may no longer resolve. |
| B4 | ~~`MenusContributionPointHandler`~~ **RETIRED in 1.76** | ~~`src/browser/vscode-git-ui-suppressor.ts`~~ (deleted) | ~~`@theia/plugin-ext/.../menus-contribution-handler`~~ | Obsolete: `@theia/git` was removed in 1.76, so the built-in `vscode.git` extension *is* the Source Control provider. The suppressor would now blank Source Control, so the rebind was removed. | None — retired. Re-add only if a duplicate SCM provider ever reappears. |
| B5 | `FileNavigatorContribution` (injected, not rebound) | `src/browser/undisclosed-explorer-auto-reveal-contribution.ts` | `@theia/navigator/lib/browser/navigator-contribution`, `@theia/navigator/lib/common/navigator-preferences` (moved out of `lib/browser` in 1.76), Lumino `TabBar.tabActivateRequested` | Re-reveals the Explorer file when the already-active tab is clicked again. | Injected service may be renamed/split; navigator internals; Lumino version (shared `@lumino/widgets`); private preference access is brittle. |
| B6 | Native media preview opener | `undisclosed-languages/src/browser/media-preview/media-preview-open-handler.ts` + `media-preview-widget.ts` | `@theia/core/lib/browser/widget-open-handler` (`WidgetOpenHandler`), `OpenHandler`, `EditorManager` priority | Opens image/audio/video in our own widget with priority above the `vscode.media-preview` builtin (~400). | `WidgetOpenHandler` / `WidgetOpenerOptions` API drift; opener priority semantics; overlap with `EditorManager`'s default opener. |
| B7 | Git extras | `src/browser/git-extras-contribution.ts` | `@theia/scm` `ScmService` (`selectedRepository.provider.rootUri` + `.input`), `ScmWidget`; `TabBarToolbarContribution`; local backend `POST /undisclosed-agent/git/exec` (**@theia/git removed in 1.76**) | Adds Undo Last Commit, stage/discard-all, and the AI commit-message button. | `ScmService` / `ScmWidget` signatures; menu/toolbar contribution APIs. |
| B8 | Agent panel + welcome + layout | `src/browser/undisclosed-agent-widget.tsx`, `undisclosed-welcome-*.ts(x)`, `undisclosed-agent-layout-contribution.ts` | `@theia/core` shell, `bindViewContribution`, `FrontendApplicationContribution`, Lumino shell layout | The agent panel, branded welcome, bottom-panel expand button, first-boot layout. | `FrontendApplicationContribution` lifecycle; `ApplicationShell` layout APIs. |
| B9 | Monaco language + editor pin | `undisclosed-languages/src/browser/undisclosed-languages-contribution.ts` | `@theia/monaco`, `@theia/monaco-editor-core` (re-pinned to **1.108.201** for 1.76) | Monarch tokenizers against Theia's Monaco; ships the media preview. | `monaco-editor-core` pin must be re-aligned to 1.76's Monaco or we risk type/runtime errors and a double Monaco. |
| B10 | VS Code builtins + import-from-VS Code | `apps/desktop` `theiaPlugins`, `undisclosed-import` | `@theia/vsx-registry`, plugin host | Bundled language features pinned to 1.95.3; Prettier pinned to 11.0.3 (last CJS release). | Theia 1.76's plugin API target may require a newer builtin set; the Prettier CJS constraint may change. |
| B11 | Backend brain lifecycle | `src/browser/undisclosed-agent-backend-module.ts` (`BrainLauncher`), `src/electron-main/brain-teardown.ts` | `@theia/core` backend `BackendApplicationContribution`, `@theia/core` electron-main | Spawns/tears down the Python brain; caps restarts at 10. | Backend contribution API; Electron main API changes (Electron 30 -> 42). |

| B12 | ~~`GitScmProvider.getUriToOpen` patch~~ **RETIRED in 1.76** | ~~`packages/undisclosed-git/src/browser/writable-git-scm-provider.ts`~~ (deleted; package is now an empty stub) | ~~`@theia/git/...`~~ | Obsolete: it patched `@theia/git`, which 1.76 removed. Source Control is now `vscode.git`, which opens the working-tree file directly. Re-verify the staged-save test (section 7) on 1.76; re-populate the stub only if it regresses. | n/a — retired; pending the B12 runtime check. |
| B13 | Webview default stylesheet (`body { padding: 0 20px }`) | `webpack.config.js` + `apps/desktop/webpack.config.js` (`applyWebviewFullWidth`) | `@theia/plugin-ext/src/main/browser/webview/pre/main.js` (`defaultCssRules`), copied to `lib/webview/pre` by `gen-webpack.config.js` | Theia injects `padding: 0 20px` into every webview; a webview that sizes to `width:100%` (Capibara Pet `#stage`) renders 40px narrower than its panel. We rewrite the declaration during the build's copy step so the content is full width. **Global: changes every webview, not just pets.** | Not a DI rebind, so it fails *silently*: it depends on the copy `from` path ending `webview/pre` and on the literal `padding: 0 20px;`. If either moves, the transform no-ops and the build still succeeds. |

### Mechanism risk shared by B1, B4 and B12

Our rebinds only win because `undisclosed-agent`'s frontend module loads **after**
`@theia/plugin-ext`'s module, and `undisclosed-git`'s module loads **after**
`@theia/git`'s module. Nothing in the code enforces that order; it depends on
`theiaExtensions` resolution order. A dependency bump can flip it silently, and the
rebind becomes a no-op with no error. The startup assertion below is the guard for
exactly this.

## Per-binding verification

Run these after any bump. B1, B3, B4, B6 must also be repeated on a packaged
(`dist:mac`) build, not only the dev server.

- **B1 webview:** open Capibara Pet (or VS Code Pets) and confirm the pet renders
  (no `#93cbf4` blue panel). In DevTools network, no 404 on `/theia-resource/`. Open
  a PNG through media preview and confirm the image paints.
- **B2 right side panel:** agent panel is flush to the right edge, no ~48px tab
  strip; resizing/collapsing the panel does not bring the strip back.
- **B3 terminal persistence:** run a few commands, reload the window, confirm
  scrollback is restored and the terminal is interactive. Confirm the `serialize`
  addon loads (its failure path degrades to a normal terminal).
- **B4 git suppressor:** open Source Control; `vscode.git`'s duplicate inline menu
  items are absent, while the `vscode.git` API still works for GitLens.
- **B5 navigator auto-reveal:** click file A's tab, then file A's tab again; the
  Explorer re-highlights/reveals A. Test after collapsing the tree and after a
  reveal that raced startup.
- **B6 media preview:** open a PNG, a GIF, an audio and a video file; each opens in
  our native widget (not the broken plugin webview), with zoom/controls.
- **B7 git extras:** Undo Last Commit, stage-all/discard-all, and the AI commit
  button appear and work.
- **B8 agent/welcome/layout:** agent panel opens on first boot; branded welcome
  shows with no workspace; bottom-panel expand button works.
- **B9 languages:** TS/JS/CSS/HTML/JSON tokenize and language features (LSP)
  activate; the configured Monarch languages highlight.
- **B10 builtins:** TS/CSS/HTML/JSON/Emmet/Markdown features work; ESLint and
  Prettier plugins activate; `undisclosed-import` pulls settings/extensions.
- **B11 brain:** app starts, brain spawns, chat/health check responds; brain
  teardown on quit; the restart-cap behavior is unchanged.
- **B12 staged-file save:** `git add` a file, edit it from the **Staged Changes**
  entry, `Cmd+S`; the change persists to the working tree and the buffer clears
  dirty. The same file opened from **Changes** (unstaged) still saves. Close-all no
  longer warns on a staged buffer that cannot be written. Must be repeated on a
  packaged build, since the extension is wired into `apps/desktop` as well as the
  root browser target.
- **B13 webview full width:** expand the Capibara Pet view; in DevTools the webview
  `body` computed `padding` is `0px` and `#stage` width equals the panel width (no
  20px inset). Confirm other webviews (media preview, markdown) still render. This
  one is a *build* transform, so it must be checked on a freshly built bundle
  (`npm run build` / `theia build`), not just a running server.

## Guards (planned, implement on the upgrade branch)

These are small additions that make a future silent failure impossible. They are
**not implemented yet** and must land on `upgrade/theia-1.76`, not on `main`.

1. **Startup assertion for B1 and B4.** In the frontend module (or a
   `FrontendApplicationContribution.onStart`), assert that
   `container.get(WebviewEnvironment).constructor === UndisclosedWebviewEnvironment`
   and the same for `MenusContributionPointHandler`. If module order ever flips, the
   app fails loudly at boot instead of quietly reverting to the broken behavior.

2. **Deep-import isolation.** Wrap each `@theia/plugin-ext/lib/...` deep import
   (B1, B4) in one small module per override, so a path change is a one-line fix
   instead of a search.

3. **`scripts/theia-override-audit.sh`.** Greps the installed `node_modules/@theia`
   for each symbol/path in the register and exits non-zero if any are missing. Also
   checks whether the webview defect line still exists upstream, so we know whether
   B1 can ever be retired. Run it as the first step of any bump.

4. **`tsc` gate in CI.** `build:packages` already runs tsc; make sure CI runs it
   against the pinned Theia so signature drift is caught on the upgrade branch, not
   at runtime.
s a one-line fix
   instead of a search.

3. **`scripts/theia-override-audit.sh`.** Greps the installed `node_modules/@theia`
   for each symbol/path in the register and exits non-zero if any are missing. Also
   checks whether the webview defect line still exists upstream, so we know whether
   B1 can ever be retired. Run it as the first step of any bump.

4. **`tsc` gate in CI.** `build:packages` already runs tsc; make sure CI runs it
   against the pinned Theia so signature drift is caught on the upgrade branch, not
   at runtime.
