// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Keep the Explorer in sync with the active editor tab on EVERY tab click.
//
// Why this exists: the stock `@theia/navigator` FileNavigatorContribution only
// reveals the current file when `ApplicationShell.onDidChangeCurrentWidget`
// fires (navigator-contribution.ts `doInit`). That event fires only when the
// current widget CHANGES. Clicking a tab that is ALREADY current fires
// nothing, so if the tree ever drifts out of sync (a reveal raced navigator
// startup and was dropped, the user collapsed the tree, etc.) you cannot fix
// it by clicking the file you are already on. You must switch to another tab
// and back. That matches the "click file 3, then 2, then 1" workaround.
//
// The fix: also listen to each tab bar's `tabActivateRequested`, which fires on
// EVERY tab click including a re-click of the active tab, and ask the navigator
// to reveal the clicked tab's file. We pass `title.owner` (the widget the tab
// belongs to) rather than `shell.currentWidget`, so the reveal does not depend
// on the activation order inside the shell. The existing
// onDidChangeCurrentWidget listener stays untouched for keyboard cycling and
// files opened by commands/agent that don't go through a tab click.
//
// Tab bars are created lazily (first widget added to an area, a split, a
// restored layout), and `ApplicationShell` does not expose a "tab bar created"
// event, so we (re)scan `shell.allTabBars` at startup and whenever a widget is
// added or the current widget changes, attaching at most once per tab bar.

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  ApplicationShell,
  FrontendApplicationContribution,
} from '@theia/core/lib/browser';
import { TabBar, Widget } from '@theia/core/shared/@lumino/widgets';
import { FileNavigatorContribution } from '@theia/navigator/lib/browser/navigator-contribution';
import { FileNavigatorPreferences } from '@theia/navigator/lib/browser/navigator-preferences';

/**
 * Reveals the file backing a tab in the Explorer whenever that tab is clicked,
 * complementing the stock `onDidChangeCurrentWidget` hook so a re-click of the
 * already-active tab also re-syncs the tree.
 */
@injectable()
export class UndisclosedExplorerAutoRevealContribution
  implements FrontendApplicationContribution
{
  @inject(ApplicationShell) protected readonly shell!: ApplicationShell;
  @inject(FileNavigatorContribution)
  protected readonly navigator!: FileNavigatorContribution;
  @inject(FileNavigatorPreferences)
  protected readonly fileNavigatorPreferences!: FileNavigatorPreferences;

  /** Tab bars we have already wired, so a rescan never connects twice. */
  protected readonly attached = new WeakSet<TabBar<Widget>>();

  onStart(): void {
    this.attachToTabBars();
    // New tab bars appear when a widget is added to an area (first open, split,
    // restored layout); re-scan then. `onDidChangeCurrentWidget` is a cheap
    // extra safety net for an area whose tab bar showed up late.
    this.shell.onDidAddWidget(() => this.attachToTabBars());
    this.shell.onDidChangeCurrentWidget(() => this.attachToTabBars());
  }

  protected attachToTabBars(): void {
    for (const tabBar of this.shell.allTabBars) {
      if (this.attached.has(tabBar)) {
        continue;
      }
      this.attached.add(tabBar);
      tabBar.tabActivateRequested.connect((_sender, { title }) => {
        if (this.fileNavigatorPreferences['explorer.autoReveal']) {
          // `selectWidgetFileNode` no-ops for non-navigatable widgets (panel
          // tabs, terminals, etc.), so no filtering is needed here.
          void this.navigator.selectWidgetFileNode(title.owner);
        }
      });
    }
  }
}
