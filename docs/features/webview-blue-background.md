# Why webview pets render a blue background instead of the pet

Investigated 2026-10-06 against the running dev app (`theia start`, http://localhost:3000),
the installed extensions under `~/.theia/deployedPlugins`, and Theia 1.60 in `node_modules/@theia`.

**Verdict: yes, it is the webview.** The pets are webview extensions, and every resource the
webview loads (`webview.asWebviewUri(...)`) 404s in this Theia build. When the JS that paints the
scene fails to load, all you see is the webview's flat fallback colour. For Capibara Pet that
fallback is literally `#93cbf4`, a light sky blue.

This is the same defect already documented for the media preview (see
`docs/media-preview-and-model-picker-plan.md`); the pets are just a second, very visible symptom.

---

## 1. How these pets render (they are webviews)

**Capibara Pet** (`juancarloscondori.capibara-pet-0.10.0`) contributes a webview **view** in the
Explorer (`package.json`: `views.explorer[0].type = "webview"`). Its whole visual is produced inside
the webview:

- `out/extension.js:81-85` — a helper `uri(webview, file)` → `webview.asWebviewUri(Uri.joinPath(extensionUri, 'media', file))`.
- `out/extension.js:111` / `:115` — sprite sheet PNGs referenced as CSS `background-image:url('...')`.
- `out/extension.js:203` — the scene renderer: `<script src="${this.uri(webview,'pixelart.js')}">`.
- `out/extension.js:224` — the inline script calls `window.PixelArt.create({...})` to draw the
  procedural scenery (sky, hills, lake, weather).

**VS Code Pets** (`tonybaloney.vscode-pets`) works the same way: a webview whose JS/assets come from
the extension and are addressed through `asWebviewUri`. Both fail for the same reason.

### Where the blue comes from (Capibara Pet)

`out/extension.js:121` reads config `background` (default `"time"`), and `:136` sets the stage
fallback:

```js
const bgPref = cfg.get('background', 'time');      // line 121, default "time"
...
if (mode === 'scene' || mode === 'time') {
    stageBg = 'background:#93cbf4;';               // line 136  <- the blue you see
}
```

`html,body` are `background:transparent` (`:160`); the solid `#93cbf4` lives on `#stage`. `pixelart.js`
is what paints over it. So:

- If `pixelart.js` loads → procedural scene covers the blue.
- If `pixelart.js` 404s → `window.PixelArt` is `undefined`, `PixelArt.create(...)` throws, nothing is
  drawn, and you are left staring at `#stage{background:#93cbf4}` = the blue panel.

That is exactly the reported symptom: "renders a blue background instead of painting the actual view".

---

## 2. Root cause: the webview resource URL is malformed (proven)

Theia serves webview resources through a service worker and a `theia-resource` route. The URL for
`asWebviewUri(resource)` is built from a template in `WebviewEnvironment.resourceRoot`:

`node_modules/@theia/plugin-ext/lib/main/browser/webview/webview-environment.js:57`

```js
async resourceRoot(host) {
    ...
    return (await this.externalEndpointUrl())
        .resolve('theia-resource/{{scheme}}//{{authority}}/{{path}}')   // <-- double slash is the point
        .toString(true);
}
```

The `//` before `{{authority}}` is deliberate: for a `file:` URI the authority is empty, and the
intent is `theia-resource/file///Users/...` (three slashes) so the receiver can reconstruct
`file:///Users/...`. **But `URI.resolve()` normalises the path and collapses the empty segment**, so
the `//` becomes `/` before the placeholders are ever substituted.

I reproduced the whole chain in Node against the real `@theia/core` `URI` (`.tmp/sim3.js`):

```
1) resourceRoot template : http://localhost:3000/webview/theia-resource/{{scheme}}/{{authority}}/{{path}}
                                                                    ^^ collapsed to one slash
2) emitted <script src>  : .../theia-resource/file//Users/octagon/.../media/pixelart.js
3) requestPath to widget : /file//Users/octagon/.../media/pixelart.js
4) normalizeRequestUri   : file://Users/octagon/...  => authority="Users"  path=/octagon/...
5) inside localResourceRoots[.../extension/media]? -> false   => 404
```

Step by step:

- `webviews.js:208` (`asWebviewUri`) does `{{path}}` ← `resource.path.replace(/^\//,'')` (strips the
  leading `/`), so `file` + `//`(collapsed to `/`) + `` + `/` + `Users/...` → **`file//Users/...`**
  (only two slashes). The correct form needs three.
- The service worker (`pre/service-worker.js:203`) strips the `/webview/theia-resource` prefix and
  forwards requestPath `/file//Users/...` to the webview widget.
- `webview.js:426` `normalizeRequestUri` rewrites `/file//Users/...` → `file://Users/...`. Theia's
  URI parser reads this as **authority = `Users`**, **path = `/octagon/...`**.
- `webview.js:382` `loadResource` only serves the file if `normalizedUri.path` is equal-or-parent of
  one of the webview's `localResourceRoots`. The root is the extension's `media/` dir
  (`/Users/octagon/.../media`); the parsed path is `/octagon/...`, which is under nothing → it falls
  through and answers **404** (`webview.js:415-419`).

With the intended three slashes (`file///Users/...` → `file:///Users/...` → authority `""`,
path `/Users/...`) the check passes and the resource would be served. That is the one-character bug.

### Consequence for the pets

Every `asWebviewUri` resource 404s: `pixelart.js` (capybara scene), `chiptune.js` (sounds), and all
the `*_sheet.png` sprites (CSS `background-image`). So the pets cannot paint at all. VS Code Pets has
the identical dependency on webview resources.

---

## 3. Live observations in the dev app

Driving the running app over CDP (`.tmp/wveval.js`, `.tmp/cdpeval.js`):

- The Capibara view renders one webview iframe
  (`http://<uuid>.webview.localhost:3000/webview/index.html?id=...`), with the inner
  `#active-frame` iframe (`.tmp/pet/capibara-view.png` captured).
- In the current dev session the inner frame's body was **empty** (`bodyLen 0`, no `pixelart.js`
  `<script>`, no `#stage`), i.e. the extension HTML itself was not delivered to the view. That is a
  second, more severe failure mode: it lines up with the "Plugin runtime crashed unexpectedly" toast
  and the earlier `Failed to initialize ... plugin` entries — if the plugin host is down, the webview
  view never gets content at all.
