# Implementation Plan: Real SVG Language Icons for the Activity Trace (replacing the hand-rolled badge)

**Status:** IMPLEMENTED (S1-S5 landed) — S6/S7 remain
**Date:** 2026-09-13
**Scope:** Replace the hardcoded `FILE_BADGE` text-chip in the activity trace with real
per-language SVG logos sourced from Simple Icons, and widen language coverage.
**Primary file today:** `agent-ui/src/components/ChatBox/MessageItem/ActivityTraceCard.tsx`

---

## What actually shipped (2026-09-13)

- **Scraper/generator:** `scripts/fetch-file-icons.mjs` (Node + `fetch`, no new deps),
  wired as `agent-ui` script `icons:file-extensions`. Supports the default networked run,
  `--offline` (cache-only) and `--check` (stale-output gate).
- **Generated artifacts (committed):**
  - `agent-ui/src/assets/fileIcons.generated.ts` — **75** icon entries keyed by extension
    (`FILE_ICON_PATHS`) + `FILE_ICON_FALLBACK_EXTENSIONS` + `FILE_ICON_META` provenance.
  - `agent-ui/src/assets/fileIcons.LICENSE.md` — attribution notice + per-icon source table.
- **Renderer:** `FileTypeIcon` in `ActivityTraceCard.tsx` now renders a real `<svg>` when the
  extension resolves, and falls through to the legacy chip otherwise. `IMAGE_EXTS` untouched.
- **Attribution stand:** logos belong to their owners; we claim no ownership and grant no
  licence. Stated in the generated module header, in `fileIcons.LICENSE.md`, and in the plan.
- **Dark mode:** data-driven `mono` flag (28/75 entries) renders `currentColor`; `mono` is set
  by the generator when the brand hex luminance is `< 0.12`, because at that point the brand
  colour no longer reads once the surface flips. No `filter: invert(1)` anywhere in this path.
- **Anthropic logo (the model picker, separate surface):** routed through a single
  `modelImageStyle(modelId, appearance)` helper in `src/shared/modelProviderImages.ts`, and
  the five ad-hoc `style={needsInvert(x) ? { filter: 'invert(1)' } : undefined}` sites in
  `Models.tsx` / `ModelSelect.tsx` now call it. The rule itself is unchanged (dark marks
  invert on dark backgrounds) — it just lives in one place now, so a caller cannot forget it.

### One unplanned addition you should know about: `bun` / `deno` / `gradle` are `mono`

Simple Icons prints these as solid black marks, so an unmodified brand-hex render would be
black-on-black in dark mode. They are in the `mono` set and inherit the icon token, exactly
like the lucide icons on the row already do. Same for `cpp`/`cc`/`cxx` (`#00599C`), `xml`
(`#005FAD`), `css` (`#663399`), `toml`, `erl`, `prisma`, `cmake`. If you would rather keep
brand colour for those and accept lower contrast, flip the threshold in the generator.

---

## TL;DR

- **Yes, we have everything we need to scrape.** No scraper framework is installed
  (no scrapy / playwright / BeautifulSoup), but we do not need one: Simple Icons ships
  a **static JSON dataset + a CDN**, and Node 24's built-in `fetch` + `npm` already
  work in this repo. **No new runtime dependency is required.**
- Recommended pipeline: `slugs.md` (title → slug) → `data/simple-icons.json`
  (hex + license + source) → `cdn.simpleicons.org/<slug>` (raw SVG) →
  **one generated TypeScript module, committed**. The UI then renders paths with
  `currentColor` and no runtime network calls.
- The current `FILE_BADGE` map already has ~36 extensions; this plan keeps
  feature parity and grows the curated set to ~75-90 while adding language icons
  for extensions that have no brand logo via a generic file-type fallback.

---

## Ground truth (verified in code + by live probe on 2026-09-13)

### The thing we are replacing
`agent-ui/src/components/ChatBox/MessageItem/ActivityTraceCard.tsx`
- `FILE_BADGE` (lines 59-96): `Record<string, { label: string; color: string }>`, 36 keys.
- `IMAGE_EXTS` (98-100), `badgeFor(path)` (102-116), `FileTypeIcon({ path })` (118-140).
- `FileTypeIcon` renders an **outlined chip**: `border` + `color` + a 2-4 char mono label.
  This is what becomes an `<svg>`.
- Call site: `ActivityItemRow` line 216, inside the clickable file link.

### The activity trace is always on
`agent-ui/src/lib/activityClassifier.ts:749` → `isActivityTraceEnabled()` returns
`true` unconditionally. There is no flag to gate a rollout: **any visual change here
is user-visible immediately**, so the visual diff needs a deliberate review pass.

