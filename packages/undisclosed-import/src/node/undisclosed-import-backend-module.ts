// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { ContainerModule } from '@theia/core/shared/inversify';
import { BackendApplicationContribution } from '@theia/core/lib/node';
import express from '@theia/core/shared/express';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { VSCODE_IMPORT_ROUTE, VscodeImportData } from '../common/protocol';

// VS Code stores per-user config under a product-named dir. We probe the common
// variants in preference order (stable first).
const VARIANTS = ['Code', 'Code - Insiders', 'VSCodium'];

/** Candidate "User" directories per platform, newest-mtime wins. */
function userDirCandidates(): { variant: string; dir: string }[] {
  const home = os.homedir();
  const out: { variant: string; dir: string }[] = [];
  for (const variant of VARIANTS) {
    let base: string;
    if (process.platform === 'darwin') {
      base = path.join(home, 'Library', 'Application Support', variant, 'User');
    } else if (process.platform === 'win32') {
      base = path.join(
        process.env.APPDATA || path.join(home, 'AppData', 'Roaming'),
        variant,
        'User'
      );
    } else {
      base = path.join(home, '.config', variant, 'User');
    }
    out.push({ variant, dir: base });
  }
  return out;
}

/** Extensions dir per variant (VS Code keeps these in the home dir, not User). */
function extensionsDirFor(variant: string): string {
  const home = os.homedir();
  if (variant === 'Code - Insiders') {
    return path.join(home, '.vscode-insiders', 'extensions');
  }
  if (variant === 'VSCodium') {
    return path.join(home, '.vscode-oss', 'extensions');
  }
  return path.join(home, '.vscode', 'extensions');
}

/** Tolerant JSON(C) parse: strips // and /* *\/ comments and trailing commas. */
function parseJsonc(text: string): Record<string, unknown> {
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    /* fall through to comment-stripped parse */
  }
  try {
    const stripped = text
      // block comments
      .replace(/\/\*[\s\S]*?\*\//g, '')
      // line comments (naive; fine for settings files)
      .replace(/(^|[^:"'])\/\/.*$/gm, '$1')
      // trailing commas
      .replace(/,(\s*[}\]])/g, '$1');
    return JSON.parse(stripped) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function readSettings(userDir: string): Record<string, unknown> {
  const p = path.join(userDir, 'settings.json');
  try {
    return parseJsonc(fs.readFileSync(p, 'utf8'));
  } catch {
    return {};
  }
}

function readExtensions(variant: string): string[] {
  const dir = extensionsDirFor(variant);
  // The authoritative list is extensions/extensions.json (array of
  // { identifier: { id }, ... }). Fall back to directory names if absent.
  try {
    const raw = fs.readFileSync(path.join(dir, 'extensions.json'), 'utf8');
    const arr = JSON.parse(raw) as Array<{ identifier?: { id?: string } }>;
    const ids = arr
      .map((e) => e?.identifier?.id)
      .filter((id): id is string => typeof id === 'string' && id.length > 0);
    if (ids.length) {
      return Array.from(new Set(ids));
    }
  } catch {
    /* fall through to dir listing */
  }
  try {
    return Array.from(
      new Set(
        fs
          .readdirSync(dir)
          .filter((n) => n.includes('.') && !n.startsWith('.'))
          // dir names look like publisher.name-1.2.3 -> strip the version
          .map((n) => n.replace(/-\d+\.\d+\.\d+.*$/, ''))
          .filter((n) => n.includes('.'))
      )
    );
  } catch {
    return [];
  }
}

function detectVscode(): VscodeImportData {
  const candidates = userDirCandidates().filter((c) => {
    try {
      return fs.existsSync(path.join(c.dir, 'settings.json'));
    } catch {
      return false;
    }
  });
  if (candidates.length === 0) {
    return { found: false, settings: {}, extensions: [] };
  }
  // Prefer the most recently used settings.json.
  candidates.sort((a, b) => {
    const at = fs.statSync(path.join(a.dir, 'settings.json')).mtimeMs;
    const bt = fs.statSync(path.join(b.dir, 'settings.json')).mtimeMs;
    return bt - at;
  });
  const chosen = candidates[0];
  return {
    found: true,
    variant: chosen.variant,
    userDir: chosen.dir,
    settings: readSettings(chosen.dir),
    extensions: readExtensions(chosen.variant),
  };
}

/**
 * Backend contribution: exposes GET `/undisclosed-import/vscode`, returning the
 * detected VS Code install's settings + extension ids so the frontend can offer
 * to import them. Read-only; touches nothing.
 */
export default new ContainerModule((bind) => {
  bind(BackendApplicationContribution)
    .toDynamicValue(() => ({
      configure(app: express.Application): void {
        app.get(VSCODE_IMPORT_ROUTE, (_req, res) => {
          try {
            res.json(detectVscode());
          } catch (err) {
            // eslint-disable-next-line no-console
            console.warn('[undisclosed-import] detect failed:', err);
            res.json({ found: false, settings: {}, extensions: [] });
          }
        });
      },
    }))
    .inSingletonScope();
});
