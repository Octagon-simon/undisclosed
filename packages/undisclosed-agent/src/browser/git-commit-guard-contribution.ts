// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Guard for the Source Control commit box.
//
// WHY THIS EXISTS
// The bundled `vscode.git` extension defaults `git.useEditorAsCommitInput` to
// true (same default as upstream VS Code 1.95). With it on, committing with an
// EMPTY message does not prompt and does not fail fast: the extension hands the
// commit off to a full text editor. `git commit` is spawned with a git-editor
// shim that opens `.git/COMMIT_EDITMSG` and the extension only lets the git
// process continue once that editor tab is CLOSED. If the user never closes it,
// `git commit` parks forever and the Source Control view keeps showing its thin
// "loading" progress strip. No commit, no error, no way out from the SCM panel.
//
// WHAT WE DO
//  1. Override the default to `false`. That changes ONLY the empty-message case:
//     a typed message still commits exactly as before, but an empty box now asks
//     the user for a message through the quick input instead of the hanging
//     editor hand-off.
//  2. Surface an inline validation error on the commit box while it is empty, so
//     the requirement is visible and an empty submission has obvious feedback.

import { inject, injectable } from '@theia/core/shared/inversify';
import { DisposableCollection } from '@theia/core/lib/common';
import { FrontendApplicationContribution } from '@theia/core/lib/browser';
import { PreferenceSchemaService } from '@theia/core/lib/common/preferences/preference-schema';
import { ScmService } from '@theia/scm/lib/browser/scm-service';
import {
  ScmInput,
  ScmInputIssue,
  ScmInputIssueType,
} from '@theia/scm/lib/browser/scm-input';

/** The git preference that decides between the prompt and the editor hand-off. */
const EDITOR_COMMIT_INPUT = 'git.useEditorAsCommitInput';

/** Shown under the commit box while it is empty. */
export const COMMIT_MESSAGE_REQUIRED =
  'Please provide a commit message before committing.';

@injectable()
export class GitCommitGuardContribution
  implements FrontendApplicationContribution
{
  @inject(PreferenceSchemaService)
  protected readonly schemaService!: PreferenceSchemaService;

  @inject(ScmService) protected readonly scm!: ScmService;

  protected readonly toDispose = new DisposableCollection();
  /** Listeners bound to the currently selected repository's input box. */
  protected readonly inputDisposables = new DisposableCollection();
  protected watchedInput: ScmInput | undefined;
  /** Ensures we re-apply the override only once, after the `git` schema loads. */
  protected schemaRearmed = false;

  onStart(): void {
    // (1) Force the non-hanging empty-message flow. This override is layered on
    // top of the extension's default and is never persisted to the user's
    // settings. It is stored even if the `git` schema is not registered yet, but
    // re-applying once the property appears is cheap insurance against any
    // schema-registration ordering.
    this.applyEditorCommitOverride();
    this.toDispose.push(
      this.schemaService.onDidChangeSchema(() => {
        if (
          !this.schemaRearmed &&
          this.schemaService.getSchemaProperty(EDITOR_COMMIT_INPUT)
        ) {
          this.schemaRearmed = true;
          this.applyEditorCommitOverride();
        }
      })
    );

    // (2) Inline validation while the commit box is empty.
    const watch = (): void => this.watchSelectedRepository();
    this.toDispose.push(this.scm.onDidChangeSelectedRepository(watch));
    watch();
  }

  onStop(): void {
    this.toDispose.dispose();
    this.inputDisposables.dispose();
  }

  protected applyEditorCommitOverride(): void {
    this.toDispose.push(
      this.schemaService.registerOverride(EDITOR_COMMIT_INPUT, undefined, false)
    );
  }

  protected watchSelectedRepository(): void {
    const input = this.scm.selectedRepository?.input;
    if (input === this.watchedInput) {
      return;
    }
    this.watchedInput = input;
    this.inputDisposables.dispose();
    if (!input) {
      return;
    }
    this.inputDisposables.push(
      input.onDidChange(() => this.updateValidation(input))
    );
    this.updateValidation(input);
  }

  /** Show an error under the commit box while it is empty, clear it otherwise. */
  protected updateValidation(input: ScmInput): void {
    const empty = input.value.trim().length === 0;
    const next: ScmInputIssue | undefined = empty
      ? { type: ScmInputIssueType.Error, message: COMMIT_MESSAGE_REQUIRED }
      : undefined;
    const current = input.issue;
    const same =
      (!current && !next) ||
      (!!current &&
        !!next &&
        current.type === next.type &&
        current.message === next.message);
    if (!same) {
      input.issue = next;
    }
  }
}
