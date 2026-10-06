# Explorer auto-reveal: why the active file is flaky in the file tree

Status: FIXED. Reproduced live, fix shipped in `packages/undisclosed-agent` (see
"Fix (implemented)" below).

## TL;DR

The explorer's "follow the active editor" feature is wired to **one** signal:
`ApplicationShell.onDidChangeCurrentWidget`. That signal only fires when the
*current widget actually changes*. Clicking a tab that is **already the current
widget** fires nothing, so the navigator is never asked to reveal it.

Result: if the tree is out of sync with the editor (selection cleared,
folder collapsed, or the reveal was simply missed when the file first became
current), clicking that file's tab again does nothing. You have to switch to a
different tab first, which changes the current widget and finally triggers a
reveal. That is exactly the "click file 3, then file 2, then file 1 and it
shows" behaviour.

The reliable signal that fires on *every* tab click, including a re-click of the
active tab, is the tab bar's `tabActivateRequested`. That is where a fix should
hook.

## Where the behaviour lives

All of this is stock Theia 1.60 (`node_modules/@theia/navigator`), no local
override. Verified nothing in `packages/**`, `src-gen/**` or `apps/**`
re-registers or replaces the navigator.

- Registration, `navigator-contribution.ts:187`, inside the async `doInit()`
  (which first `await`s `fileNavigatorPreferences.ready`, `:186`):

  ```ts
  this.shell.onDidChangeCurrentWidget(() => this.onCurrentWidgetChangedHandler());
  ```

- Handler, `navigator-contribution.ts:631`:

  ```ts
  protected onCurrentWidgetChangedHandler(): void {
      if (this.fileNavigatorPreferences['explorer.autoReveal']) {
          this.selectWidgetFileNode(this.shell.currentWidget);
      }
  }
  ```

- Reveal, `navigator-contribution.ts:615` → `selectFileNode` `:619`:

  ```ts
  async selectWidgetFileNode(widget) { return this.selectFileNode(NavigatableWidget.getUri(widget)); }
  async selectFileNode(uri) {
      if (uri) {
          const { model } = await this.widget;
          const node = await model.revealFile(uri);
          if (SelectableTreeNode.is(node)) { model.selectNode(node); return true; }
      }
      return false;
  }
  ```

- `FileNavigatorModel.revealFile` (`navigator-model.ts:177`) expands the
  ancestor chain and returns the file node; `selectNode` then selects it and the
  tree scrolls (`TreeWidget.getScrollToRow` / `scrollToSelected`).

`explorer.autoReveal` defaults to `true` (`navigator-preferences.ts`). The only
other place it is read is the "toggle auto reveal" command.

## What I verified live

I drove the running dev editor (`http://127.0.0.1:3000`, Theia 1.60) over CDP,
opened a workspace and five `.md` files in five different folders, collapsed the
explorer, and clicked tabs with real mouse events.

Reveal on _change_ works fine:

- click `LICENSE-SYSTEM.md` → current = LICENSE-SYSTEM.md, explorer select = LICENSE-SYSTEM.md
- click `README.md` → current = README.md, explorer select = README.md

Reveal on _re-click of the already-current tab_ does nothing:

```
collapse tree                         -> explorer select = []      (selection gone)
click LICENSE-SYSTEM.md (already current)
                                      -> explorer select = []      <-- no reveal
click README.md                       -> explorer select = [README.md]
click LICENSE-SYSTEM.md               -> explorer select = [LICENSE-SYSTEM.md]
```

The same call, invoked directly while the file is current, does reveal:

```
collapse tree
forced selectWidgetFileNode(currentWidget) -> explorer select = [LICENSE-SYSTEM.md]
```

So the reveal logic itself is healthy. The bug is purely in the trigger.

