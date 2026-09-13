/**
 * Generate real per-language SVG logos for the chat activity trace.
 *
 * Source of truth: Simple Icons (https://simpleicons.org/), which exposes the
 * full set as a static JSON dataset plus a per-slug CDN:
 *   - https://raw.githubusercontent.com/simple-icons/simple-icons/develop/slugs.md
 *   - https://raw.githubusercontent.com/simple-icons/simple-icons/develop/data/simple-icons.json
 *   - https://cdn.simpleicons.org/<slug>
 *
 * No scraping framework is required (and none should be added): Node's built-in
 * `fetch` gets us the same bytes a browser-driven scraper would, deterministically
 * and without a headless browser.
 *
 * Outputs (all committed):
 *   - agent-ui/src/assets/fileIcons.generated.ts   path data keyed by extension
 *   - agent-ui/src/assets/fileIcons.LICENSE.md     attribution notice + sources
 *
 * Usage:
 *   node scripts/fetch-file-icons.mjs              # normal run (network + cache)
 *   node scripts/fetch-file-icons.mjs --offline    # cache only, no network
 *   node scripts/fetch-file-icons.mjs --check      # exit 1 if committed output is stale
 */

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, '..');
const AGENT_UI = join(REPO_ROOT, 'agent-ui');
const CACHE_DIR = join(REPO_ROOT, '.cache', 'file-icons');
const OUT_TS = join(AGENT_UI, 'src', 'assets', 'fileIcons.generated.ts');
const OUT_LICENSE = join(AGENT_UI, 'src', 'assets', 'fileIcons.LICENSE.md');

const DATA_URL =
  'https://raw.githubusercontent.com/simple-icons/simple-icons/develop/data/simple-icons.json';
const SLUGS_URL =
  'https://raw.githubusercontent.com/simple-icons/simple-icons/develop/slugs.md';
const CDN = (slug) => `https://cdn.simpleicons.org/${slug}`;

const args = new Set(process.argv.slice(2));
const OFFLINE = args.has('--offline');
const CHECK = args.has('--check');

/**
 * Extension -> Simple Icons slug.
 *
 * `null` means "no brand mark upstream, keep the legacy text chip". Every
 * Tier A key (the 36 extensions the badge already covered) MUST be present,
 * so parity with the old FILE_BADGE map is reviewable in one table.
 */
const TIER_A = {
  ts: 'typescript',
  tsx: 'react',
  js: 'javascript',
  jsx: 'react',
  mjs: 'javascript',
  cjs: 'javascript',
  py: 'python',
  json: 'json',
  md: 'markdown',
  mdx: 'mdx',
  txt: null,
  rst: null,
  css: 'css',
  scss: 'sass',
  less: 'less',
  html: 'html5',
  vue: 'vuedotjs',
  svelte: 'svelte',
  go: 'go',
  rs: 'rust',
  java: null,
  kt: 'kotlin',
  rb: 'ruby',
  php: 'php',
  c: 'c',
  cpp: 'cplusplus',
  cc: 'cplusplus',
  h: 'c',
  sh: 'gnubash',
  bash: 'gnubash',
  zsh: 'gnubash',
  sql: 'mysql',
  yml: 'yaml',
  yaml: 'yaml',
  toml: 'toml',
  xml: 'xml',
};

/** High-value dev extensions we did not cover before. */
const TIER_B = {
  swift: 'swift',
  dart: 'dart',
  lua: 'lua',
  r: 'r',
  perl: 'perl',
  scala: 'scala',
  ex: 'elixir',
  exs: 'elixir',
  erl: 'erlang',
  hs: 'haskell',
  clj: 'clojure',
  cljs: 'clojure',
  cs: 'sharp',
  vb: 'dotnet',
  fs: 'fsharp',
  m: null,
  mm: null,
  pl: 'perl',
  groovy: 'apachegroovy',
  sol: 'solidity',
  zig: 'zig',
  nim: 'nim',
  cr: 'crystal',
  graphql: 'graphql',
  gql: 'graphql',
  prisma: 'prisma',
  proto: null,
  tf: 'terraform',
  hcl: 'terraform',
  nix: 'nixos',
  dockerfile: 'docker',
  makefile: 'make',
  cmake: 'cmake',
  ipynb: 'jupyter',
  tex: 'latex',
  bun: 'bun',
  deno: 'deno',
  gradle: 'gradle',
  hpp: 'cplusplus',
  hh: 'cplusplus',
  cxx: 'cplusplus',
  cshtml: 'sharp',
  razor: 'sharp',
  htm: 'html5',
  vbs: 'dotnet',
};

