# Dev-build SCM regressions: staged-file read-only editor + stuck AI-commit spinner

Status: **IMPLEMENTED** (Bug B + Option A2). Build clean; reload the app tab to pick it up.

Implemented in:
- `packages/undisclosed-agent/src/browser/git-extras-contribution.ts` and new
  `packages/undisclosed-agent/src/browser/git-commit-message-button.tsx` (Bug B).
- `packages/undisclosed-git/src/browser/staged-changes-open-contribution.ts` and
  `undisclosed-git-frontend-module.ts` (Bug A2).
Both packages `tsc` clean; `npx theia build --mode development` exit 0 with the
new code in `lib/frontend/bundle.js`. Still to confirm in the UI: the two-step
verification in section 8.

Scope: `eigent-theia` dev build (`scripts/dev.sh`, Theia 1.76, browser target on :3000 + local brain on :5001)

---

## 1. Symptoms (as reported)

1. Clicking a **staged** file in Source Control opens something you cannot edit:
   *"Cannot edit in read-only editor."*
2. The **✨ AI commit button** in the SCM toolbar spins its loader and never stops.
   (Webview and the VS Code git extension otherwise work.)

---

## 2. How the dev build actually runs (important)

`scripts/dev.sh start` runs `npm run start` →
`theia start --port 3000`, from the **prebuilt** output, not a source dev-server:

```
node lib/backend/main.js --hostname 0.0.0.0 --port 3000
```

So the running frontend is **`lib/frontend/bundle.js`** (last built Oct 6 22:45),
served by the Theia backend. Two consequences:

- A change to `packages/**/src/**` does nothing until `scripts/dev.sh build`
  (which runs the package `tsc` + `theia build`) **and** the browser tab is
  reloaded.
- The open editor is currently a **`gitrev:`** document
  (`gitrev:/…/webpack.config.js?HEAD`). `gitrev:` was the URI scheme of the
  **old `@theia/git`** provider. `@theia/git` is **gone** in this tree
  (`node_modules/@theia/git` does not exist) and the current
  `lib/frontend/bundle.js` contains **no** `gitrev` string. So that tab is a
  **restored leftover from before the 1.76 rebuild**, shown read-only because
  nothing serves that scheme any more. See section 6 — a reload is part of the fix.

---

## 3. Evidence collected (all verified on the live dev build)

**The AI-commit backend path is healthy** — this is not a "hang":
- `curl POST http://localhost:5001/git/commit-message` (tiny diff) → `200`,
  `{"success":true,...}` in ~1.1 s.
- Same call with the **real staged diff (1,001,579 bytes, 28 files)** → `200` in
  **4.3 s** with a full commit message.
- CORS preflight (`OPTIONS`, `Origin: http://localhost:3000`) → `200` with
  `access-control-allow-origin: *`.
- `git diff --cached` via the backend `/undisclosed-agent/git/exec` → `200` in
  ~0.03 s.
- `.brain.log` shows the user's own clicks as `POST /git/commit-message … 200`
  (before my test calls). **The message is generated successfully.**

**The spinner is stuck because the toolbar render crashes.** `.theia-server.log`
records exactly two client-side crashes, both at the moment the user clicked the
button (21:57:44 and 21:58:07), and nowhere else in the whole session:

```
root ERROR TypeError: Cannot read properties of undefined (reading 'node')
    at SubmenuAsToolbarItemWrapper.renderMenuItem (bundle.js:264177)
    at TabBarToolbar.render (bundle.js:266570)
    at TabBarToolbar.onUpdateRequest (bundle.js:250003)
...
root ERROR TypeError: Cannot read properties of undefined (reading 'node')
    at ToolbarActionWrapper.renderMenuItem (bundle.js:264177)
    at TabBarToolbar.render (bundle.js:266570)
```

---

## 4. Bug B — "AI commit button spins forever"

### Root cause

`GitExtrasContribution` drives the spinner by mutating a flag and forcing the
**whole SCM toolbar** to re-render
(`packages/undisclosed-agent/src/browser/git-extras-contribution.ts`):

- `setGenerating()` fires `this.onDidChangeToolbar` (lines 102-105).
- The toolbar item passes it through as `onDidChange` (line 307).
- `TabBarToolbarRegistry` debounces that into a registry-wide change, and
  `TabBarToolbar.updateItems` subscribes each item's `onDidChange` to
  `maybeUpdate()` → full re-render.

