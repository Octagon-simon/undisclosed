// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { ContainerModule } from '@theia/core/shared/inversify';
import {
  bindViewContribution,
  FrontendApplicationContribution,
  WidgetFactory,
} from '@theia/core/lib/browser';
import { TabBarToolbarContribution } from '@theia/core/lib/browser/shell/tab-bar-toolbar';
import {
  CommandContribution,
  MenuContribution,
} from '@theia/core/lib/common';
import { SidePanelHandler } from '@theia/core/lib/browser/shell/side-panel-handler';
import { UndisclosedSidePanelHandler } from './undisclosed-side-panel-handler';
import { UndisclosedAgentWidget } from './undisclosed-agent-widget';
import { UndisclosedAgentContribution } from './undisclosed-agent-contribution';
import { UndisclosedAgentLayoutContribution } from './undisclosed-agent-layout-contribution';
import { GitExtrasContribution } from './git-extras-contribution';

/**
 * Frontend DI module (referenced by `theiaExtensions` in package.json). Binds
 * the view contribution + a widget factory so Theia can create/restore the
 * Undisclosed Agent panel, and wires `initializeLayout` via
 * FrontendApplicationContribution so it opens on first boot.
 */
export default new ContainerModule((bind, _unbind, _isBound, rebind) => {
  // Replace the right-side tab strip behavior (keep it hidden). The
  // SidePanelHandlerFactory is a toAutoFactory over SidePanelHandler, so
  // rebinding the impl makes both left+right handlers use our subclass (which
  // only alters the RIGHT side).
  rebind(SidePanelHandler).to(UndisclosedSidePanelHandler);

  bindViewContribution(bind, UndisclosedAgentContribution);
  bind(FrontendApplicationContribution).toService(UndisclosedAgentContribution);
  bind(TabBarToolbarContribution).toService(UndisclosedAgentContribution);
  bind(UndisclosedAgentLayoutContribution).toSelf().inSingletonScope();
  bind(FrontendApplicationContribution).toService(UndisclosedAgentLayoutContribution);
  bind(UndisclosedAgentWidget).toSelf();
  bind(WidgetFactory)
    .toDynamicValue((ctx) => ({
      id: UndisclosedAgentWidget.ID,
      createWidget: () => ctx.container.get<UndisclosedAgentWidget>(UndisclosedAgentWidget),
    }))
    .inSingletonScope();

  // Extra git commands (Undo Last Commit, unstage/discard all) + AI commit
  // message button in the Source Control toolbar.
  bind(GitExtrasContribution).toSelf().inSingletonScope();
  bind(CommandContribution).toService(GitExtrasContribution);
  bind(MenuContribution).toService(GitExtrasContribution);
  bind(TabBarToolbarContribution).toService(GitExtrasContribution);
});