### What "scraping" resources exist here
| Need | Status |
|---|---|
| `curl` | present (8.7.1) |
| Node | v24.1.0 — global `fetch`, `node --experimental-strip-types` era |
| Python | 3.14.6, but **no** requests/httpx/bs4/scrapy/playwright installed |
| Package manager | npm (`package-lock.json` at repo root; `agent-ui` also has its own lock) |
| `simple-icons` npm/pkg | **not** installed anywhere in the repo |
| Scrape target reachability | `https://simpleicons.org/` → 200; `https://cdn.simpleicons.org/typescript` → 200, `image/svg+xml` |
| Upstream machine-readable data | `https://raw.githubusercontent.com/simple-icons/simple-icons/develop/data/simple-icons.json` → 200, 3460 icons, fields `title, hex, source, aliases, license?` |
| Title → slug map | `https://raw.githubusercontent.com/simple-icons/simple-icons/develop/slugs.md` → 200, 3460 rows `| \`Name\` | \`slug\` |` |
| `npm view simple-icons version` | 16.31.0 (exists if we prefer the package over HTTP) |

**Conclusion: no scraping tool is needed, and none should be added.** Use Node + `fetch`
(a ~150-line script), not a framework. A browser-driving scraper (Playwright) would be
strictly worse here: slow, flaky, and it can only read what the site hydrates, whereas the
raw data is a static JSON we can diff in CI.

---

## Why not the `simple-icons` npm package

`simple-icons` (16.31.0) would work, but:
- It ships ~3400 ES modules and generated `.d.ts`; tree-shaking a subset is fine, but the
  package is a dev dependency that then must track upstream versions.
- The **raw `path` data** is the only thing we need, and it is available over plain HTTP
  without touching `node_modules`.
- A **checked-in generated module** means the icons cannot silently change under us on an
  unrelated `npm i`, and a reviewer can see the exact paths in a diff.

Recommendation: **HTTP scrape + committed generated module.** Optionally keep the
`simple-icons` package *out* of `dependencies` entirely.

---

## Architecture: how the icon gets on screen

### Chosen approach — bundler-inlined SVG path data
1. Build-time script writes `agent-ui/src/assets/fileIcons.generated.tsx` containing:
   - `FILE_ICON_PATHS: Record<string, { title: string; hex: string; path: string }>` keyed
     by **extension** (e.g. `ts`, `py`, `rs`) plus a few **filename** keys
     (e.g. `dockerfile`, `package.json`).
   - Nothing else. No JSX, no React import. Just data.
2. Runtime component resolves `path` → key → entry, and renders:
   ```tsx
   <svg viewBox="0 0 24 24" width={14} height={14} role="img" aria-label={title}>
     <path d={entry.path} fill={resolvedColor} />
   </svg>
   ```
3. Color: `fill` is decided by **brand color strategy** (see next section), never
   hardcoded to the Simple Icons hex if that hex is unreadable on our background.

Why this shape:
- **Path data inlines into the agent-embed bundle.** The embed build
  (`agent-ui/vite.config.agent-embed.ts`) currently has *no* `assetsInlineLimit` override,
  and existing logo SVGs (`src/assets/model/*.svg`) are imported as URL strings. Shipping
  ~90 icon *files* would therefore mean ~90 extra emitted assets that the embed must serve;
  path data in one `.tsx` module is a single extra chunk with zero fetch. Given the model
  logos already suffer a **dark-mode problem** (see `DARK_FILL_MODELS` /
  `needsInvertModelImage` in `src/shared/modelProviderImages.ts`), inlining also lets us
  recolor per-brand instead of `filter: invert(1)` hackery.
- **No `vite-plugin-svgr` needed.** The repo has no `?react` SVG import support today
  (verified: nothing matching `svgr|svg-loader|reactComponent|\?react` in any vite config).
  Adding a plugin for ~90 static icons is unnecessary surface area.
- **Zero runtime network.** Offline/desktop builds keep working; no CSP/CORS concerns.

### Fallbacks (must be part of the plan, not an afterthought)
- Extension not in `FILE_ICON_PATHS`: keep the current outlined **text chip** as the
  fallback renderer (`badgeFor` stays as the fallback path). This guarantees no file ever
  renders blank.
- Image files (`IMAGE_EXTS`): keep the existing generic `ImageIcon`.
- Readability: if a brand hex has too little contrast against the surface, use a
  near-black/near-white variant (see strategy below) or the chip, whichever reads better.