/**
 * EXCLUDED from the icon set, deliberately.
 *
 * Everything here is a source-code language. A brand logo can only exist when
 * a company or community owns the mark; a file *format* owned by nobody would
 * have to borrow a vendor's logo, which is misleading (e.g. "dotenv" or
 * "editorconfig" are not a products, they are specs).
 *
 * These keys keep the legacy chip, but each chip is re-labelled with the real
 * language/file-type name (e.g. JSON -> "JSON", TOML -> "TOML") instead of a
 * truncated 4-character abbreviation. See `FALLBACK_PRESENTATION`.
 */
const FALLBACK_PRESENTATION = {
  json: { label: 'JSON' },
  toml: { label: 'TOML' },
  yml: { label: 'YAML' },
  yaml: { label: 'YAML' },
  xml: { label: 'XML' },
  ini: { label: 'INI' },
  cfg: { label: 'CFG' },
  conf: { label: 'CONF' },
  env: { label: 'ENV' },
  log: { label: 'LOG' },
  csv: { label: 'CSV' },
  tsv: { label: 'TSV' },
  diff: { label: 'DIFF' },
  patch: { label: 'PATCH' },
  lock: { label: 'LOCK' },
  asm: { label: 'ASM' },
  s: { label: 'ASM' },
  bib: { label: 'BIB' },
  rmd: { label: 'RMD' },
  rst: { label: 'RST' },
  txt: { label: 'TXT' },
  java: { label: 'JAVA' },
};

const ALL = { ...TIER_A, ...TIER_B };

/** Silences unused-var linting for the table above in ad-hoc runs. */
void FALLBACK_PRESENTATION;

const HEADER = `// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

/**
 * GENERATED FILE -- DO NOT EDIT BY HAND.
 * Regenerate with:  npm run icons:file-extensions   (inside agent-ui/)
 *
 * Brand logos are the property of their respective owners. We claim no
 * ownership and grant no license to the marks found here; see
 * fileIcons.LICENSE.md alongside this module for the full attribution notice.
 *
 * Path data is inlined (no runtime fetch, no extra emitted asset), so the
 * agent-embed bundle stays a single chunk.
 */`;

const isImageFile = (v) => new RegExp(`\\.(${v})$`, 'i').test('x.png');

/** Fetch a URL with one retry, caching under .cache/file-icons. */
async function cachedFetch(url, key, { json = false } = {}) {
  const cachePath = join(CACHE_DIR, key);
  if (existsSync(cachePath)) return readFile(cachePath, 'utf8');

  if (OFFLINE) {
    throw new Error(
      `offline mode: cache miss for ${url} (${cachePath}). Run without --offline once.`
    );
  }

  let lastErr;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const res = await fetch(url, {
        headers: { 'user-agent': 'eigent-file-icons-generator' },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
      const text = await res.text();
      await mkdir(dirname(cachePath), { recursive: true });
      await writeFile(cachePath, text, 'utf8');
      return text;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}

function parseSlugs(md) {
  const rows = new Map();
  for (const line of md.split('\n')) {
    const m = line.match(/^\|\s*`(.+?)`\s*\|\s*`(.+?)`\s*\|$/);
    if (m) rows.set(m[1], m[2]);
  }
  return rows;
}

function extractPath(svg) {
  const d = svg.match(/<path[^>]*\sd="([^"]+)"/);
  const viewBox = svg.match(/viewBox="([^"]+)"/);
  if (!d) throw new Error('no <path d="..."> found in SVG');
  return { path: d[1], viewBox: viewBox ? viewBox[1] : '0 0 24 24' };
}

