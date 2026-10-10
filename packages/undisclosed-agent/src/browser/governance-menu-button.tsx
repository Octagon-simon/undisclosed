// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// The agent panel's "⋯" (governance) toolbar button, rendered as a
// self-contained React node.
//
// WHY A REACT ITEM (and not a `menuPath` item): in Theia 1.76 a toolbar item
// declared with `menuPath` is wrapped by `ToolbarActionWrapper`, which does NOT
// expose `priority` (see @theia/core .../tab-bar-toolbar/tab-bar-toolbar-menu-adapters.js).
// `TabBarToolbar.updateItems` then sorts it with an undefined priority (treated
// as 0), so the ⋯ jumped to the FRONT of the toolbar — before New/History/Browser
// — no matter what `priority` we set. Its click target also split in two: the
// ellipsis ran `executeCommand` (a no-op for a menu item that has no command) and
// only the 1px chevron opened the popup. A React item keeps our `priority` (so
// the button sits after the browser button) and lets the whole ellipsis open the
// menu.

import React from '@theia/core/shared/react';
import type { Widget } from '@theia/core/lib/browser';
import type { UndisclosedAgentContribution } from './undisclosed-agent-contribution';

/** DOM id of the clickable icon. */
export const GOVERNANCE_ITEM_ID = 'undisclosed-agent.more';

export const GOVERNANCE_ITEM_TOOLTIP = 'Governance and options';

/** Entry point used by `UndisclosedAgentContribution.registerToolbarItems`. */
export function renderGovernanceMenuButton(
  contribution: UndisclosedAgentContribution,
  widget?: Widget
): React.ReactNode {
  return (
    <div className="item enabled">
      <div
        id={GOVERNANCE_ITEM_ID}
        className="codicon codicon-ellipsis action-label"
        title={GOVERNANCE_ITEM_TOOLTIP}
        onClick={(event) => contribution.openGovernanceMenu(event, widget)}
      >
        {' '}
      </div>
    </div>
  );
}