### Color strategy (this is the part that bit us with model logos)
Three tiers, declared per-key in the generated module:
1. **Brand-contrast-safe** (default): use the Simple Icons `hex`; it is a *brand token*
   chosen by us, so it must be legible on both themes. Compute a luminance once in the
   script and store `hexLight` / `hexDark` when the brand color needs one.
2. **Monochrome/inverted logos** (e.g. anything whose brand treatment is a solid dark
   mark, like `openai`/`anthropic` in the model picker): store `mono: true` and render
   `currentColor`, inheriting the `text-ds-icon-neutral-*` token, exactly like the
   `CATEGORY_ICON` lucide icons already do on this row.
3. **Theme-flexible**: a small explicit allowlist (like the existing
   `DARK_FILL_MODELS` set) for brands that must flip between themes, with a committed
   `hexDark`. Do **not** reach for `filter: invert(1)` again — that is the bug the user
   already flagged.

The generated module should carry a `mono?: boolean` and partial
`hexLight?: string; hexDark?: string` so the strategy is data, not code branches.

---

## Step-by-step

### S1 — Curate the extension list (do first; it defines everything else)
Extend the current 36 keys into a single source of truth **in the script**, not the
component. Proposed tiers:

- **Tier A (current 36, feature parity):** `ts tsx js jsx mjs cjs py json md mdx txt rst
  css scss less html vue svelte go rs java kt rb php c cpp cc h sh bash zsh sql yml yaml
  toml xml` plus the 4 filename specials (`package.json`, `readme*`, `dockerfile`, `.env`).
- **Tier B (high-value dev additions):** `dart swift lua r perl scala elixir ex erl hs
  clj cljs ml mli fs fsx vb cs pl pm groovy gradle m mm sol asm s v zig nim cr exs exs
  graphql gql prisma proto tf tfvars hcl nix dockerfile makefile cmake ini cfg conf env
  log csv tsv parquet ipynb rmd tex bib diff patch lock`.
- **Tier C (aliases/collapse):** `cc→cpp`, `cxx→cpp`, `hpp→cpp`, `hh→cpp`, `mjs/cjs→js`,
  `htm→html`, `yaml→yml` (share one path), `bash/zsh→sh`.

Each tier entry is `extension → { slug: 'typescript' | null, mono?: true, ... }`.
An entry with `slug: null` explicitly means "use the chip", so the mapping is reviewable.

### S2 — Resolve title → slug
Fetch `slugs.md`, parse the `| \`Name\` | \`slug\` |` table into a `Map<title, slug>`
(3453 brand rows; verified via probe). Keep an explicit title override table for the
awkward ones found in the probe: `C → c`, `C++ → cplusplus`, `GNU Bash → gnubash`,
`Vue.js → vuedotjs`, `Node.js → nodedotjs`, `Sass → sass`, `HTML5 → html5`.
**Java has no slug under any casing we found — verify and, if genuinely absent, let
Java fall back to the chip or hand-author its path.** Treat resolution as
`slug = overrides.get(key) ?? map.get(title) ?? null` and **fail the build** if a Tier A
key resolves to null without an explicit `slug: null`.

### S3 — Fetch metadata + SVGs
Two calls, both verified working:
- `data/simple-icons.json` → `{ title, hex, source, license? }` per icon. Use `hex` for
  the brand color and `source`/`license` for the attribution file (`license` is present
  on only 223/3460 icons, so absence is normal and is not a "no license" signal).
- `cdn.simpleicons.org/<slug>` → the raw `<svg>` (confirmed 200, `image/svg+xml`).
  Extract the `d` attribute and `viewBox` from the response rather than trusting a
  regex on the HTML site.
- Fetch with a tiny concurrency limit (e.g. 6 at a time) and a retry-once on non-200.
  Cache responses under a gitignored `.cache/file-icons/` so re-runs are offline and
  deterministic.

### S4 — Generate the module
Write `agent-ui/src/assets/fileIcons.generated.tsx` (data-only, header comment saying
"GENERATED — do not edit; run `npm run icons:file-extensions`"). Include:
```ts
export interface FileIconEntry {
  title: string; hex: string;
  hexLight?: string; hexDark?: string; mono?: boolean;
  path: string; viewBox?: string;
}
export const FILE_ICON_PATHS: Record<string, FileIconEntry> = { /* … */ };
export const FILE_ICON_META = { generatedFrom: '<commit sha>', simpleIconsVersion: '<x.y.z>' };
```
Record the upstream commit SHA / package version so drift is visible in review.
Also emit `agent-ui/src/assets/fileIcons.LICENSE.md` with `title → slug → source URL`
for every icon actually bundled (attribution hygiene; the repo has no NOTICE file today).

