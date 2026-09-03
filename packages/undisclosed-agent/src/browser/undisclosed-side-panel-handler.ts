// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { injectable } from '@theia/core/shared/inversify';
import { SidePanelHandler } from '@theia/core/lib/browser/shell/side-panel-handler';

/**
 * Keeps the RIGHT side-panel tab strip permanently hidden so the agent panel is
 * flush to the edge (Antigravity-style), with no leftover ~48px gap.
 *
 * The stock `SidePanelHandler.refresh()` does `tabBar.setHidden(isEmpty)` — i.e.
 * it RE-SHOWS the tab bar whenever the panel has a widget (our agent). A one-off
 * `.hide()` therefore gets clobbered on the next refresh. Overriding `refresh()`
 * to force the strip hidden (via Lumino's `setHidden`, so the layout re-flows
 * and reclaims the space) is what makes it stick. Left panel is untouched.
 */
@injectable()
export class UndisclosedSidePanelHandler extends SidePanelHandler {
  override refresh(): void {
    super.refresh();
    if (this.side !== 'right') {
      return;
    }
    // Hide the sidebar container (which houses tabBar, top/bottom menus, and the collapsed handle)
    if (this.tabBar.parent) {
      this.tabBar.parent.hide();
    }
    this.tabBar.setHidden(true);
    this.topMenu.setHidden(true);
    this.bottomMenu.setHidden(true);
    this.additionalViewsMenu.setHidden(true);

    // Hide the main right container whenever dockPanel is hidden (collapsed or no active view)
    // eslint-disable-next-line no-null/no-null
    const collapsedOrEmpty = this.tabBar.currentTitle === null || this.dockPanel.isHidden;
    this.container.setHidden(collapsedOrEmpty);
  }
}