Theia's re-render of menu-based toolbar items dereferences `widget.node`:

- `node_modules/@theia/core/.../tab-bar-toolbar-menu-adapters.js:63`
  `renderMenuItem(widget)` → `… isEmpty(this.effectiveMenuPath, contextMatcher, widget.node, widget)`
- `node_modules/@theia/core/.../tab-bar-toolbar.js` `render()` calls
  `item.render(this.current, …)`; when `this.current` is `undefined`
  (widget disposed / toolbar temporarily detached) `renderMenuItem` throws.

The SCM title toolbar now contains **vscode.git menu contributions** (the 1.76
stack; `@theia/git` removed, suppressor removed), e.g. from
`plugins/vscode.git/extension/dist/main.js` `scm/title`:
`git.commit`/`git.refresh` (`group: navigation` → rendered **inline**) plus
several submenus. Those become `CommandMenuAsToolbarItemWrapper` /
`SubmenuAsToolbarItemWrapper`, i.e. the classes in the stack trace.

Because the throw happens mid-render, React never commits the "generate finished"
render, so the last committed icon (the spinning loader) stays on screen forever.
The commit message is still written (that code runs before the `finally`), which
is why it looks like "the button works, but keeps spinning".

The type doc even warns about this design:
`TabBarToolbarActionBase.onDidChange` — *"each item of the container toolbar will
be re-rendered if any of the items have changed."*

### Fix (recommended)

Stop routing the spinner through the global toolbar re-render. Use a
**React-backed toolbar item** (`ReactTabBarToolbarAction`, supported in 1.76 —
`tab-bar-toolbar-types.d.ts`), which owns its own state and re-renders only
itself:

- Register the item with `render: () => <CommitMessageButton contribution={this}/>`
  instead of `icon` + `onDidChange`.
- `CommitMessageButton` subscribes to `onDidChangeToolbar` (or better, a dedicated
  `generating` event) via `useSyncExternalStore`/`useEffect`, and renders the
  sparkle or the spinner itself.
- Keep `id`, `command: GENERATE_MESSAGE.id`, `tooltip`, `isVisible`.

Result: clicking flips internal React state only; no registry-wide `maybeUpdate`;
no `renderMenuItem` crash; the spinner clears when the request resolves.

Secondary (defensive, optional): also guard the Theia bug at the source so any
future toolbar re-render can't crash the SCM toolbar. Cleanest is a tiny
override/patch of `AbstractToolbarMenuWrapper.renderMenuItem` to use
`widget?.node`, shipped the same way as the other Theia overrides. Not required
if we adopt the React item, but it hardens the whole toolbar.

Files touched: `packages/undisclosed-agent/src/browser/git-extras-contribution.ts`
(+ its frontend-module registration stays the same).

---

## 5. Bug A — "Cannot edit in read-only editor" on staged files

### Root cause

The Theia-1.60 fix that made staged changes open the writable working file
(`packages/undisclosed-git/src/browser/writable-git-scm-provider.ts`, doc row
B12) was **retired during the 1.76 upgrade** — see the doc comment in
`packages/undisclosed-git/src/browser/undisclosed-git-frontend-module.ts`
("obsolete and has been deleted"), and `git status` shows
`D packages/undisclosed-git/src/browser/writable-git-scm-provider.ts`.

In the new stack the SCM tree is served by the bundled **vscode.git** extension
via plugin-ext:

- `node_modules/@theia/plugin-ext/lib/main/browser/scm-main.js:76`
  `PluginScmResource.open()` → `$executeResourceCommand(...)`
  → the VS Code resource's **default command**.
- That default command is chosen in `plugins/vscode.git/extension/dist/main.js`
  (`resolveDefaultCommand`, ~offset 1012507):

  ```js
  resolveDefaultCommand(e){
    return workspace.getConfiguration("git", root).get("openDiffOnClick", true)
      ? this.resolveChangeCommand(e)      // opens a read-only git diff
      : this.resolveFileCommand(e)        // vscode.open(e.resourceUri)  <- working file
  }
  ```

