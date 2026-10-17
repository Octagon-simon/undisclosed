// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Render "nothing vs something" diffs as a compact inline view.
//
// Clicking an UNTRACKED file in Source Control opens a diff whose LEFT side is
// an empty blob (there is no committed version to compare against). Monaco's
// diff editor defaults to `renderSideBySide: true`, so that empty left side is
// drawn as a full, blank half of the editor and the file content is pushed into
// the right half — the "huge spacing on the left" you see when opening a new
// file. (Verified in the dev editor: at a 2400px window the diff is
// `.monaco-diff-editor.side-by-side` with the original pane 742px wide and
// `originalModel` value length 0.)
//
// Two options are needed, both verified against the installed
// `@theia/monaco-editor-core` (1.108.201) source:
//
//   1. `renderSideBySide: false` — switch to the inline (unified) layout.
//   2. `compactMode: true` — Monaco's inline layout still reserves a left
//      column for the ORIGINAL side's line numbers
//      (`diffEditorWidget.js` -> `originalWidth = max(5,
//      original.layoutInfoDecorationsLeft)`), and `inlineViewHideOriginalLineNumbers`
//      is bound to `compactMode` (`diffEditorOptions.js`). Without compactMode
//      an empty original still eats ~36px of blank gutter before the content;
//      with it `originalWidth` collapses to 0.
//
// Theia builds the diff options in
// `MonacoEditorProvider.createMonacoDiffEditorOptions(original, modified)`.
// We wrap that method: when the original model is empty we force both options,
// so the diff renders as a single flush column. Real diffs (modified / deleted
// files) keep their side-by-side layout untouched.
//
// Patching the provider prototype mirrors the existing `installStagedOpenOverride`
// pattern in this package. Our frontend bundler (esbuild) does NOT mangle
// property/method names — property mangling is opt-in — so the wrapped method
// name is stable in the packaged build. If upstream ever moves it we no-op
// instead of throwing.

import { MonacoEditorProvider } from '@theia/monaco/lib/browser/monaco-editor-provider';

/** Minimal shape of the diff options object we care about. */
interface DiffOptions {
  renderSideBySide?: boolean;
  compactMode?: boolean;
}

/** Minimal shape of a Monaco editor model (only what we read). */
interface MaybeModel {
  textEditorModel?: { getValueLength?: () => number };
}

let installed = false;

/**
 * Wraps `MonacoEditorProvider.prototype.createMonacoDiffEditorOptions` once so
 * that a diff against an empty original always renders unified.
 */
export function installEmptyDiffInlineOverride(): void {
  if (installed) {
    return;
  }
  const proto = MonacoEditorProvider.prototype as unknown as Record<
    string,
    unknown
  >;
  const base = proto['createMonacoDiffEditorOptions'];
  if (typeof base !== 'function') {
    // Upstream moved the hook; leave the stock (side-by-side) behaviour alone.
    return;
  }
  installed = true;
  const baseFn = base as (
    this: unknown,
    original: unknown,
    modified: unknown
  ) => DiffOptions;

  proto['createMonacoDiffEditorOptions'] = function (
    this: unknown,
    original: unknown,
    modified: unknown
  ): DiffOptions {
    const options = baseFn.call(this, original, modified);
    try {
      const model = (original as MaybeModel | undefined)?.textEditorModel;
      const len =
        model && typeof model.getValueLength === 'function'
          ? model.getValueLength()
          : 'no-model';
      if (len === 0) {
        // Unified layout AND no left column reserved for the empty original.
        options.renderSideBySide = false;
        options.compactMode = true;
      }
    } catch (err) {
      // Cosmetic only: never let this break opening a diff.
      // eslint-disable-next-line no-console
      console.warn('[undisclosed-diff] options wrapper failed', err);
    }
    return options;
  };
}