### S5 — Rewire the component (additive, reversible)
In `ActivityTraceCard.tsx`:
- Delete `FILE_BADGE` **only after** the new renderer is proven; first land it as
  `FILE_BADGE_LEGACY` behind the same fallback branch.
- `badgeFor(path)` stays and becomes the fallback resolver.
- `FileTypeIcon` becomes: resolve icon entry → if hit, render `<svg>` with the color
  strategy; else render the existing chip exactly as today.
- Keep `size={14}`, `aria-hidden`, `shrink-0`, and the `IMAGE_EXTS` branch untouched.
- Add `title`/`aria-label` (the brand name) so screen readers and hover get more than
  the 2-char chip gave.

### S6 — Wire the build script
- New script at **`scripts/fetch-file-icons.mjs`** (the repo already uses
  `scripts/*.mjs`/`.js` at root, and `agent-ui/package.json` has no `scripts/` dir of its
  own — verified).
- Add `agent-ui/package.json` scripts: `"icons:file-extensions": "node ../scripts/fetch-file-icons.mjs"`.
- Script must be **idempotent and offline-friendly**: if `.cache/` is warm and
  `--offline` is passed, regenerate without network. CI uses `--check` mode (exit 1 if
  the committed module is stale).

### S7 — Tests & validation
- Unit (`vitest`, already configured): assert `FileTypeIcon` renders an `<svg>` for
  `foo.ts`, falls back to the chip for an unknown extension, keeps `ImageIcon` for
  `a.png`, and that `package.json`/`Dockerfile`/`README.md`/`.env` resolve to their
  special entries.
- Snapshot-lite: assert the resolved **fill color** for 3 contrasting brands on light
  and dark (`ts`, `md`, one `mono: true` entry).
- **Typecheck gate:** `npm --prefix agent-ui run type-check`.
- **Regression gate:** the existing design-token check (`check:design-token-usage`) must
  still pass, since we are swapping a hardcoded-`style` chip for `currentColor` SVG.
- Manual: run the app, open a task that touches many languages, confirm the trace renders
  correctly in **both** light and dark, and specifically re-check the Anthropic-style
  dark-logo case the user hit before.

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Simple Icons **license/attribution** — the `simple-icons` project is CC0-1.0 for its *data*, but each bundled brand mark carries its own source/license | Medium | **DONE.** `fileIcons.LICENSE.md` is generated and committed (force-un-ignored past the blanket `*.md` rule). It states plainly that every mark belongs to its owner, that we claim no ownership and grant no licence, and it lists the source URL per icon. |
| **Brand logos imply endorsement** (e.g. a company mark in a product UI) | Medium | Reviewer decision; Tier A only covers language/tooling marks (TS, Python…), which is lower risk than company logos. |
| Dark-mode legibility (the bug already reported for model logos) | High | **DONE for the icon set:** data-driven `mono` (28/75) renders `currentColor`, and there is no `filter: invert` anywhere in `ActivityTraceCard`. **DONE for the model picker:** the invert rule now lives in one `modelImageStyle()` helper that all five call sites use. Remaining: the explicit dark-mode screenshot test (S7). |
| Bundle growth | Low | Path data only, ~90 icons; a few KB gzipped. Verify by diffing `dist-agent-embed/agent-embed.umd.js` size before/after. |
| Upstream drift (icon renamed/removed) | Medium | Pin by commit SHA in `FILE_ICON_META`; CI `--check` job fails loudly on a re-run that differs. |
| Always-on feature flag → no dark launch | Medium | Land S5 as a small, isolated diff; screenshot both themes in the PR. |
| Embed asset pipeline (extra emitted assets) | Low | Avoided entirely by inlining path data (see architecture rationale). |

---

## Sequencing & ownership

| Step | Effort | Depends on | Owner |
|---|---|---|---|
| S1 curate Tier A/B/C list | S | — | Eigent + Octagon sign-off |
| S2 slug resolution + overrides | S | S1 | Eigent |
| S3 fetch/cache script (`scripts/fetch-file-icons.mjs`) | M | S1 | Eigent |
| S4 generate `fileIcons.generated.tsx` + LICENSE.md | M | S2, S3 | Eigent |
| S5 rewire `FileTypeIcon` (fallback preserved) | M | S4 | Eigent |
| S6 npm script + CI `--check` | S | S3 | Eigent |
| S7 tests (vitest + typecheck + token check + dark-mode manual) | M | S5 | Eigent + Octagon review |