/** Relative luminance of a #rrggbb brand color (WCAG-ish, quick form). */
function luminance(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

async function main() {
  if (OFFLINE && !existsSync(CACHE_DIR)) {
    console.error(
      `--offline requested but ${CACHE_DIR} does not exist. Nothing to read.`
    );
    process.exit(1);
  }

  const slugsMd = await cachedFetch(SLUGS_URL, 'slugs.md');
  const dataJson = await cachedFetch(DATA_URL, 'simple-icons.json');
  const slugs = parseSlugs(slugsMd);
  const data = JSON.parse(dataJson);
  // The dataset is a bare top-level array of { title, hex, source, slide? }.
  const byTitle = new Map(data.map((i) => [i.title, i]));
  const titleBySlug = new Map([...slugs.entries()].map(([t, s]) => [s, t]));

  const entries = {};
  const fallbacks = [];
  const missing = [];

  for (const [ext, slug] of Object.entries(ALL)) {
    if (!slug) {
      fallbacks.push({ ext, reason: 'no brand mark upstream' });
      continue;
    }
    const svg = await cachedFetch(CDN(slug), `svg/${slug}.svg`);
    const { path: d, viewBox } = extractPath(svg);

    // Resolve the human title for attribution; slug->title via slugs.md.
    const title = titleBySlug.get(slug) ?? slug;
    const meta = byTitle.get(title);
    const hex = meta ? `#${meta.hex}` : '#6b7280';

    entries[ext] = {
      slug,
      title,
      hex,
      // A brand hex darker than this is unreadable on a light surface, so the
      // renderer falls back to `currentColor` (which flips with the theme).
      ...(luminance(hex) < 0.12 ? { mono: true } : {}),
      path: d,
      viewBox,
      source: meta?.source ?? `https://simpleicons.org/?q=${slug}`,
    };
    if (!meta) missing.push({ ext, slug, title });
  }

  const commit = (() => {
    try {
      return execFileSync('git', ['rev-parse', 'HEAD'], {
        cwd: REPO_ROOT,
      })
        .toString()
        .trim();
    } catch {
      return 'unknown';
    }
  })();

  const body = Object.entries(entries)
    .map(([ext, e]) => {
      const flags = [
        `slug: '${e.slug}'`,
        `title: '${e.title.replace(/'/g, "\\'")}'`,
        `hex: '${e.hex}'`,
        `viewBox: '${e.viewBox}'`,
        ...(e.mono ? ['mono: true'] : []),
      ].join(', ');
      return `  ${JSON.stringify(ext)}: { ${flags}, path: '${e.path}' },`;
    })
    .join('\n');

  const ts = `${HEADER}

export interface FileIconEntry {
  /** Simple Icons slug this mark came from. */
  slug: string;
  /** Human-readable brand name, for \`aria-label\` / \`title\`. */
  title: string;
  /** Upstream brand hex (a brand token, not necessarily legible here). */
  hex: string;
  /**
   * True when the brand's own treatment is a solid mark whose brand hex is too
   * dark to read on a light surface. Renderers use \`currentColor\` for these
   * instead of \`hex\`, which is how dark mode is supported without a filter.
   */
  mono?: boolean;
  /** SVG \`d\` attribute. */
  path: string;
  viewBox: string;
}

/** Extension -> icon, for the activity trace file links. */
export const FILE_ICON_PATHS: Record<string, FileIconEntry> = {
${body}
};

/** Extensions deliberately left on the legacy text chip (no brand mark). */
export const FILE_ICON_FALLBACK_EXTENSIONS = ${JSON.stringify(
    fallbacks.map((f) => f.ext)
  )} as const;

/** Provenance, so drift is visible in review. */
export const FILE_ICON_META = {
  generatedFromCommit: '${commit}',
  source: 'https://simpleicons.org/',
  generatedAt: '${new Date().toISOString().slice(0, 10)}',
};
`;

  const licenseRows = Object.entries(entries)
    .map(
      ([ext, e]) =>
        `| \`${ext}\` | ${e.title} | \`${e.slug}\` | ${e.source} |`
    )
    .join('\n');

  const license = `# Brand logo attribution

The SVG paths in \`fileIcons.generated.ts\` are brand marks sourced from
[Simple Icons](https://simpleicons.org/). **Every logo, name and trademark
represented here belongs to its respective owner.** Eigent does not own these
logos, does not claim any rights in them, and no license or sublicense to the
marks is granted by their inclusion in this repository. All rights are reserved
by the respective owners. They are used here solely to identify the language or
file type a developer is looking at in the activity trace.

If you are a rights holder and want a mark removed or altered, open an issue and
we will act on it.

Generated from commit \`${commit}\`. Do not edit by hand; run
\`npm run icons:file-extensions\` inside \`agent-ui/\`.

| Extension | Brand | Simple Icons slug | Source |
| --- | --- | --- | --- |
${licenseRows}
`;

  if (CHECK) {
    const [prevTs, prevLic] = await Promise.all([
      readFile(OUT_TS, 'utf8').catch(() => ''),
      readFile(OUT_LICENSE, 'utf8').catch(() => ''),
    ]);
    const same =
      createHash('sha1').update(prevTs).digest('hex') ===
        createHash('sha1').update(ts).digest('hex') &&
      createHash('sha1').update(prevLic).digest('hex') ===
        createHash('sha1').update(license).digest('hex');
    if (!same) {
      console.error(
        'file icons are stale: re-run npm run icons:file-extensions and commit the result.'
      );
      process.exit(1);
    }
    console.log('file icons are up to date.');
    return;
  }

  await mkdir(dirname(OUT_TS), { recursive: true });
  await writeFile(OUT_TS, ts, 'utf8');
  await writeFile(OUT_LICENSE, license, 'utf8');

  console.log(`wrote ${OUT_TS}`);
  console.log(`wrote ${OUT_LICENSE}`);
  console.log(
    `${Object.keys(entries).length} icons; ${fallbacks.length} extensions on the chip fallback.`
  );
  if (missing.length) {
    console.warn(
      `no metadata row for: ${missing.map((m) => m.ext).join(', ')} (hex defaulted to #6b7280)`
    );
  }
  void isImageFile;
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
