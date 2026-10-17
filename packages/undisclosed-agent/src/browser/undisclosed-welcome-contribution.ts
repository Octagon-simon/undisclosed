// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Keeps the branded welcome in the main area whenever no editor is open, and
// drops it as soon as a real widget (an editor, settings, …) takes that area.

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  ApplicationShell,
  FrontendApplicationContribution,
  WidgetManager,
} from '@theia/core/lib/browser';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { UndisclosedWelcomeWidget } from './undisclosed-welcome-widget';

@injectable()
export class UndisclosedWelcomeContribution
  implements FrontendApplicationContribution
{
  @inject(WorkspaceService)
  protected readonly workspaceService!: WorkspaceService;
  @inject(WidgetManager) protected readonly widgetManager!: WidgetManager;
  @inject(ApplicationShell) protected readonly shell!: ApplicationShell;

  protected refreshQueued = false;

  onStart(): void {
    const refresh = (): void => this.scheduleRefresh();
    // Workspace changes swap the copy (open-folder buttons vs. editing hints).
    this.workspaceService.onWorkspaceChanged(refresh);
    this.workspaceService.onWorkspaceLocationChanged(refresh);
    // Opening the first editor or closing the last one changes what belongs in
    // the main area. `onDidInitializeLayout` only fires on a fresh layout, so
    // widget add/remove is what keeps a restored layout correct too.
    this.shell.onDidAddWidget(refresh);
    this.shell.onDidRemoveWidget(refresh);
  }

  onDidInitializeLayout(): void {
    this.scheduleRefresh();
  }

  /**
   * Defer the layout mutation out of the shell's add/remove signal (closing or
   * adding a widget while that signal is still running is re-entrant), and
   * collapse a burst of restored editors into one refresh.
   */
  protected scheduleRefresh(): void {
    if (this.refreshQueued) {
      return;
    }
    this.refreshQueued = true;
    setTimeout(() => {
      this.refreshQueued = false;
      void this.refresh();
    }, 0);
  }

  /** Main-area content other than our own welcome widget. */
  protected hasMainContent(): boolean {
    return Array.from(this.shell.mainPanel.widgets()).some(
      (widget) => widget.id !== UndisclosedWelcomeWidget.ID
    );
  }

  protected async refresh(): Promise<void> {
    const existing = this.widgetManager.tryGetWidget(
      UndisclosedWelcomeWidget.ID
    );
    if (this.hasMainContent()) {
      existing?.close();
      return;
    }
    const widget =
      existing ??
      (await this.widgetManager.getOrCreateWidget(
        UndisclosedWelcomeWidget.ID
      ));
    // Another widget may have claimed the area while the factory resolved.
    if (this.hasMainContent()) {
      widget.close();
      return;
    }
    let added = false;
    if (!widget.isAttached) {
      this.shell.addWidget(widget, { area: 'main' });
      added = true;
    }
    widget.update();
    // Only claim focus when the welcome just took over the empty area; other
    // widgets being added/removed (e.g. the agent panel) must not steal it.
    if (added) {
      this.shell.activateWidget(widget.id);
    }
  }
}
