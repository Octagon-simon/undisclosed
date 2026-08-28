# Eigent Editor (Theia product)

Eigent's editor-first shell, built as a **custom Eclipse Theia product** — not a
fork. The code editor is the primary surface; Eigent's agent panel and features
are added as **native Theia contributions** (the Antigravity model: the agent
lives *inside* the editor, one integrated surface — not an external dock beside
an embedded iframe, which is what code-server forces).

## Why Theia (not code-server)

code-server is stock VS Code: it ships its own chat/Copilot chrome and can't be
stripped or extended enough to host our agent as a first-class panel. Theia is a
**framework** — you compose `@theia/*` packages + your own extensions, disable
built-in views, and register your own **`ReactWidget`** as a native panel. That
is the only path to "the editor's agent section *is* Eigent's agent."

## Architecture (how it plugs into Eigent)

- **Browser target.** `theia build` + `theia start` produce a local Node server
  (`node lib/backend/main.js`, bound to `127.0.0.1:{port}`), opened on a folder.
  This matches exactly how the main Eigent app already spawns an editor engine:
  `CodeEditorManager` reads `~/.eigent/editor/launch.json` (`{ "cmd": "…{port}…
  {dir}…" }`) and spawns it. So swapping code-server → this Theia build is a
  `launch.json` change — the engine seam is already there (`EIGENT_THEIA_*`).
- **Backend untouched.** Eigent's FastAPI agent backend (models, toolkits, SSE)
  stays as-is. "Bring your own models" and existing features are preserved
  because they live server-side; the editor is just the skin.

## Roadmap

1. **Stand up Theia** (this repo): a minimal, working browser editor. ← current
2. **Rebrand + strip chrome**: app name, disable Theia's built-in AI, trim the
   layout so it reads as Eigent, not stock Theia.
3. **Native agent widget**: a custom Theia extension contributing a `ReactWidget`
   in the right panel — later hosts Eigent's (decoupled) agent UI, driven by the
   Eigent backend over REST/SSE.
4. **Eigent features as contributions**: Context / Scheduled / Dispatch, spaces,
   history — as Theia views / a custom area.
5. **Package per-OS** and wire into the main app via `launch.json`
   (`EIGENT_THEIA_BUNDLE_URL` / download-on-first-use, mirroring the current
   provisioner).

> Agent decoupling (extracting Eigent's agent UI + its store/SSE layer into a
> self-contained package) is deliberately **deferred** until Theia itself is
> standing and rebranded. Get the editor working first.

## Develop

```bash
nvm use            # Node 20 (Theia targets 18/20; newer Node breaks native deps)
npm install        # heavy (~Theia is large); native deps use prebuilt binaries
npm run build      # webpack the frontend + generate the backend server
npm start          # serve at http://127.0.0.1:3000
```