With the default `git.openDiffOnClick = true`, clicking a change opens a diff
whose sides are **`git:` blob URIs** (served by the extension's read-only content
provider). For a **staged** change both sides are blobs (HEAD vs index), so there
is nothing writable → "Cannot edit in read-only editor." This is stock VS Code
behavior; the 1.60 override is what previously worked around it.

### Fix options

**Option A1 — setting (smallest, recommended first).**
Add `"git.openDiffOnClick": false` to the frontend preferences in `package.json`
(`theia.frontend.config.preferences`, next to `files.enableTrash`) and mirror it
in `apps/desktop`. Effect: clicking any SCM change opens the **working file**
(`vscode.open` with `sourceUri`) — editable. The diff stays one click away via the
inline "Open Change" (`$(compare-changes)`) action and the editor title. The
extension re-computes resource commands on config change, so no plugin restart is
needed.
Trade-off: applies to *all* change groups (unstaged too), and you lose
diff-on-single-click. Simple, zero code, easy to revert.

**Option A2 — code override (matches the old B12 behavior exactly).**
Re-introduce a targeted override so staged resources open with the working file
on the right of the diff:
- For **staged new** files → open `sourceUri` (`file:`).
- For **staged modified** files → diff `git:index` (left) vs `file:<worktree>`
  (right); the right pane is writable.
- For **staged deleted** files → keep the HEAD blob (read-only is correct).

Implementation hook: monkey-patch `PluginScmResource.prototype.open()` (or
intercept the plugin resource command) in the `undisclosed-git` frontend module,
keyed off the resource's group id (`index` vs `workingTree` vs `untracked`).
More faithful to B12, but fragile: it depends on the extension's `git:` URI
format and on plugin-ext internals.

**Recommendation:** ship **A1** now (restores editability with no internals
coupling); keep A2 documented as the fallback if single-click-diff matters.

---

## 6. Also required: reload the build

The dev server serves the prebuilt bundle, and the editor is holding a stale
`gitrev:` document that no code path can produce any more. After building, the
window must be reloaded. Plan / verification therefore includes:

```
./scripts/dev.sh build          # tsc packages + theia build (dev)
# then reload the app tab (or ./scripts/dev.sh restart)
```

---

## 7. Proposed changes (summary)

| # | File | Change |
|---|------|--------|
| 1 | `packages/undisclosed-agent/src/browser/git-extras-contribution.ts` | Replace the icon/`onDidChange` toolbar item with a self-stateful `render` (React) item; spinner owned locally. |
| 2 | `packages/undisclosed-agent/src/browser/git-extras-contribution.ts` | (optional) `AbortController` + timeout on the commit-message `fetch` so a dead brain fails visibly instead of spinning. |
| 3 | `package.json` (+ `apps/desktop/package.json`) | Add `"git.openDiffOnClick": false` preference (Option A1). |
| 4 | (optional) Theia override module | Defensive `widget?.node` guard in `tab-bar-toolbar-menu-adapters` `renderMenuItem`. |
| 5 | `packages/undisclosed-git` | (only if A2 chosen) staged-resource open override. |

---

## 8. Verification plan

Bug B:
1. `./scripts/dev.sh build` → reload.
2. Stage a change, click ✨. Expect: loader spins ~1-5 s, then returns to the
   sparkle; commit box is filled; **no** `reading 'node'` in `.theia-server.log`.
3. Repeat while switching panels mid-request (the case that made `current`
   undefined).

Bug A:
1. With `git.openDiffOnClick: false`, click a staged **new** file → opens the
   working file, edit + save lands on disk.
2. Click a staged **modified** file → editable target (working file, or diff with
   writable right pane if A2). Confirm `Cmd+S` persists.
3. Click a staged **deleted** file → still the read-only HEAD view (expected).
4. Confirm unstaged files still open a useful diff.

Regression: run a TypeScript typecheck on the touched packages before declaring
done (`npm --prefix packages/undisclosed-agent run build`).

---

## 9. Open questions / risks

- I could not drive the live SCM UI from here, so Bug A's *current* on-click
  behavior is inferred from the extension code (`resolveDefaultCommand`) plus the
  fact that the open doc is a stale `gitrev:` tab. Step 8.1 settles it.
- If the user's tab predates the 22:45 rebuild, both symptoms may differ after a
  reload; re-test before deeper changes.
- A1 changes click behavior for unstaged files too — confirm that is acceptable,
  otherwise choose A2.
