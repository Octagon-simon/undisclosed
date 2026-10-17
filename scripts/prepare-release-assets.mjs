#!/usr/bin/env node
// Flatten per-OS artifact dirs into one set of release assets with unique names.
//
// GitHub keys release assets by basename, and electron-builder names the update
// feeds by target, not by runner: both mac runners emit `latest-mac.yml`, and
// every runner emits `builder-debug.yml`. Uploading two same-named files makes
// GitHub answer PATCH /releases/assets/{id} with 404 while the first copy is
// still being processed ("update-a-release-asset"), which is what made the
// publish job flaky. Here we drop the debug dumps and merge duplicate update
// feeds into a single file instead.
//
// Usage: node scripts/prepare-release-assets.mjs [artifactsDir] [outDir]
import { copyFile, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

const src = path.resolve(process.argv[2] ?? 'artifacts');
const out = path.resolve(process.argv[3] ?? 'release-assets');

// electron-builder diagnostics, not a release asset.
const SKIP = new Set(['builder-debug.yml']);
const FEED = /^latest(-[a-z]+)?\.yml$/;

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(p)));
    else if (entry.isFile()) files.push(p);
  }
  return files.sort();
}

// electron-builder's feed is a flat, machine-generated document:
//   version: x
//   files:
//     - url: ...
//       sha512: ...
//       size: n
//   path: ...
//   sha512: ...
//   releaseDate: ...
function parseFeed(text, file) {
  const lines = text.split(/\r?\n/);
  const start = lines.findIndex((l) => /^files:\s*$/.test(l));
  if (start === -1) throw new Error(`${file}: no "files:" block`);

  const items = [];
  let current = null;
  let i = start + 1;
  for (; i < lines.length; i++) {
    const line = lines[i];
    if (/^ {2}- /.test(line) || /^- /.test(line)) {
      current = [line];
      items.push(current);
    } else if (/^\s+\S/.test(line) && current) {
      current.push(line);
    } else if (line.trim() === '') {
      continue;
    } else {
      break;
    }
  }

  const version = lines.find((l) => /^version:/.test(l))?.slice('version:'.length).trim();
  const topPath = lines.find((l) => /^path:/.test(l))?.slice('path:'.length).trim();
  return { head: lines.slice(0, start), items, tail: lines.slice(i), version, topPath, file };
}

const urlOf = (item) => (item[0].match(/url:\s*(\S+)/)?.[1] ?? item.join('\n'));

function mergeFeeds(docs) {
  const versions = new Set(docs.map((d) => d.version));
  if (versions.size !== 1) {
    throw new Error(
      `update feeds disagree on version: ${docs.map((d) => `${d.file}=${d.version}`).join(', ')}`,
    );
  }

  // Keep the non-arch-suffixed feed first so the top-level `path`/`sha512` stay
  // the default artifact (what electron-builder writes for a dual-arch mac build).
  const base = docs.find((d) => !/arm64/.test(d.topPath ?? '')) ?? docs[0];
  const seen = new Set(base.items.map(urlOf));
  const merged = [...base.items];
  for (const doc of docs) {
    if (doc === base) continue;
    for (const item of doc.items) {
      const url = urlOf(item);
      if (seen.has(url)) continue;
      seen.add(url);
      merged.push(item);
    }
  }

  return [...base.head, 'files:', ...merged.flat(), ...base.tail].join('\n') + '\n';
}

const files = (await walk(src)).filter((f) => !SKIP.has(path.basename(f)));
const groups = new Map();
for (const file of files) {
  const name = path.basename(file);
  groups.set(name, [...(groups.get(name) ?? []), file]);
}

await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });

for (const [name, group] of [...groups].sort(([a], [b]) => a.localeCompare(b))) {
  const dest = path.join(out, name);
  if (group.length === 1) {
    await copyFile(group[0], dest);
    console.log(`  ${name}`);
    continue;
  }
  if (!FEED.test(name)) {
    throw new Error(
      `duplicate asset name "${name}" from ${group.length} platforms:\n` +
        group.map((f) => `  - ${f}`).join('\n'),
    );
  }
  const docs = [];
  for (const file of group) docs.push(parseFeed(await readFile(file, 'utf8'), file));
  await writeFile(dest, mergeFeeds(docs), 'utf8');
  console.log(`  ${name} (merged ${group.length} feeds: ${docs.map((d) => d.topPath).join(', ')})`);
}

console.log(`\n${groups.size} assets ready in ${path.relative(process.cwd(), out)}/`);
