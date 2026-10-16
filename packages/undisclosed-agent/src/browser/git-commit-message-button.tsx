// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// The AI commit-message toolbar button, rendered as a self-contained React node.
//
// WHY A REACT ITEM (and not icon + onDidChange): the stock RenderedToolbarItem
// drives its icon from a registry-wide `onDidChange`, and TabBarToolbar answers
// that by re-rendering EVERY item in the container. In Theia 1.76 that re-render
// walks the vscode.git `scm/title` menu items through
// `AbstractToolbarMenuWrapper.renderMenuItem`, which dereferences `widget.node`;
// when the toolbar's current widget is momentarily undefined the render throws
// (`Cannot read properties of undefined (reading 'node')`) and React never
// commits the "finished" frame, so the spinner stays on screen forever.
//
// A ReactTabBarToolbarAction owns its own state: subscribing here re-renders
// only this button, never the container toolbar, so nothing can wedge the icon.

import React from '@theia/core/shared/react';
import type { Disposable } from '@theia/core/lib/common/disposable';
import type { GitExtrasContribution } from './git-extras-contribution';

/** Toolbar item id; also the DOM id of the clickable icon (matches the command). */
export const GENERATE_MESSAGE_ITEM_ID = 'undisclosed.git.generateCommitMessage';

export const GENERATE_MESSAGE_TOOLTIP =
  'Generate a commit message from the staged changes (AI)';

const SPARKLE = 'codicon codicon-sparkle action-label';
const SPINNER = 'codicon codicon-loading codicon-modifier-spin action-label';

/** Entry point used by `GitExtrasContribution.registerToolbarItems`. */
export function renderCommitMessageButton(
  contribution: GitExtrasContribution
): React.ReactNode {
  return <CommitMessageButton contribution={contribution} />;
}

function CommitMessageButton(props: {
  contribution: GitExtrasContribution;
}): React.ReactElement {
  const { contribution } = props;
  const generating = React.useSyncExternalStore(
    React.useCallback(
      (onStoreChange: () => void): (() => void) => {
        const disposable: Disposable =
          contribution.onDidChangeGenerating(onStoreChange);
        return () => disposable.dispose();
      },
      [contribution]
    ),
    () => contribution.isGenerating()
  );
  return (
    <div className={generating ? 'item' : 'item enabled'}>
      <div
        id={GENERATE_MESSAGE_ITEM_ID}
        className={generating ? SPINNER : SPARKLE}
        title={GENERATE_MESSAGE_TOOLTIP}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          if (!generating) {
            void contribution.trigger();
          }
        }}
      >
        {' '}
      </div>
    </div>
  );
}
