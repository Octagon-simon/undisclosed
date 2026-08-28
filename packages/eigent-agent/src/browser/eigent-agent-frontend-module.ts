// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { ContainerModule } from '@theia/core/shared/inversify';
import {
  bindViewContribution,
  FrontendApplicationContribution,
  WidgetFactory,
} from '@theia/core/lib/browser';
import { EigentAgentWidget } from './eigent-agent-widget';
import { EigentAgentContribution } from './eigent-agent-contribution';

/**
 * Frontend DI module (referenced by `theiaExtensions` in package.json). Binds
 * the view contribution + a widget factory so Theia can create/restore the
 * Eigent Agent panel, and wires `initializeLayout` via
 * FrontendApplicationContribution so it opens on first boot.
 */
export default new ContainerModule((bind) => {
  bindViewContribution(bind, EigentAgentContribution);
  bind(FrontendApplicationContribution).toService(EigentAgentContribution);
  bind(EigentAgentWidget).toSelf();
  bind(WidgetFactory)
    .toDynamicValue((ctx) => ({
      id: EigentAgentWidget.ID,
      createWidget: () => ctx.container.get<EigentAgentWidget>(EigentAgentWidget),
    }))
    .inSingletonScope();
});
