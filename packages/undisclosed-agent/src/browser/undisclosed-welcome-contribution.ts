// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Shows the branded welcome widget in the main area when there is NO open
// workspace, and closes it once a folder is opened. Keeps the editor from being
// a plain black void before a workspace is selected.

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

  onStart(): void {
    // React to the workspace opening/closing at runtime.
    this.workspaceService.onWorkspaceChanged(() => void this.refresh());
    this.workspaceService.onWorkspaceLocationChanged(() => void this.refresh());
  }

  // `onDidInitializeLayout` fires on EVERY boot — both when Theia creates a
  // fresh default layout and when it restores a saved one. `initializeLayout`
  // only fires on a fresh layout, so on a plain reload (saved layout restored)
  // it never runs and the welcome never appears. Hook the one that always fires.
  onDidInitializeLayout(): void {
    void this.refresh();
  }

  protected async refresh(): Promise<void> {
    if (this.workspaceService.opened) {
      // A folder is open — the editor has real content; drop the welcome.
      const existing = this.widgetManager.tryGetWidget(
        UndisclosedWelcomeWidget.ID
      );
      existing?.close();
      return;
    }
    // No workspace — show the welcome in the main area (don't steal focus from
    // the agent panel on first boot; activate only so it's the visible tab).
    const widget = await this.widgetManager.getOrCreateWidget(
      UndisclosedWelcomeWidget.ID
    );
    if (!widget.isAttached) {
      this.shell.addWidget(widget, { area: 'main' });
    }
    this.shell.activateWidget(widget.id);
  }
}