- Either way the pet does not render: (a) content present but resources 404 → flat `#93cbf4` blue;
  (b) content absent → blank panel.

Note: a raw `curl` of a `theia-resource` URL always returns 404, because that route is served by the
frontend service worker, not the backend. Use the in-page/CDP path to test it, not curl.

---

## 4. Fix options

The bug is in Theia (`node_modules/@theia/plugin-ext`), not in this repo, so it needs one of:

**Option A (recommended): rebind `WebviewEnvironment` with a corrected `resourceRoot`.**
Add a small subclass in `packages/undisclosed-agent` that builds the resource-root string **without**
routing it through `URI.resolve` (string-concatenate against `externalEndpointUrl()`), so the literal
`{{scheme}}//{{authority}}/{{path}}` survives and a `file:` resource becomes `file///Users/...`.
Bind it in the frontend module to override the default. Upgrade-safe-ish, no dependency edit.

**Option B: `patch-package` the `resourceRoot` line** (or `normalizeRequestUri`/`loadResource`) in
`@theia/plugin-ext`. Smallest diff, but brittle across Theia upgrades.

**Option C: don't rely on webview resources for first-party surfaces.** Fine for the media preview
(see the media-preview doc, which recommends a native preview), but you cannot do this for
third-party marketplace extensions like the pets — for those, A or B is the only route.

A robustness fix on the receiving side is also possible: in `loadResource`, when
`normalizeRequestUri` yields a non-empty `authority` for a `file` resource, re-attempt with the
authority folded back into the path. That heals the mis-encoded URL but is a workaround for the
symptom rather than the defect.

---

## 5. Status: Option A implemented (and why upgrading does not help)

**Implemented 2026-10-06 (Option A).**

