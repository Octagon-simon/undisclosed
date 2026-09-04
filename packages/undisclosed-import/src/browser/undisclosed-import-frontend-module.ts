// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { ContainerModule } from '@theia/core/shared/inversify';
import { CommandContribution } from '@theia/core/lib/common';
import { FrontendApplicationContribution } from '@theia/core/lib/browser';
import { UndisclosedImportContribution } from './undisclosed-import-contribution';

/**
 * Frontend module for the `undisclosed-import` Theia extension: registers the
 * "Import from VS Code" command, the status-bar button, and the first-run
 * prompt (all driven by UndisclosedImportContribution).
 */
export default new ContainerModule((bind) => {
  bind(UndisclosedImportContribution).toSelf().inSingletonScope();
  bind(CommandContribution).toService(UndisclosedImportContribution);
  bind(FrontendApplicationContribution).toService(UndisclosedImportContribution);
});
