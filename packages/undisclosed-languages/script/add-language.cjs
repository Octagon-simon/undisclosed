#!/usr/bin/env node
/**
 * Add a language to `undisclosed-languages` without hand-editing two files.
 *
 * It appends to:
 *   - the LANGUAGES list in `generate.js`   (only for NEW vendored tokenizers)
 *   - the LANGUAGE_DESCRIPTORS table in `src/languages.ts` (always)
 * using the `// <ADD-LANGUAGE:...>` anchors in those files.
 *
 * Two modes
 * ---------
 * 1. New vendored language — the id is a folder under monaco-editor's
 *    `basic-languages` (its Monarch tokenizer gets vendored):
 *
 *      node script/add-language.js kotlin --ext .kt,.kts --alias "Kotlin,kt"
 *
 * 2. Reuse an existing tokenizer — give a distinct id but point it at a module
 *    that's already vendored (nothing new is vendored). This is how TSX reuses
 *    the TypeScript tokenizer:
 *
 *      node script/add-language.js typescriptreact \
 *        --module typescript --ext .tsx --alias "TypeScript React,tsx"
 *
 * Options
 *   --ext <.a,.b>       file extensions (required)
 *   --alias <A,b>       aliases (default: capitalized id)
 *   --module <name>     vendored module to use (default: <id>). Differ from id
 *                       to REUSE an existing tokenizer instead of vendoring one.
 *   --mimetypes <a,b>   optional mimetypes
 *   --first-line <re>   optional firstLine detection regex
 *   --generate          run `npm run generate:languages` after editing
 *
 * After running: `npm run generate:languages` (if a new module was added) then
 * `npm run build`, and rebuild Theia to load the extension.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const PKG_ROOT = path.join(__dirname, '..');
const REPO_ROOT = path.join(PKG_ROOT, '..', '..');
const GENERATE_JS = path.join(__dirname, 'generate.js');
const LANGUAGES_TS = path.join(PKG_ROOT, 'src', 'languages.ts');

const VENDORED_ANCHOR = '// <ADD-LANGUAGE:vendored>';
const DESCRIPTOR_ANCHOR = '// <ADD-LANGUAGE:descriptors>';

function die(msg) {
  console.error(`error: ${msg}`);
  process.exit(1);
}

// --- arg parsing -----------------------------------------------------------
function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) {
        out[key] = true; // boolean flag
      } else {
        out[key] = next;
        i++;
      }
    } else {
      out._.push(a);
    }
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const id = args._[0];
if (!id) die('missing <id>. Usage: node script/add-language.js <id> --ext .foo');
if (!/^[a-z][a-z0-9]*$/i.test(id)) {
  die(`id "${id}" must be a single alphanumeric token (no spaces/dashes)`);
}
if (!args.ext) die('missing --ext (e.g. --ext .tsx or --ext .kt,.kts)');

const vendorModule = args.module || id;
const isReuse = vendorModule !== id;

const extensions = String(args.ext)
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean)
  .map((s) => (s.startsWith('.') ? s : `.${s}`));

const aliases = args.alias
  ? String(args.alias).split(',').map((s) => s.trim()).filter(Boolean)
  : [id.charAt(0).toUpperCase() + id.slice(1)];

const mimetypes = args.mimetypes
  ? String(args.mimetypes).split(',').map((s) => s.trim()).filter(Boolean)
  : undefined;
const firstLine = args['first-line'] || undefined;

// --- validation ------------------------------------------------------------
function monacoHasModule(name) {
  for (const root of [
    path.join(REPO_ROOT, 'node_modules', 'monaco-editor'),
    path.join(REPO_ROOT, 'agent-ui', 'node_modules', 'monaco-editor'),
  ]) {
    if (fs.existsSync(path.join(root, 'esm', 'vs', 'basic-languages', name, `${name}.js`))) {
      return true;
    }
  }
  return false;
}

if (!isReuse && !monacoHasModule(vendorModule)) {
  die(
    `"${vendorModule}" is not a monaco basic-languages tokenizer. Either fix the id, ` +
      `or reuse an existing one with --module <vendoredName>.`
  );
}

// --- edit generate.js (only when vendoring a brand-new module) -------------
function insertBefore(file, anchor, line) {
  const text = fs.readFileSync(file, 'utf8');
  if (!text.includes(anchor)) die(`anchor "${anchor}" not found in ${file}`);
  const updated = text.replace(anchor, `${line}\n  ${anchor}`);
  fs.writeFileSync(file, updated);
}

if (!isReuse) {
  const gen = fs.readFileSync(GENERATE_JS, 'utf8');
  if (new RegExp(`['"]${vendorModule}['"]`).test(gen.split(VENDORED_ANCHOR)[0])) {
    console.log(`• "${vendorModule}" already in generate.js LANGUAGES — skipping`);
  } else {
    insertBefore(GENERATE_JS, VENDORED_ANCHOR, `'${vendorModule}',`);
    console.log(`✓ added "${vendorModule}" to generate.js LANGUAGES`);
  }
} else {
  console.log(`• reuse mode: tokenizer "${vendorModule}" is vendored already, not touching generate.js`);
}

// --- edit languages.ts (always) --------------------------------------------
const langTs = fs.readFileSync(LANGUAGES_TS, 'utf8');
if (new RegExp(`id:\\s*'${id}'`).test(langTs)) {
  die(`a descriptor with id '${id}' already exists in languages.ts`);
}

const parts = [`module: '${vendorModule}'`, `id: '${id}'`];
parts.push(`aliases: [${aliases.map((a) => `'${a}'`).join(', ')}]`);
parts.push(`extensions: [${extensions.map((e) => `'${e}'`).join(', ')}]`);
if (mimetypes) parts.push(`mimetypes: [${mimetypes.map((m) => `'${m}'`).join(', ')}]`);
if (firstLine) parts.push(`firstLine: '${firstLine.replace(/'/g, "\\'")}'`);
const descriptorLine = `    { ${parts.join(', ')} },`;

const langAnchorIndent = `    ${DESCRIPTOR_ANCHOR}`;
fs.writeFileSync(
  LANGUAGES_TS,
  langTs.replace(langAnchorIndent, `${descriptorLine}\n${langAnchorIndent}`)
);
console.log(`✓ added descriptor for id "${id}" (${extensions.join(', ')}) to languages.ts`);

// --- optional generate + next steps ---------------------------------------
if (args.generate && !isReuse) {
  console.log('\n running: npm run generate:languages ...');
  execSync('npm run generate:languages', { cwd: PKG_ROOT, stdio: 'inherit' });
}

console.log('\nNext steps:');
if (!isReuse && !args.generate) {
  console.log('  npm run generate:languages   # vendor the new tokenizer');
}
console.log('  npm run build                # compile the extension');
console.log('  # then rebuild Theia so the extension picks up the new language');
