# Theia Upgrade Plan: 1.60.0 (Node 20) to 1.76.0 (Node 24)

Status: **plan for review, not yet executed.**
Owner: Simon Ugorji
Created: 2026-10-06
Updated: 2026-10-06 (Electron 30 -> 42 mapping + the renderer-abort finding; see
section 3, "Electron is pinned by Theia" and "Two different crashes").

This is the follow-up to the webview blue-background fix
(`docs/features/webview-blue-background.md`). The upgrade was deliberately
separated from that bug fix because the version bump is a large, risky piece of
work on its own, and it does **not** fix the webview defect (see section 3).

---

## 0. Branch strategy (read first)

All code changes for this upgrade happen on a dedicated branch,
`upgrade/theia-1.76`, created off `main`. **Nothing upgrade-related is changed on
`main`.** `main` stays the shippable tree: it keeps the 1.60.0 pins and the current
webview fix.

Only planning documents are added on `main`: this plan and the register
`docs/features/theia-overrides.md`. The register's guards (startup assertion,
deep-import isolation, the audit script) are **code**, so they go on the upgrade
branch, not here. Section 6 and section 10 track that split.

---

## 1. Goal and non-goals

### Goal
Move the whole product from Theia 1.60.0 on Node 20 to Theia 1.76.0 on Node 24,
without losing any of the custom behavior we have bolted onto Theia: the webview
fix, the media preview, the navigator auto-reveal, the side-panel/welcome/layout
customizations, the persistent terminal, and the VS Code git UI suppressor.

### Non-goals
- Not a rewrite of the agent, brain, or agent-ui. Only the Theia shell and our
  Theia extension packages move.
- Not a jump to `next` (1.77.0-next.x). We target the `latest` stable tag.
- Not a fix for the webview resource 404. That stays a rebind regardless of
  Theia version.

### Definition of done
- Root app (`theia target: browser`) and `apps/desktop` (`theia target:
  electron`) both run on Theia 1.76.0 / Node 24 / Electron 42.
- `npm run build:packages`, `npm run build` (root), and
  `npm --prefix apps/desktop run build` all succeed.
- Every entry in the Custom Binding Register (section 4) passes its
  verification step (section 7).
- CI (`release.yml`) and all `engines` / `.nvmrc` pins say Node 24.
- A rollback branch exists if the upgrade cannot be stabilized.

---

## 2. Current state (verified 2026-10-06)

### Versions we run today
- `@theia/*`: **1.60.0** in three places: root `package.json`,
  `apps/desktop/package.json`, and each extension package.
- Node: `.nvmrc` = `20`, `engines.node` = `">=18 <=20"` in both root and
  `apps/desktop/package.json`. CI `.github/workflows/release.yml` uses
  `node-version: 20`.
- Electron: **30.1.2** (`apps/desktop` devDependencies).
- `@theia/monaco-editor-core`: **1.96.302** (pinned in
  `packages/undisclosed-languages/package.json`).
- Terminal: `xterm ^5.3.0` + `xterm-addon-serialize 0.11.0`
  (`packages/undisclosed-agent/package.json`).
- Bundled VS Code builtins pinned to **1.95.3** in
  `apps/desktop/package.json` (`theiaPlugins`), Prettier pinned to 11.0.3.
- npm override `@vscode/ripgrep: 1.15.9`.

### Repo shape (two independent npm projects, no workspaces)
- Root project: Theia **browser** target. Depends on the local extension
  packages via `file:packages/*`.
- `apps/desktop`: Theia **electron** target, its own `package-lock.json` and
  its own `node_modules` (currently `@theia/core` 1.60.0). This is what ships.
- Extension packages: `undisclosed-agent`, `undisclosed-languages`,
  `undisclosed-import`, `agent-net` (framework-agnostic transport, no Theia
  dependency), plus `brain/` (Python, independent of the Node toolchain).

