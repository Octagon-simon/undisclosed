# Fix plan: media preview (Issue 1) and chatbox model picker (Issue 2)

Investigated against the running app (`theia start`, http://localhost:3000) plus the source in
`node_modules/@theia/plugin-ext`, `agent-ui/`, `plugins/`, and `brain/`.

---

## Issue 1 — PNG / GIF / audio / video won't open in the editor

### What actually happens (reproduced)

1. The `vscode.media-preview` builtin **is** installed and **is** loaded. Its custom editors are
   registered from `plugins/vscode.media-preview/extension/package.json` (view types
   `imagePreview.previewEditor`, `vscode.audioPreview`, `vscode.videoPreview`), and Theia's
   `PluginCustomEditorRegistry` picks it over the text editor because `priority: "builtin"` gives it
   opener priority 400 vs. 100 for `EditorManager`.
2. Opening `bottom.png` **does** open a preview tab. The tab is a webview, and inside it you see:

   > An error occurred while loading the image.

   So the plugin works, the custom editor opens, and the failure is **inside the webview**.

### Root cause (proven)

The webview asks the app for the file over Theia's `theia-resource` route, and that route returns
**HTTP 404 for every resource** (the preview's own CSS, its JS, and the image).

Observed URL the webview tried to load:

```
http://localhost:3000/webview/theia-resource/file//Users/octagon/Documents/github/eigent-theia/bottom.png
```

The chain:

- The webview host (`node_modules/@theia/plugin-ext/src/main/browser/webview/pre/host.js`) registers
  `service-worker.js`, which intercepts `theia-resource/*` and relays each request to the main app.
- The main app (`.../main/browser/webview/webview.ts`, `loadResource` + `normalizeRequestUri`)
  reconstructs a URI from the path and then only serves it if it sits under one of the webview's
  `contentOptions.localResourceRoots`.
- `normalizeRequestUri('/file//Users/octagon/…/bottom.png')` applies
  `replace(/^\/([a-zA-Z0-9.\-+]+)\/(.+)$/, (_, s, p) => s + ':/' + p)`, which yields
  `file://Users/octagon/…/bottom.png`. Theia's URI parser reads **authority = `Users`** and
  **path = `/octagon/…`** (verified with a Node simulation against `@theia/core`'s URI).
- `localResourceRoots` is `[dirname(file) = /Users/octagon/…/eigent-theia, <extensionRoot>]`.
  `/octagon/…` is under neither, so `loadResource` falls through and answers `{ status: 404 }`.

The URL is **one slash short**. The generator (webview environment `resourceRoot` template
`theia-resource/{{scheme}}//{{authority}}/{{path}}` + `webviews.ts#asWebviewUri`) is supposed to emit
`file///Users/…` for an empty-authority file URI, but the emitted path collapses to `file//Users/…`.
Node simulation confirms:

| request path seen | parsed authority | parsed path | inside localResourceRoots? |
|---|---|---|---|
| `/file//Users/…` (observed) | `Users` | `/octagon/…` | **no → 404** |
| `/file///Users/…` (intended) | `""` | `/Users/…` | yes → 200 |
| `/file/Users/…` (single slash) | `""` | `/Users/…` | yes → 200 |

Corroborating evidence that **all** webview resources fail, not just the image:
`curl` on `…/theia-resource/file//…/imagePreview.css`, `imagePreview.js` and `…/package.json` all
return 404, and in the live webview the computed style of `.image-load-error` is `block` (its
`display:none` rule never applied) and `<body>` never gets the `ready`/`error` class the plugin's JS
sets. The preview's CSS and JS never ran.

**In short:** the media-preview plugin is fine. Theia 1.60's webview resource URL encoding produces a
malformed `file:` resource path, and `normalizeRequestUri` mis-parses it, so `loadResource` 404s every
webview resource.

Key references:
- `package.json:53`, `apps/desktop/package.json:62` — the plugin listed in `theiaPlugins`.
- `plugins/vscode.media-preview/extension/dist/browser/extension.js` — `localResourceRoots: [Utils.dirname(resource), extensionRoot]`.
- `node_modules/@theia/plugin-ext/src/plugin/webviews.ts:252` — `asWebviewUri` substitution.
- `node_modules/@theia/plugin-ext/src/main/browser/webview/webview-environment.ts:67` — `resourceRoot` template.
- `node_modules/@theia/plugin-ext/src/main/browser/webview/webview.ts` — `loadResource` / `normalizeRequestUri`.

### Options

**Option A (recommended): ship a native Theia preview and stop depending on the webview plugin.**
- Add a small Theia extension (new package, e.g. `packages/undisclosed-media-preview`, or fold into
  `undisclosed-languages`) that contributes:
  - an `OpenHandler` for image/audio/video extensions with a priority above `EditorManager`
    (e.g. `canHandle` → 500) for `.png .jpg .jpeg .gif .webp .bmp .ico .avif .svg`,
    `.mp3 .wav .ogg .oga`, `.mp4 .webm`;
  - a `Widget` that reads the file through `FileService`/`FileSystem`, makes a blob URL with
    `URL.createObjectURL`, and renders `<img>` / `<audio controls>` / `<video controls>`. GIF
    animates natively in `<img>`. No webview, so none of the `theia-resource` plumbing is involved.
- Register it in the app's dependency list; keep "Open With → Text Editor" available.
- Remove `vscode.media-preview` from `theiaPlugins` in both `package.json` and
  `apps/desktop/package.json` once this lands, so two editors don't compete for the same file types.

**Option B (keep the plugin, patch the webview resource path).**
- Patch `@theia/plugin-ext` with `patch-package` (the webpack build already compiles from
  `node_modules/@theia/plugin-ext/src`, so a source patch is picked up):
  - emit a resource path that survives normalization (`theia-resource/{{scheme}}/{{authority}}{{path}}`
    with the leading slash kept for empty authority, or single-slash `file:/Users/…`, which the Node
    simulation shows round-trips correctly); and
  - defensively handle the collapsed `file//x` case in `normalizeRequestUri`.
- Add a `postinstall` patch step, pin it, and add a round-trip regression test (build the URL, run
  `normalizeRequestUri`, assert the resulting path matches the source file).
- Smaller change, but brittle across Theia upgrades and it only fixes webview-based surfaces.

**Option C (cheap first check):** before writing code, open a Markdown preview (or any other webview)
in the same app. If its resources also 404, that confirms this is global webview plumbing, not
media-preview-specific. Also try the default `THEIA_WEBVIEW_EXTERNAL_ENDPOINT`
(`{{uuid}}.webview.{{hostname}}`) instead of `{{hostname}}` to see whether the extra slash survives —
but based on the root cause I expect it to persist.

### Recommended sequence
1. Reproduce and record (done above).
2. Confirm the failure is global to webviews (Option C check).
3. Implement Option A (native preview). Small, durable, works on web and Electron.
4. Drop the `vscode.media-preview` entry from the shipped plugin set.
5. Regression matrix: every listed image type (incl. animated GIF), audio, and video; verify in dev
   (`theia start`) **and** in the packaged Electron app.
6. Optional follow-up: apply the Option B patch anyway if other webview features (markdown preview,
   the agent panel) need working `theia-resource` URLs.

---

## Issue 2 — the chatbox forces one model per provider

### What actually happens (reproduced from code)

- The **models screen** is the embedded `components/CodeAgentWorkspace/AgentModels.tsx` ("Add model":
  provider + API key + free-text model name + base URL). It `POST`s `/api/v1/provider`.
- The backend (`brain/app/controller/chat_platform_controller.py`) stores providers in a JSON list and
  **appends** each POST with a new auto-increment `id`. There is **no dedupe by `provider_name`**, so
  you can legitimately have several rows:

  ```
  { id: 3, provider_name: "deepseek", model_type: "deepseek-chat" }
  { id: 7, provider_name: "deepseek", model_type: "deepseek-v4-flash" }
  ```

- The **chatbox picker** is `components/ChatBox/BottomBox/ModelSelect.tsx`. It is driven by the static
  `INIT_PROVODERS` catalog (`lib/llm.ts`), fetched providers are folded onto it, and it matches only
  the **first** row per provider:

  ```ts
  const found = providerList.find(p => p.provider_name === item.id); // first match only
  ```

  plus `form`/`items` are indexed by the catalog, and the custom-model submenu renders one item per
  catalog provider.

### Consequences

1. The composer lists **one "Deepseek" entry**, not one entry per configured model. Selecting it pins
   the single (first) row's `provider_id`/`model_type`, so you can't pick `deepseek-v4-flash` vs
   `deepseek-chat`.
2. The backend's `/provider/prefer` sets `prefer` on exactly **one** row (all others are cleared), so a
   provider-level "default" can only ever point at one of the models.
3. Providers added through AgentModels whose ids aren't in the static catalog don't appear at all:
   `qwen` (catalog is `tongyi-qianwen`), `openai-compatible` (catalog is `openai-compatible-model`), and
   the local ids `lmstudio`/`vllm`/`sglang`/`llama.cpp` (different from `pages/Agents/localModels.ts`).
   So there is an id-mismatch bug on top of the collapse.
4. The desktop `pages/Agents/Models.tsx` default-model dropdown has the same provider-collapse pattern.

Key references:
- `agent-ui/src/components/CodeAgentWorkspace/AgentModels.tsx` — presets (~L64-77), `save()` (~L226-301).
- `agent-ui/src/components/ChatBox/BottomBox/ModelSelect.tsx` — catalog `items`/`form` (~L146-161),
  `find()` fold (~L179-215), `handleDefaultModelSelect` (~L407-485), custom submenu (~L597-672).
- `agent-ui/src/lib/llm.ts` — `INIT_PROVODERS`.
- `agent-ui/src/pages/Agents/Models.tsx` — desktop models page (~L154-184, ~L405-450, ~L2536-2597).
- `agent-ui/src/lib/applyDefaultModelSelection.ts` — shared default-model selection.
- `brain/app/controller/chat_platform_controller.py` — `create_provider` (no dedupe), `set_provider_prefer`.

### Fix (make the picker data-driven)

1. **Source of truth = `/api/v1/providers`.** In `ModelSelect.tsx`, replace the `INIT_PROVODERS` +
   `providerList.find(...)` fold with the actual configured rows, grouped by `provider_name`.
2. **Render every configured model.** Either a per-provider submenu (provider → its models) or a flat
   list with provider group headers. Label each entry with the `model_type`; mark the `prefer` row as
   "Default".
3. **Pin the exact row on select:**
   - global default → `POST /api/v1/provider/prefer { provider_id }` for that exact row;
   - project-pinned → `setProjectModel(projectId, { modelType: 'custom', provider_id,
     model_platform: provider_name, model_type })` from the same row.
4. **Fix provider-id consistency.** Drive both `AgentModels.tsx` and `ModelSelect.tsx` (and
   `Models.tsx`) from one shared provider registry so ids/labels can't drift
   (`lib/llm.ts` + `pages/Agents/localModels.ts`). Update AgentModels' preset ids to match.
5. **Keep an "add a new model" path** (link to the models screen / AgentModels) for providers that
   aren't configured yet, preserving the current `DEFAULT_MODEL_CONFIGURE_PATH` behavior.
6. **Apply the same change to the desktop `Models.tsx` default dropdown** so both surfaces behave
   identically.

### Tests
- Unit: given two `deepseek` rows (`deepseek-chat`, `deepseek-v4-flash`), the picker renders two
  entries and each selection pins the correct `provider_id` + `model_type`.
- Global default vs per-project pin.
- Regression: `qwen`, `openai-compatible`, and local ids appear.
- Ensure the trigger label always matches the currently preferred row.

### Risks
- "Default model" semantics change: the trigger must reflect the `prefer` row, not a catalog provider.
- Several rows for one provider usually share an API key; grouping them under one provider header keeps
  the menu readable.
- Backend is a JSON file store, so no schema migration is required.

---

## Suggested order of work

1. Issue 1, Option C check (cheap, rules out config), then Option A native preview + drop the plugin.
2. Issue 2: data-driven picker in `ModelSelect.tsx`, shared provider registry, then mirror in
   `Models.tsx`.
3. Regression pass across image/audio/video types and the multi-model picker on both dev and the
   packaged desktop app.
