// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

/**
 * JSX-aware comment toggle.
 *
 * `Cmd/Ctrl+/` is Monaco's "Toggle Line Comment", and the line-comment token for
 * the `typescriptreact` / `javascriptreact` languages is `//`. Inside JSX markup
 * that is wrong: React only reads `{/* … *\/}` (a JS expression container holding
 * a block comment). VS Code papers over this in its TypeScript extension; plain
 * Monaco (what Theia embeds) does not, so `Cmd+/` emits `//` on a `<div>` and the
 * file stops compiling.
 *
 * We intercept `Cmd/Ctrl+/` for those two languages (a `when` clause scoped to
 * `editorLangId`, which the stock binding does not use) and toggle a `{/* … *\/}`
 * wrapper around the selected line(s) instead. Non-JSX languages are untouched:
 * our binding simply does not match, so Monaco's normal line comment still runs.
 */

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  Command,
  CommandContribution,
  CommandRegistry,
} from '@theia/core/lib/common';
import {
  KeybindingContribution,
  KeybindingRegistry,
} from '@theia/core/lib/browser';
import { EditorManager } from '@theia/editor/lib/browser';
import { MonacoEditor } from '@theia/monaco/lib/browser/monaco-editor';
import * as monaco from '@theia/monaco-editor-core';

export const TOGGLE_JSX_COMMENT_COMMAND: Command = {
  id: 'undisclosed.toggle-jsx-comment',
  label: 'Toggle JSX Comment',
};

/** Languages whose JSX regions need `{/* … *\/}` instead of `//`. */
const JSX_LANGUAGES = new Set(['typescriptreact', 'javascriptreact']);

/**
 * `editorLangId` is a per-editor context key, so this clause is strictly more
 * specific than the stock `editorTextFocus` binding for `Cmd/Ctrl+/` — Theia's
 * keybinding resolver prefers it while a `.tsx`/`.jsx` editor is focused.
 */
const JSX_COMMENT_WHEN =
  'editorTextFocus && (editorLangId == typescriptreact || editorLangId == javascriptreact)';

const OPEN = '{/*';
const CLOSE = '*/}';

@injectable()
export class JsxCommentContribution
  implements CommandContribution, KeybindingContribution
{
  @inject(EditorManager)
  protected readonly editorManager!: EditorManager;

  registerCommands(commands: CommandRegistry): void {
    commands.registerCommand(TOGGLE_JSX_COMMENT_COMMAND, {
      execute: () => this.toggle(),
    });
  }

  registerKeybindings(keybindings: KeybindingRegistry): void {
    keybindings.registerKeybinding({
      command: TOGGLE_JSX_COMMENT_COMMAND.id,
      keybinding: 'ctrlcmd+/',
      when: JSX_COMMENT_WHEN,
    });
  }

  /** Wrap/unwrap the current selection (or line) in a `{/* … *\/}` comment. */
  protected toggle(): void {
    const widget = this.editorManager.currentEditor;
    const control = MonacoEditor.get(widget)?.getControl();
    const model = control?.getModel();
    if (!control || !model) return;
    if (!JSX_LANGUAGES.has(model.getLanguageId())) return;

    const selections = control.getSelections() ?? [];
    if (!selections.length) return;

    const edits: monaco.editor.IIdentifiedSingleEditOperation[] = [];
    const seen = new Set<string>();
    for (const selection of selections) {
      const startLine = selection.startLineNumber;
      const endLine = selection.endLineNumber;
      const range = new monaco.Range(
        startLine,
        1,
        endLine,
        model.getLineMaxColumn(endLine)
      );
      const key = `${startLine}:${endLine}`;
      // Multiple cursors on the same line would produce overlapping edits,
      // which `executeEdits` rejects.
      if (seen.has(key)) continue;
      seen.add(key);

      const text = model.getValueInRange(range);
      const indent = (text.match(/^[ \t]*/) ?? [''])[0];
      const body = text.slice(indent.length).replace(/[ \t]+$/, '');

      if (body.startsWith(OPEN) && body.endsWith(CLOSE)) {
        // Already commented — strip the wrapper (and its padding) back off.
        let inner = body.slice(OPEN.length, body.length - CLOSE.length);
        inner = inner.replace(/^\s*\n/, '').replace(/\n[ \t]*$/, '');
        inner = inner.replace(/^ +/, '').replace(/ +$/, '');
        edits.push({ range, text: indent + inner, forceMoveMarkers: true });
      } else if (body.includes('\n')) {
        edits.push({
          range,
          text: `${indent}${OPEN}\n${text}\n${indent}${CLOSE}`,
          forceMoveMarkers: true,
        });
      } else {
        edits.push({
          range,
          text: `${indent}${OPEN} ${body} ${CLOSE}`,
          forceMoveMarkers: true,
        });
      }
    }

    if (!edits.length) return;
    control.pushUndoStop();
    control.executeEdits('undisclosed.jsx-comment', edits);
    control.pushUndoStop();
    control.focus();
  }
}