### Where our customizations live
- `packages/undisclosed-agent/src/browser/undisclosed-agent-frontend-module.ts`
  is the single frontend DI module (declared via `theiaExtensions` in that
  package's `package.json`). All rebinds are in this one file today.
- `packages/undisclosed-languages/src/browser/undisclosed-languages-frontend-module.ts`
  hosts the native media preview (widget factory + `OpenHandler`).
- `packages/undisclosed-agent/src/browser/undisclosed-agent-backend-module.ts`
  and `src/electron-main/brain-teardown.ts` for backend/electron hooks.

### Working tree state (do not lose this)
`git status` shows uncommitted work: `undisclosed-webview-environment.ts`
(untracked, the webview fix), the modified
`undisclosed-agent-frontend-module.ts` (the rebind), plus
`apps/desktop/electron-entry.js`, `.env.sample`, and new docs. There are also
many `*.bak` files scattered alongside sources. **Checkpoint before touching
dependencies.**

---

## 3. Target state and the key upstream findings

### Target versions
- `@theia/*`: **1.76.0** (npm `latest` tag as of 2026-10-06; the `patch` tag is
  1.74.2, `next` is 1.77.0-next.14).
- Node: **24** (Theia 1.76.0's root `package.json` declares
  `engines.node: ">=24"`). Node 20 will not work.
- Electron: **42.8.1** (the version `@theia/electron@1.76.0` pins). A 12-major
  jump from Electron 30. See "Electron is pinned by Theia" below.
- `@theia/monaco-editor-core`: whatever 1.76.0 aligns with (must be re-pinned
  in `undisclosed-languages`; the current 1.96.302 is a 1.60-era pin).

### Electron is pinned by Theia, not chosen by us

`@theia/electron` declares Electron as a **peer dependency, exact** (no range).
We do not pick the Electron version independently: `@theia/electron`'s
`electron-main` is written against that one generation. The pin moves every few
Theia releases:

| Theia | `@theia/electron` peer `electron` |
|---|---|
| 1.60.0 (we are here) | **30.1.2** |
| 1.65.0 | 37.2.1 |
| 1.68.0 | 38.4.0 |
| 1.70.0 | 39.7.0 |
| 1.73.0 | 39.8.7 |
| 1.75.0 / 1.76.0 | **42.8.1** |

(Verified with `npm view @theia/electron@<v> peerDependencies.electron`,
2026-10-06.)

So the 1.76 upgrade is **also** an Electron 30 -> 42 upgrade, and Node 24 comes
with it. Two consequences to bake into the plan:

- **You cannot bump Electron on its own.** Moving `apps/desktop` to 37+ without a
  matching Theia breaks the exact peer dependency and the Electron main APIs
  `@theia/electron` targets. The bump is part of this upgrade, not a side quest.
- **A same-line patch bump is not enough.** 30.1.2 -> 30.5.1 (the last 30.x) stays
  on Chromium 124 / V8 12.4, so it would not move a V8 bug. The only supported
  path to a newer Electron is the Theia bump.

For reference, the newest Electron stable today is **44.5.1**; 1.76's 42.8.1 is
current-minus-two, not bleeding edge.

### Two different crashes, only one is Electron

While chasing the plugin toast we found **two** unrelated crash classes in the
macOS reports (`~/Library/Logs/DiagnosticReports`). They matter here because the
Electron bump only addresses one of them:

| Crash | Process | Signal / fault | Is it Electron? | Does 1.76 address it? |
|---|---|---|---|---|
| Plugin runtime toast | `node` (dev plugin host; parent = Theia backend, pid 75368) | `SIGKILL (Code Signature Invalid)`, `CODESIGNING / Invalid Page`, inside `process.dlopen` -> `dyld` while mapping a native addon | **No**, it is the nvm **Node** plugin host | No. The Electron version is irrelevant to this one. |
| Packaged app dies / blanks | `Undisclosed Helper (Renderer)` (Electron) | `SIGABRT` from `abort()` -> `node::OnFatalError` inside the **Electron Framework**, with V8 `cppgc` / `CppHeap` frames | **Yes**, Electron's Chromium/V8 | **Plausibly.** A newer Chromium/V8 is a candidate for this abort class; rule out a heap OOM too. |

The first is the dev plugin-host code-signing kill written up in
`docs/features/plugin-runtime-crash.md`; the fix there is the orphan reaping in
`scripts/dev.sh`, not a version bump. The second is why "it's Electron itself" is
right *for the packaged app*, and is the concrete justification for treating the
Electron jump as a real part of this upgrade rather than incidental.

### Two decisions this forces
1. We cannot stay on Node 20. `.nvmrc`, both `engines` blocks, and CI must all
   move to 24 together, or `npm install` will fail the engine check (and the
   Theia CLI will refuse or misbehave).
2. The upgrade does **not** remove any of our Theia overrides. Concretely, the
   webview defect is still present in 1.76.0:

   ```
   // packages/plugin-ext/src/main/browser/webview/webview-environment.ts:75 (v1.76.0)
   return (await this.externalEndpointUrl()).resolve('theia-resource/{{scheme}}//{{authority}}/{{path}}').toString(true);
   ```

   So `UndisclosedWebviewEnvironment` and its `rebind(WebviewEnvironment)` stay
   in the tree after the upgrade. Same reasoning for every other entry in the
   register. This is the core of "preserve the custom bindings".

### Symbols we depend on still exist at v1.76.0
Confirmed present at the v1.76.0 tag (raw source returned HTTP 200):
`packages/core/src/browser/shell/side-panel-handler.ts`,
`packages/terminal/src/browser/base/terminal-widget.ts`,
`packages/plugin-ext/src/main/browser/menus/menus-contribution-handler.ts`,
`packages/plugin-ext/src/main/browser/webview/webview-environment.ts`,
`packages/navigator/src/browser/navigator-contribution.ts`, and
`doc/Migration.md`. Existing is not the same as unchanged. The migration guide
(`doc/Migration.md`) lists renames/removals in the 1.60 to 1.76 window that
touch adopters; compiling our packages against 1.76 is what actually proves each
signature.

---

## 4. Custom Binding Register (the thing to preserve)

Every row is a contract: our code assumes this exact upstream symbol, path, and
behavior. On upgrade, each one is a checkpoint.

| # | What we override | Our code | Upstream dependency | Why it exists | Upgrade risk |
|---|---|---|---|---|---|
| B1 | `WebviewEnvironment` (singleton) | `undisclosed-webview-environment.ts` | `@theia/plugin-ext/lib/main/browser/webview/webview-environment` | Rebuilds the `theia-resource/...` template by concatenation so the `//` before `{{authority}}` survives `URI.resolve()`. Fixes pets + media preview. | Deep import path; `resourceRoot(host)` signature; whether the binding still wins after module ordering. |
| B2 | `SidePanelHandler` | `undisclosed-side-panel-handler.ts` | `@theia/core/lib/browser/shell/side-panel-handler` | `refresh()` override keeps the RIGHT tab strip hidden. Reads internals `tabBar.parent`, `topMenu`, `bottomMenu`, `additionalViewsMenu`, `container`, `dockPanel`. | These protected members can be renamed/retyped. The `side` field. |
| B3 | `TerminalWidget` (transient) | `persistent-terminal-widget.ts` | `@theia/terminal/lib/browser/terminal-widget-impl` (`TerminalWidgetImpl`) + `xterm-addon-serialize` | Serializes terminal buffer on close, replays after reload. | Highest risk. Terminal internals and the `xterm` vs `@xterm/xterm` package split changed across this window. `SerializeAddon` import path (`xterm-addon-serialize`) may no longer resolve. |
| B4 | `MenusContributionPointHandler` (singleton) | `vscode-git-ui-suppressor.ts` | `@theia/plugin-ext/lib/main/browser/menus/menus-contribution-handler` | Keeps `vscode.git` API but withholds its Source Control menu items so it stops duplicating `@theia/git`. | Deep import; handler method signatures and menu registration flow. Load-order dependency (ours must load after plugin-ext). |
| B5 | `FileNavigatorContribution` (injected, not rebound) | `undisclosed-explorer-auto-reveal-contribution.ts` | `@theia/navigator/lib/browser/navigator-contribution`, `navigator-preferences`, Lumino `TabBar.tabActivateRequested` | Re-reveals the Explorer file on a re-click of the already-active tab. Reads `shell.allTabBars`, `FileNavigatorContribution` methods, `fileNavigatorPreferences['explorer...']`. | Injected service may be renamed/split; navigator internals; Lumino version (shared `@lumino/widgets`). Private preference access is brittle. |
| B6 | Native media preview opener | `media-preview-open-handler.ts` + `media-preview-widget.ts` | `@theia/core/lib/browser/widget-open-handler` (`WidgetOpenHandler`), `OpenHandler`, `EditorManager` priority | Opens image/audio/video in our own widget with priority above the `vscode.media-preview` builtin (~400). | `WidgetOpenHandler`/`WidgetOpenerOptions` API drift; opener priority semantics; `EditorManager` default opener overlap. |
| B7 | Git extras | `git-extras-contribution.ts` | `@theia/git` `Git`, `GitRepositoryProvider`, `@theia/scm` `ScmService`, `ScmWidget`, `TabBarToolbarContribution` | Adds Undo Last Commit, stage/discard all, and the AI commit-message button. | `ScmService`/`ScmWidget` signatures; menu/toolbar contribution APIs. |
| B8 | Agent panel + welcome + layout | `undisclosed-agent-widget.tsx`, `undisclosed-welcome-*.ts`, `undisclosed-agent-layout-contribution.ts` | `@theia/core` shell, `bindViewContribution`, `FrontendApplicationContribution`, Lumino shell layout | The agent panel, branded welcome, bottom-panel expand button, first-boot layout. | `FrontendApplicationContribution` lifecycle; `ApplicationShell` layout APIs. |
| B9 | Monaco language + editor pin | `undisclosed-languages-contribution.ts` | `@theia/monaco`, `@theia/monaco-editor-core` | Monarch tokenizers against Theia's Monaco; ships the media preview. | `monaco-editor-core` version must match the new `@theia/monaco`; otherwise duplicate Monaco / type errors. |
| B10 | VS Code builtins + import-from-VS Code | `apps/desktop` `theiaPlugins`, `undisclosed-import` | `@theia/vsx-registry`, plugin host | Bundled language features pinned to 1.95.3, Prettier 11.0.3 (last CJS release). | Theia 1.76's plugin API target may require a newer builtin set; the Prettier CJS constraint may change. |
| B11 | Backend brain lifecycle | `undisclosed-agent-backend-module.ts` (`BrainLauncher`), `brain-teardown.ts` | `@theia/core` backend `BackendApplicationContribution`, `@theia/core` electron-main | Spawns/tears down the Python brain; caps restarts at 10. | Backend contribution API; Electron main API changes (Electron 30 to 42). |

### Mechanism risk shared by B1 and B4
Our rebinds only win because `undisclosed-agent`'s frontend module is loaded
**after** `@theia/plugin-ext`'s module. That ordering is not something the code
enforces; it depends on `theiaExtensions` resolution order. A dependency bump
can change that order silently, and the rebind would be a no-op with no error.
Mitigation in section 6 (startup assertion + audit script).

---

## 5. Phased execution plan

Each phase ends with a green checkpoint. Do not proceed on red.

### Phase 0: Checkpoint and branch (no dependency changes)
- Per section 0: land the current webview fix and this plan + register on `main`
  first, then branch. `main` never receives upgrade code.
- Commit or stash the current webview fix (`undisclosed-webview-environment.ts`
  + the rebind + docs) on `main`, or branch first. The upgrade must start from a
  clean, known-good tree.
- Decide the fate of the `*.bak` files (the app has dozens). At minimum exclude
  them from the upgrade branch so diffs stay readable.
- Create `upgrade/theia-1.76` branch.
- Record the current green baseline: `npm run build:packages` passes,
  `npm run build` passes, app starts, pets/media/terminal work.
- Rollback is `git checkout main` plus `npm ci` in both projects. Copy the
  current lockfiles aside; they are the real rollback artifact.

### Phase 1: Toolchain (Node 24)
- Switch local Node to 24 (`.nvmrc` -> `24`, or the exact 24.x LTS the team
  standardizes on). Note: the dev shell currently reports **Node v26.5.0**,
  which is *not* the pinned version and is ahead of the Theia baseline. Do not
  test against 26; pin 24.
- Update `engines.node` to `">=24"` (or `">=24 <25"` to match the repo's prior
  "one major" style) in root and `apps/desktop/package.json`.
- Update `.github/workflows/release.yml` `node-version` from 20 to 24.
- Check `scripts/*.sh` (build-brain.sh, verify-fresh.sh, preflight-ci.sh,
  release.sh, dev.sh) and `electron-builder.yml` for any hard Node path.

### Phase 2: Dependencies
- Root `package.json`: bump every `@theia/*` from 1.60.0 to 1.76.0, and
  `@theia/cli`. Add any new peer packages Theia 1.76 splits out (the migration
  guide is the source of truth; e.g. AI-related packages reorganized, though we
  do not depend on them).
- `apps/desktop/package.json`: same `@theia/*` bump, plus `electron` 30.1.2 ->
  42.8.1 and `@theia/cli`.
- `packages/undisclosed-agent/package.json`: bump its `@theia/*` deps; review
  the `xterm`/`xterm-addon-serialize` pins against what 1.76's terminal uses
  (may become `@xterm/xterm` + `@xterm/addon-serialize`).
- `packages/undisclosed-languages/package.json`: bump `@theia/monaco`,
  `@theia/monaco-editor-core`, `@theia/filesystem` to the 1.76-aligned versions.
- `packages/undisclosed-import/package.json`: bump `@theia/core`,
  `@theia/vsx-registry`.
- Review the `@vscode/ripgrep` override; 1.76 may bundle a different default.
- Do **not** hand-edit `src-gen/`, `gen-webpack*.js`, or `webpack.config.js`.
  Regenerate via the Theia CLI.

### Phase 3: Reinstall
- Root: `npm install`, then commit the updated lockfile. Prefer keeping the lock
  and letting npm update it, so the diff is reviewable (delete it only if a
  clean resolve is needed).
- `apps/desktop`: same, in its own directory (`npm --prefix apps/desktop
  install`). It has its own lockfile and `node_modules`.
- Rebuild native/electron deps: `npm --prefix apps/desktop run rebuild`
  (`theia rebuild:electron`). Expect native module rebuilds against Electron 42.

### Phase 4: Compile our packages (first real signal)
- `npm run build:packages` (tsc for undisclosed-agent, undisclosed-import,
  undisclosed-languages). Fix API drift file by file. This is where B2, B3, B5,
  B6, B7, B9 break if they break.
- Iterate until `tsc` is clean for all three. Each failure maps to a register
  row; record the fix next to the row.

### Phase 5: Browser app build and smoke test
- `npm run download:plugins` (may need a plugin-set bump, Phase 8).
- `npm run build`, then `npm run start`.
- Smoke test the browser target against section 7.

### Phase 6: Desktop build and package
- `npm --prefix apps/desktop run build`, then `package:dir` for a fast
  un-packaged check before `dist:mac`.
- Verify the Electron main entry (`electron-entry.js`, `BrowserWindow`,
  `powerMonitor`, brain spawn/teardown) on Electron 42.
- Try to reproduce the packaged renderer `SIGABRT` (section 3, "Two different
  crashes"): run `dist:mac` and exercise the renderer until the prior crash
  cadence either recurs or does not. This is the one signal that justifies the
  Electron 42 change; if it persists, rule out a renderer heap OOM before
  blaming and/or crediting the version bump.
- Only run the full `dist:mac`/`dist:win`/`dist:linux` after Phase 7 passes.

### Phase 7: Binding verification (the acceptance gate)
Run the full checklist in section 7. Every B-item must pass. This is the phase
that answers "are our custom bindings preserved".

### Phase 8: Bundled VS Code plugins
- Bump `theiaPlugins` in `apps/desktop/package.json` to the VS Code builtin
  release that matches Theia 1.76's plugin API. Determine the exact version from
  the 1.76 plugin host at upgrade time (what `@theia/plugin-ext` 1.76 emulates,
  and the open-vsx `vscode` namespace). Do not guess a number.
- Re-check the Prettier CJS pin: if 1.76's plugin host (Electron 42 / its Node)
  still `require()`s extension entries, keep the last-CJS Prettier; if the host
  accepts ESM, we can move forward.
- Re-run `npm run download:plugins` and re-verify language features activate.

### Phase 9: Regression matrix and docs
- Run the scenario matrix (section 7) on browser and desktop.
- Update `docs/PACKAGING.md` and `docs/systems/*`.
- Update the register (`docs/features/theia-overrides.md`, already drafted on
  `main`) with anything the bump changes: re-pinned versions, fixed rows, retired
  overrides.
- Bump product/desktop version if the team's release process requires it.

### Phase 10: Merge and rollback readiness
- Merge `upgrade/theia-1.76` only after Phase 7 passes on a packaged build.
- Keep the 1.60 lockfiles tagged so a one-command revert exists.

---

## 6. Making the bindings survive future upgrades (process)

The upgrade will likely succeed on effort. The failure mode to design against is
a **silent** loss: a rebind that no longer wins because module order changed, or
a subclass whose `override` no longer matches a renamed upstream method (tsc
catches the latter, nothing catches the former).

Status: item 1 (the register) is **drafted on `main`**. Items 2-5 are **code** and
are **deferred to `upgrade/theia-1.76`**; do not add them on `main`.

1. **A register doc that is code-adjacent. [DONE, doc]**

   -> `docs/features/theia-overrides.md`

   Section 4 is promoted into the register, one section per override, each with
   the upstream file + symbol, the exact behavior we change, and the manual
   verification step. This is the checklist a future upgrade reads first.

2. **A startup assertion for the order-sensitive rebinds (B1, B4).
   [DEFERRED -> `upgrade/theia-1.76`]** In the frontend module (or a
   `FrontendApplicationContribution.onStart`), assert that
   `container.get(WebviewEnvironment).constructor === UndisclosedWebviewEnvironment`
   and the same for `MenusContributionPointHandler`. If a future upgrade flips
   module order, the app fails loudly at boot instead of quietly reverting to
   the broken behavior.

3. **An upgrade audit script. [DEFERRED -> `upgrade/theia-1.76`]** A
   `scripts/theia-override-audit.sh` that greps the installed `node_modules/@theia`
   for each symbol/path in the register and exits non-zero if any are missing, plus
   a check that the webview defect line still exists (so we know whether the rebind
   can ever be retired). Run it as the first step of any future bump.

4. **A `tsc` gate on the extension packages in CI. [DEFERRED ->
   `upgrade/theia-1.76`]** `build:packages` already runs tsc; make sure CI runs it
   against the pinned Theia so signature drift is caught on the upgrade branch, not
   at runtime.

5. **Isolate deep imports. [DEFERRED -> `upgrade/theia-1.76`]** Every
   `@theia/plugin-ext/lib/...` deep import (B1, B4) is a private surface. Where
   feasible, wrap the import in one small module per override so a path change is a
   one-line fix, not a search.

---

## 7. Verification checklist

### Per-binding acceptance (Phase 7)
- **B1 webview:** open Capibara Pet (or VS Code Pets) and confirm the pet
  renders (no `#93cbf4` blue panel). In DevTools network, no 404 on
  `/theia-resource/`. Open a PNG through media preview and confirm the image
  paints (webview resources and plugin assets both load).
- **B2 right side panel:** agent panel is flush to the right edge, no ~48px tab
  strip; resizing/collapsing the panel does not bring the strip back.
- **B3 terminal persistence:** run a few commands, reload the window, confirm
  scrollback is restored and the terminal is interactive. Confirm the
  `serialize` addon loads (its failure path degrades to a normal terminal).
- **B4 git suppressor:** open Source Control; `vscode.git`'s duplicate inline
  menu items are absent, while the `vscode.git` API still works for GitLens.
- **B5 navigator auto-reveal:** click file A's tab, then file A's tab again;
  the Explorer re-highlights/reveals A. Test after collapsing the tree and after
  a reveal that raced startup.
- **B6 media preview:** open a PNG, a GIF, an audio and a video file; each
  opens in our native widget (not the broken plugin webview), with zoom/controls.
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

### Cross-cutting scenarios
- Fresh clone + `npm install` + `npm run build` + `npm run start` (browser).
- `npm --prefix apps/desktop run dist:mac` produces a launchable app; repeat the
  B1, B3, B4, B6 checks in the packaged app, not just dev.
- Workspace open/close, split editors, multiple terminals, session reload.
- No new errors in the Theia log or the renderer console.

---

## 8. Risk register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Terminal API/xterm split (B3) | High (feature breaks) | High | Migrate to `@xterm/xterm` + `@xterm/addon-serialize`; keep the "degrade to normal terminal" path so it never blocks the app. |
| Rebind loses because module order flipped (B1, B4) | High (webview 404s return) | Medium | Startup assertion (section 6.2) + manual B1/B4 checks in the packaged app. |
| Electron 30 -> 42 main-process breakage (B11) | High (desktop app won't launch) | Medium | Test `electron-entry.js` early (Phase 6 `package:dir`); check `powerMonitor`, `BrowserWindow`, brain spawn. |
| Packaged renderer `SIGABRT` (V8) survives the bump | High (app dies/blanks) | Low-Medium | The 19 `Undisclosed Helper (Renderer)` aborts are `node::OnFatalError` in the Electron Framework (section 3). Reproduce on a packaged Electron 42 build (Phase 6); rule out a renderer heap OOM before assuming the newer V8 fixed it. |
| `monaco-editor-core` mismatch (B9) | Medium (type/runtime errors, double Monaco) | Medium | Re-pin to the 1.76-aligned version before compiling the languages package. |
| Bundled VS Code builtins too old for the 1.76 plugin host (B10) | Medium (language features fail) | Medium | Phase 8 bump to the matching builtin release; re-verify activation. |
| Plugin host Prettier ESM requirement changes | Low (formatting only) | Low | Re-test; move off the 11.0.3 CJS pin only if the host supports ESM. |
| Two lockfiles drift (root vs desktop) | Medium | Medium | Upgrade both in the same branch; CI builds the desktop. |
| Loss of uncommitted webview fix | High | Low | Phase 0 checkpoint before any dependency change. |
| `*.bak` clutter obscuring the diff | Low | High | Exclude/clean on the upgrade branch. |

### Rollback
`git checkout main` + `npm ci` in root and `apps/desktop` (using the saved
1.60 lockfiles) + `npm --prefix apps/desktop run rebuild`. Because the upgrade is
isolated on a branch and the lockfiles are copied aside in Phase 0, rollback is
"checkout and reinstall", no source archaeology.

---

## 9. Open questions to decide before starting

1. **Scope: both targets or desktop only?** The root browser app is the dev
   surface; `apps/desktop` is what ships. Upgrading both is cleaner (shared
   extension packages demand one Theia version). Confirm both move together.
2. **Node 24 line:** the exact 24.x LTS to pin in `.nvmrc` and CI, and whether a
   local Node 24 install is available (the dev shell is on 26 today).
3. **1.76 stable vs wait for 1.77:** `next` is 1.77.0-next.14. Recommend stable
   1.76.0 now; revisit 1.77 when it ships.
4. **Terminal package migration:** adopt `@xterm/*` now (matches 1.76) or keep
   the old `xterm` shim if Theia still re-exports it.
5. **Retain vs replace deep-import overrides:** for B1 and B4, keep the rebind
   (upgrade-safe-ish, needs the order assertion) or move to `patch-package`
   (which 1.76's own `@theia/cli` now depends on)? Recommend keeping the rebind
   and adding the assertion.
6. **Rebuild budget:** `dist:mac` + plugin download is a long run. Decide who
   runs the packaged verification and on which machine (macOS/arm64).

---

## 10. Follow-ups (do these on the upgrade branch, not on `main`)

The register (`docs/features/theia-overrides.md`) is drafted and lives on `main` as
a planning artifact. Everything below is **code or config** and is deferred to
`upgrade/theia-1.76`.

| # | Follow-up | Type | Status | Where |
|---|---|---|---|---|
| F1 | Custom Binding Register | doc | **Done (on `main`)** | `docs/features/theia-overrides.md` |
| F2 | Startup assertion that `WebviewEnvironment` / `MenusContributionPointHandler` are our subclasses | code | To do | frontend module or a `FrontendApplicationContribution.onStart` |
| F3 | `scripts/theia-override-audit.sh` (symbol/path presence + webview-defect-line check) | code | To do | repo `scripts/` |
| F4 | CI `tsc` gate on the extension packages against the pinned Theia | CI config | To do | `.github/workflows/` |
| F5 | Deep-import isolation for the `@theia/plugin-ext/lib/...` imports (B1, B4) | code | To do | `packages/undisclosed-agent/src/browser/` |
| F6 | `process.dlopen` wrapper in the forked plugin host to name the addon behind the code-signing kill | code | To do | `docs/features/plugin-runtime-crash.md` section 5 (dev-Node track, independent of the upgrade) |

F2-F5 are small, but they are guardrails for the *next* upgrade, not prerequisites
for this one. Land them on the upgrade branch after Phase 7 passes, so they are
written against the 1.76 surfaces they must protect. F6 is the other way around:
it belongs to the plugin-host crash investigation, not the upgrade, so it is
tracked here only so the offer is not lost.
