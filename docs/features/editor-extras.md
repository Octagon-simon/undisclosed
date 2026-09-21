# Editor extras (SCM, welcome, Storybook, languages, packaging)

This doc collects the editor-shell work that is not the agent itself but makes
Undisclosed feel like a real editor-first product.

---

## Source control + git extras

**Problem.** In git repos the editor showed "no repo found": the Theia git/SCM
extensions were simply not bundled.

**Solution.** Bundle `@theia/git` + `@theia/scm` + `@theia/scm-extra`, which gives
the full SCM stack (Source Control view with A/M/U, click-to-diff, dirty-diff
gutter, stage/unstage/commit/amend, merge editor, stash, pull/push/sync, history)
using system git.

Then fill the gaps developers expect with
`packages/undisclosed-agent/src/browser/git-extras-contribution.ts`:

| Command | Implementation |
| --- | --- |
| Undo Last Commit (keep changes) | `reset --soft HEAD~1` |
| Undo Last Commit (discard changes) | `reset --hard HEAD~1` (confirmed) |
| Unstage All | `reset` |
| Discard All Changes | `checkout -- .` (confirmed) |

Available in the command palette and a Git main menu. Needs a full Theia build.

## Welcome widget

A first-run welcome screen is contributed as a Theia widget
(`undisclosed-welcome-widget.tsx` + `undisclosed-welcome-contribution.ts`). It
opened the way for the desktop entry scaffolding and the component Storybook.

## Storybook

Rebuilding the whole Theia editor to see one UI change is slow, so `agent-ui`
has Storybook for component work: `cd agent-ui && npm run storybook` serves
hot-reloading components on `:6006`, separate from the full editor rebuild.

## Languages and VS Code import

- `packages/undisclosed-languages/`: Monaco/Monarch language support (see its
  `add-language.cjs`), including the language and file-type brand icons.
- `packages/undisclosed-import/`: import VS Code settings and extensions.

## Keyboard guard (Cmd/Ctrl+A)

The agent panel shares one DOM with Theia (no iframe), so Theia's global
keybindings can intercept shortcuts typed in the panel's `contenteditable`.
`mount.tsx` installs a window-capture guard that stops propagation for
`Cmd/Ctrl+A` when the target is one of the panel's inputs, so the browser selects
the input's text and Theia's editor select-all never fires. (The clipboard
`Cmd+C/X/V` clash, caused by Theia's document-capture keybinding handler routing
to the active Monaco editor, is the same class of problem.)

## File-type icons and pretty activity

`agent-ui/src/components/ChatBox/MessageItem/ActivityTraceCard.tsx` renders
colored, outlined file-type badges (TS, TSX, JS, PY, JSON, MD, CSS, HTML, Go,
Rust, ... with special cases for `package.json`, README, Dockerfile, `.env`), and
`activityClassifier.ts` humanizes the agent's activity trace (Read/Edited/Wrote
file, Fetched, Loaded skill, MCP connector actions) with click-to-open paths and
+N/-M diff stats on edits.

## Packaging and dev scripts

- `apps/desktop/` is the Electron Theia shell that bundles the editor and the
  frozen (PyInstaller) brain into one installable app. See
  [../PACKAGING.md](../PACKAGING.md).
- `scripts/dev.sh`: start/stop/restart/build/rebuild/status/logs for the local
  Theia server, pins Node 20, waits for HTTP 200, and rebuild always restarts both
  Theia and the brain so a bad build cannot leave you backend-less.
- `scripts/brain.sh`: start/stop/restart/logs/status for the brain.
- `scripts/build-brain.sh`: freeze the brain for packaging.

## Key commits

`b4e3e33` (git SCM + diff/Cmd+A), `03de54f` (git extras), `99f8e0e` (Storybook +
welcome widget), `42ba7bc` (welcome screen + `UNDISCLOSED_` rename), `2573fb8`
(brand icons), `6acfe4d`/`e8166d0` (UI vendor + webviews/auto-login/theme).