Event probe on the tab bar (with listeners attached to the shell's `TabBar`):

```
click current tab  -> ["tabActivateRequested"]
click same again   -> ["tabActivateRequested"]
click other tab    -> ["shellCurrentChanged", "currentChanged", "tabActivateRequested"]
```

`tabActivateRequested` fires on every click. `currentChanged`
(`onDidChangeCurrentWidget`) only fires when the selection actually moves.

## Why it looks "flaky"

The explorer and the editor drift out of sync whenever the file becomes current
without the reveal taking effect, and nothing re-syncs them afterwards:

1. **Startup / restore race.** The listener is registered late (after
   `fileNavigatorPreferences.ready`, `navigator-contribution.ts:186`) and
   `FileNavigatorModel.initializeRoot()` is itself async (waits for
   `initialized_layout` + workspace roots). A reveal that races the tree coming
   up can be silently dropped (`revealFile` returns `undefined`, and
   `selectFileNode` just returns `false`).
2. **Non-tab ways of activating an editor.** Opening a file via the agent,
   "Open Recent", a quick-open, or a restored session can set the current widget
   through paths that don't produce a clean change, or before the navigator is
   ready.
3. **Then the user's own action can't recover it.** Once the file is the current
   widget, clicking its tab fires no change event, so no reveal. Only switching
   away and back forces one.

There are secondary robustness gaps too: `selectWidgetFileNode` is fired
un-awaited and uncancelled, so overlapping reveals (fast tab switching) race;
`revealFile` expands ancestors through async filesystem resolves with no retry;
and the fail path is silent (`return false`), which is why it presents as
"sometimes".

## Fix (implemented)

The fix lives in a small frontend contribution that calls the navigator's public
API, so the dependency is not forked:

- `packages/undisclosed-agent/src/browser/undisclosed-explorer-auto-reveal-contribution.ts`
  (`UndisclosedExplorerAutoRevealContribution`)
- bound as a `FrontendApplicationContribution` in
  `packages/undisclosed-agent/src/browser/undisclosed-agent-frontend-module.ts`
- `@theia/navigator` added to `packages/undisclosed-agent/package.json`

It hooks `tabActivateRequested` on every tab bar and calls
`FileNavigatorContribution.selectWidgetFileNode(title.owner)`, gated on
`explorer.autoReveal`. `title.owner` is used (not `shell.currentWidget`) so the
reveal does not depend on activation ordering, and `selectWidgetFileNode` is a
no-op for non-navigatable tabs (Explorer, Search, terminals, ...).

Correction to the earlier sketch: there is **no** `shell.onDidCreateTabBar`.
That signal (`onDidCreateTabBar`) lives on the internal `DockPanelRenderer`, and
`DockPanelRenderer` is bound transient, so the main and bottom panels each get
their own renderer; subscribing to one injected renderer would miss the others.
Instead the contribution (re)scans `shell.allTabBars` at `onStart`, on
`shell.onDidAddWidget`, and on `shell.onDidChangeCurrentWidget`, attaching at
most once per tab bar (tracked with a `WeakSet`).

Notes / tradeoffs:
- `selectWidgetFileNode` is already a no-op for non-navigatable widgets, so
  panel tabs (Explorer, Search, …) are unaffected.
- Keep `onDidChangeCurrentWidget` as well, otherwise Ctrl+Tab / keyboard editor
  switching and command-opened files stop revealing.
- Consider a small guard to avoid revealing when the target is already the
  selected navigator node (cheap, avoids redundant scrolling).
- Optional hardening for the startup race: make `selectFileNode` retry once
  after the navigator model reaches its root, or await `model.ready`-equivalent
  before the first reveal.

## Files involved

- `node_modules/@theia/navigator/lib/browser/navigator-contribution.js` (source:
  `.../src/browser/navigator-contribution.ts`) — the trigger + reveal.
- `node_modules/@theia/navigator/lib/browser/navigator-model.js` — `revealFile`.
- `node_modules/@theia/core/lib/browser/shell/application-shell.js` — `TabBar`,
  `onDidCreateTabBar`, `onDidChangeCurrentWidget`, `allTabBars`.

Because the navigator is a dependency, the fix is either an upstream patch
(`patch-package`) or a small custom `FrontendApplicationContribution` in
`packages/undisclosed-agent`. The custom contribution route was taken; it hooks
the tab bars and calls the public `FileNavigatorContribution.selectWidgetFileNode`,
so nothing is forked.

## Verified live (after the fix)

A dev build served the running app, then a five-file workspace (five folders,
`file1.md`..`file5.md`) was opened and the already-active tab was clicked while
the current widget was unchanged:

```
current widget        = file5.md   (before and after, i.e. no widget change)
explorer selection    = file4.md   (before click)
click file5.md tab    -> explorer selection = file5.md
```

Because `file5.md` was already the current widget, the stock
`onDidChangeCurrentWidget` path could not have fired; the reveal came from the
new `tabActivateRequested` hook. Pre-fix, the same sequence left the selection
on `file4.md`.
