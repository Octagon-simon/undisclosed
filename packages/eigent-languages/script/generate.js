#!/usr/bin/env node
/**
 * Vendors Monaco "basic-languages" Monarch tokenizers for the popular
 * languages we want to support, as self-contained TypeScript modules.
 *
 * It reads the tokenizer modules from the `monaco-editor` npm package (which
 * ships them compiled by esbuild) and rewrites each into a small TS module
 * that depends only on `@theia/monaco-editor-core` (so no second Monaco gets
 * bundled). The result is written under src/generated/*.ts and consumed by the
 * `eigent-languages` Theia extension.
 *
 * Run: node packages/eigent-languages/script/generate.js
 */
'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.join(__dirname, '..', '..', '..');
const MONACO_ROOT = path.join(REPO_ROOT, 'node_modules', 'monaco-editor');
const MONACO_ESM = path.join(MONACO_ROOT, 'esm', 'vs', 'basic-languages');
const OUT_DIR = path.join(__dirname, '..', 'src', 'generated');

// languageId (subfolder) -> generated module name. Keep to the popular set for now.
const LANGUAGES = [
  'javascript',
  'typescript',
  'python',
  'java',
  'cpp',
  'csharp',
  'go',
  'rust',
  'ruby',
  'php',
  'html',
  'css',
  'sql',
  'shell',
];

function readModule(lang) {
  const file = path.join(MONACO_ESM, lang, `${lang}.js`);
  return fs.readFileSync(file, 'utf8');
}

function vendorOne(lang) {
  const src = readModule(lang);

  // 1) Cut everything before the first "// src/basic-languages/<lang>/" marker,
  //    which removes the license header, helper block, and monaco imports.
  const marker = new RegExp(`// src/basic-languages/${lang}/${lang}\\.ts\\s*`);
  const match = src.match(marker);
  if (!match) {
    throw new Error(`Could not find source marker in ${lang}.js`);
  }
  let body = src.slice(match.index + match[0].length);

  // 2) Replace references to the esbuild-shimmed monaco variable with the real
  //    Theia Monaco module. (IndentAction is the only value the tokenizer bodies
  //    actually pull from monaco.)
  body = body
    .replace(/monaco_editor_core_exports\.languages\.IndentAction\.IndentOutdent/g, 'monaco.languages.IndentAction.IndentOutdent')
    .replace(/monaco_editor_core_exports\.languages\.IndentAction\.Indent/g, 'monaco.languages.IndentAction.Indent')
    .replace(/monaco_editor_core_exports\.languages\.IndentAction\.Outdent/g, 'monaco.languages.IndentAction.Outdent')
    .replace(/monaco_editor_core_exports\.languages\.IndentAction/g, 'monaco.languages.IndentAction')
    // Safety net for any other use of the shimmed variable.
    .replace(/monaco_editor_core_exports\./g, 'monaco.');

  // 3) Fix cross-module imports. The javascript tokenizer reuses TypeScript's
  //    `conf`/`language` from "../typescript/typescript.js" (the path inside
  //    monaco-editor's package layout). Our vendored copy lives in the same
  //    folder, so point it at sibling module instead.
  body = body.replace(
    /import \{ conf as tsConf, language as tsLanguage \} from "\.\.\/typescript\/typescript\.js"/g,
    'import { conf as tsConf, language as tsLanguage } from "./typescript"'
  );

  // 4) Annotate the emitted `conf` with Monaco's type so TypeScript does not
  //    over-narrow array literals (e.g. blockComment: string[] vs tuple).
  //    NOTE: the `language`/Monarch tokenizer stays untyped (`any`): monaco's
  //    vendored tokenizers contain single-element rules (e.g. `[/regex/]`)
  //    that Theia's stricter `IMonarchLanguageRule` union rejects.
  body = body.replace(/^var conf = /m, 'var conf: monaco.languages.LanguageConfiguration = ');

  // 5) Assemble the final module.
  const out = `// Generated from monaco-editor (MIT) "basic-languages/${lang}".
// See packages/eigent-languages/script/generate.js. Do not edit directly.
import * as monaco from '@theia/monaco-editor-core';

${body}
`;
  return out.trimEnd() + '\n';
}

fs.mkdirSync(OUT_DIR, { recursive: true });

const indexLines = [];
for (const lang of LANGUAGES) {
  const code = vendorOne(lang);
  const file = path.join(OUT_DIR, `${lang}.ts`);
  fs.writeFileSync(file, code);
  indexLines.push(`export { conf as ${lang}Conf, language as ${lang}Language } from './${lang}';`);
  console.log(`vendored ${lang}: ${code.split('\n').length} lines`);
}

const index = `// Auto-generated language registry. See script/generate.js.
${indexLines.join('\n')}
`;
fs.writeFileSync(path.join(OUT_DIR, 'index.ts'), index);
console.log('wrote index.ts');
