// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  AbstractViewContribution,
  FrontendApplicationContribution,
  StorageService,
} from '@theia/core/lib/browser';
import { EigentAgentWidget } from './eigent-agent-widget';

export const EIGENT_AGENT_TOGGLE_COMMAND_ID = 'eigent-agent:toggle';

/** Storage flag: whether we've already shown the panel once (first-run reveal). */
const INTRODUCED_KEY = 'eigent-agent.introduced';

/**
 * Registers the "Eigent Agent" view: a toggle command + keybinding (View menu /
 * command palette / Cmd(Ctrl)+Shift+A) and places the widget in the right panel.
 *
 * Visibility policy — "on by default, user can hide":
 *  - `initializeLayout` opens it for a *fresh* workbench (no saved layout).
 *  - `onStart` opens it the *first time the extension is present* for users who
 *    already have a saved layout (so upgrades get it too), then records a flag.
 *  - After that, Theia's layout persistence remembers the user's show/hide
 *    choice — hiding it sticks.
 */
@injectable()
export class EigentAgentContribution
  extends AbstractViewContribution<EigentAgentWidget>
  implements FrontendApplicationContribution
{
  @inject(StorageService)
  protected readonly storageService!: StorageService;

  constructor() {
    super({
      widgetId: EigentAgentWidget.ID,
      widgetName: EigentAgentWidget.LABEL,
      defaultWidgetOptions: { area: 'right', rank: 100 },
      toggleCommandId: EIGENT_AGENT_TOGGLE_COMMAND_ID,
      toggleKeybinding: 'ctrlcmd+shift+a',
    });
  }

  async onStart(): Promise<void> {
    const introduced = await this.storageService.getData<boolean>(
      INTRODUCED_KEY,
      false
    );
    if (!introduced) {
      await this.openView({ activate: false, reveal: true });
      await this.storageService.setData(INTRODUCED_KEY, true);
    }
  }

  async initializeLayout(): Promise<void> {
    await this.openView({ activate: false, reveal: true });
  }
}