**Suggested cut:** land **S1-S5 as one PR** with the chip fallback intact, then add S6/S7
as a fast follow. Do not start S5 before the S1 list is signed off, because the list is
what the generator is keyed on.

---

## Fallback list — extensions with NO Simple Icons mark (follow-up work)

These six keep the legacy text chip. They are exactly what
`FILE_ICON_FALLBACK_EXTENSIONS` exports, and the generator will never produce an icon for
them until an upstream mark exists or we hand-author one.

| Extension | Why there is no logo | Suggested follow-up |
|---|---|---|
| `txt` | Plain text is a format, not a brand. Upstream has no `textfiles`/`text` icon (CDN 404). | Hand-author a neutral document glyph, or keep the chip permanently (low value). |
| `rst` | reStructuredText has no mark. Upstream `readthedocs` exists but is a *product* logo, which would be misleading for a language. | Decide: accept the Read the Docs mark, or hand-author. |
| `java` | **Genuinely absent from Simple Icons** under every casing (`java`, `openjdk`, `oracle`). This is the most notable gap given how common the file type is. | Highest-value hand-author: a Duke-less neutral Java glyph, or vendor a permissively licensed mark. |
| `m` | Objective-C has no mark; the only near-neighbour is `apple`, which is a different thing entirely. | Decide: `apple` (clear but imprecise) vs. hand-author vs. chip. |
| `mm` | Same as `m` (Objective-C++). | Same decision as `m`. |
| `proto` | Protocol Buffers has no slug (upstream is `protocolbuffers` in the docs but the CDN 404s; no dataset row). | Hand-author, or keep the chip. |

Not-icon-set by design (these are *formats*, not languages, and borrowing a vendor logo for
them would be misleading) — they also keep the chip, and the chip label was widened to the
real format name instead of a 4-char truncation:

`json` / `toml` / `yml` / `yaml` / `xml` / `ini` / `cfg` / `conf` / `env` / `log` / `csv` /
`tsv` / `diff` / `patch` / `lock` / `asm` / `s` / `bib` / `rmd`

> Note: `json`, `toml`, `xml`, `yaml` currently DO get a Simple Icons mark because upstream
> ships one. The list above is the "if we later decide formats should be uniform" set.

---

## License posture (decided 2026-09-13)

- **We do not own the logos.** Every mark, name and trademark in
  `fileIcons.generated.ts` belongs to its respective owner. All rights are reserved by the
  owners. We claim no ownership and grant no licence or sublicence to the marks by including
  them. This is stated verbatim in `fileIcons.LICENSE.md`.
- The notice is shipped as a **committed, reviewable file** next to the generated module
  rather than a `THIRD-PARTY-NOTICES` file, which this repo does not have. If legal review
  wants it centralised later, `fileIcons.LICENSE.md` is the single source to fold in.
- `.gitignore` has a blanket `*.md` rule, so the notice is force-un-ignored
  (`!agent-ui/src/assets/fileIcons.LICENSE.md`) — without that negation the attribution file
  would silently never be committed, which is the worst possible failure mode here.
- Simple Icons' own guidance says the marks should not imply endorsement. We only use them to
  identify a file's language, which is the "informational reference" case.

---

## Open questions for review

1. ~~**License posture**~~ **RESOLVED:** acceptable to bundle, with the owner-reserved
   attribution notice in `fileIcons.LICENSE.md` (see "License posture" above). No
   `THIRD-PARTY-NOTICES` file; fold this one in later if legal asks.
2. ~~**Coverage depth**~~ **RESOLVED:** Tier A + a trimmed Tier B — 75 icons shipped,
   keyed on the extensions that actually appear in developer traces.
3. ~~**Chosen source**~~ **RESOLVED:** HTTP fetch of the raw JSON/CDN + a committed generated
   module. The `simple-icons` npm package is deliberately NOT a dependency.
4. ~~**Color**~~ **RESOLVED:** brand hex by default; `currentColor` for the 28 `mono`
   entries (luminance `< 0.12`), driven by generated data rather than per-icon code.
5. **Attribution in the DOM:** currently each rendered icon carries `role="img"` +
   `aria-label={entry.title}` (the brand name), replacing the old 2-char chip label with
   nothing at all. **Still open:** whether to keep the brand name as a visible `title`
   tooltip, or leave the trace visually bare and keep it accessibility-only. Currently
   accessibility-only — say the word if you want the tooltip.
6. **New:** do you want `java` (the one high-traffic extension with no upstream mark)
   hand-authored now, or left on the chip until the follow-up? See the fallback table.
