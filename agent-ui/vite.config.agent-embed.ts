// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
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
 * Library build for the embeddable agent UI. See src/agent-embed/mount.tsx.
 *
 * The bundle is mounted into a HOST page (the Theia agent widget) whose own UI
 * we must not disturb. Eigent's stylesheet has aggressive GLOBAL rules
 * (`* { font-family }`, preflight resets on html/body/elements) that would
 * clobber the host. The PostCSS pass below **scopes only bare-element / `*`
 * selectors** under `.eigent-agent-root`, while leaving class/id/attr/`:root`
 * selectors global — so theme variables (`:root`, `.dark`, `[data-theme]`) and
 * utility classes (used by portaled dropdowns/tooltips too) still work, but the
 * global resets can't leak out of the panel.
 */

import react from '@vitejs/plugin-react';
import autoprefixer from 'autoprefixer';
import path from 'node:path';
import postcssImport from 'postcss-import';
import tailwindcss from 'tailwindcss';
import tailwindcssNesting from 'tailwindcss/nesting';
import { defineConfig } from 'vite';

const AGENT_ROOT = '.eigent-agent-root';

function scopeSelector(sel: string): string {
  const s = sel.trim();
  if (!s || s.startsWith(AGENT_ROOT)) return sel;
  const c = s[0];
  // Keep class / id / attribute selectors global (utilities + theme vars +
  // component styles — needed by portaled UI outside the panel root).
  if (c === '.' || c === '#' || c === '[') return s;
  if (c === ':') {
    // Pseudo-ELEMENTS (::before/::after/::selection) can bleed — scope them.
    // Pseudo-classes / :root / :where stay global.
    return s.startsWith('::') ? `${AGENT_ROOT} ${s}` : s;
  }
  if (s === 'html' || s === 'body') return AGENT_ROOT;
  if (s === '*') return `${AGENT_ROOT}, ${AGENT_ROOT} *`;
  // Bare element selectors (h1, p, button, …) → scope under the panel root.
  return `${AGENT_ROOT} ${s}`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const scopeAgentCss: any = () => ({
  postcssPlugin: 'scope-agent-css',
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Rule(rule: any) {
    const p = rule.parent;
    if (p && p.type === 'atrule' && /keyframes|font-face/i.test(p.name)) return;
    rule.selectors = rule.selectors.map(scopeSelector);
  },
});
scopeAgentCss.postcss = true;

export default defineConfig({
  resolve: {
    alias: { '@': path.join(__dirname, 'src') },
  },
  optimizeDeps: {
    exclude: ['@stackframe/react'],
  },
  plugins: [react()],
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  css: {
    postcss: {
      plugins: [
        postcssImport(),
        tailwindcssNesting(),
        tailwindcss(),
        autoprefixer(),
        // Scope global rules last, on the fully-expanded CSS.
        scopeAgentCss(),
      ],
    },
  },
  build: {
    outDir: 'dist-agent-embed',
    emptyOutDir: true,
    cssCodeSplit: false,
    sourcemap: true,
    lib: {
      entry: path.resolve(__dirname, 'src/agent-embed/mount.tsx'),
      name: 'EigentAgentEmbed',
      formats: ['es', 'umd'],
      fileName: (format) => `agent-embed.${format}.js`,
    },
  },
});