- `packages/undisclosed-agent/src/browser/undisclosed-webview-environment.ts` — `UndisclosedWebviewEnvironment extends WebviewEnvironment`, overriding `resourceRoot(host)` to build the template by **string concatenation** against `externalEndpointUrl()` instead of `URI.resolve(...)`, so the `{{scheme}}//{{authority}}` separator survives. The `frontend` branch is delegated to `super` (it uses `withPath()` and has no authority segment to preserve).
- `packages/undisclosed-agent/src/browser/undisclosed-agent-frontend-module.ts` — `rebind(WebviewEnvironment).to(UndisclosedWebviewEnvironment).inSingletonScope()`. Our frontend module loads after `@theia/plugin-ext`'s, the same mechanism already used to rebind `MenusContributionPointHandler`, so this override wins.

Verified end-to-end in Node against the real `@theia/core` `URI` (upstream vs fixed template, then `asWebviewUri` substitution, the service-worker slice, `normalizeRequestUri`, and the `localResourceRoots` gate):

```
UPSTREAM  scheme=file authority="Users" path=/octagon/.../media/pixelart.js   inLocalResourceRoots=false  -> 404
FIXED     scheme=file authority=""      path=/Users/octagon/.../media/pixelart.js  inLocalResourceRoots=true -> 200
```

The package typechecks (`tsc -p packages/undisclosed-agent`, exit 0).

**Does upgrading Theia fix it? No.** The defect is still present verbatim in the upstream source:

- `v1.75.0` tag: `return (await this.externalEndpointUrl()).resolve('theia-resource/{{scheme}}//{{authority}}/{{path}}').toString(true);`
- `master`: the identical line (only shifted by one line number).

So `1.60 -> 1.75/1.76` would not fix the pets or the media preview; the rebind remains necessary. (npm `latest` for `@theia/plugin-ext` is in fact `1.76.0`.) Treat the version bump as a separate, much larger piece of work, not as a fix for this bug.

To take effect the frontend bundle must be rebuilt: `npm run build` (or `npm run watch`) for the dev app, `npm run dist` / `dist:mac` for the desktop build.

---

## 6. Full width: the injected `body { padding: 0 20px }`

Once B1 landed the pet renders, but the webview content is still inset 20px on each
side. The webview host script
`@theia/plugin-ext/src/main/browser/webview/pre/main.js` (copied to `lib/webview/pre`
at build time and served by the backend at `/webview`) defines `defaultCssRules` with:

```css
body { … margin: 0; padding: 0 20px; }
```

That is a Theia-only deviation (modern VS Code uses `padding: 0`). It is prepended to
every webview document, so Capibara's `#stage { width: 100% }` resolves against a
141px content box instead of the 181px panel: measured `#stage` 141px vs body 181px,
i.e. the scene is 40px narrower than the panel.

**Fix (B13 in `theia-overrides.md`).** Rewrite that one declaration as the `webview/pre`
folder is copied during the build. `webpack.config.js` and
`apps/desktop/webpack.config.js` add a `transform` to the `CopyWebpackPlugin` pattern
whose `from` ends in `webview/pre`, replacing `padding: 0 20px;` with `padding: 0;`
in `main.js` only.

Verified live on the dev server (webview body computed `padding: 0px`, `#stage` 181px =
panel width; `PixelArt` loaded). Scope is **global** (every webview), and because it is
a build-time transform it only takes effect after `npm run build` / `theia build`; a
running server keeps serving the previous `lib/webview/pre/main.js` until then.

## 7. Key references

Capibara Pet (installed):
- `~/.theia/deployedPlugins/juancarloscondori.capibara-pet-0.10.0/extension/out/extension.js`
  — `uri()` L81-85, stage fallback `#93cbf4` L136, `pixelart.js` script L203, `PixelArt.create` L224.

Theia 1.60:
- `node_modules/@theia/plugin-ext/lib/main/browser/webview/webview-environment.js:57` — `resourceRoot` template (the defect).
- `node_modules/@theia/plugin-ext/lib/plugin/webviews.js:208` — `asWebviewUri` (strips leading `/`).
- `node_modules/@theia/plugin-ext/lib/main/browser/webview/webview.js:382` — `loadResource`; `:426` — `normalizeRequestUri`.
- `node_modules/@theia/plugin-ext/src/main/browser/webview/pre/service-worker.js:203` — requestPath slice.
- `node_modules/@theia/plugin-ext/src/main/browser/webview/pre/main.js:71` — webview body background is `var(--vscode-editor-background)`.

Related prior work:
- `docs/media-preview-and-model-picker-plan.md` — same defect seen through the media-preview plugin.
