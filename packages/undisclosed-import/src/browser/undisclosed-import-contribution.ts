// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  Command,
  CommandContribution,
  CommandRegistry,
  MessageService,
} from '@theia/core/lib/common';
import {
  FrontendApplicationContribution,
  PreferenceScope,
  PreferenceService,
  StatusBar,
  StatusBarAlignment,
} from '@theia/core/lib/browser';
import { StorageService } from '@theia/core/lib/browser/storage-service';
import { ProgressService } from '@theia/core/lib/common/progress-service';
import { VSXExtensionsModel } from '@theia/vsx-registry/lib/browser/vsx-extensions-model';
import { VSCODE_IMPORT_ROUTE, VscodeImportData } from '../common/protocol';

export const IMPORT_VSCODE_COMMAND: Command = {
  id: 'undisclosed.import.vscode',
  label: 'Undisclosed: Import Settings & Extensions from VS Code',
};

const PROMPTED_KEY = 'undisclosed.import.vscode.prompted';
const STATUS_BAR_ID = 'undisclosed.import.vscode';

@injectable()
export class UndisclosedImportContribution
  implements CommandContribution, FrontendApplicationContribution
{
  @inject(PreferenceService)
  protected readonly preferences!: PreferenceService;

  @inject(MessageService)
  protected readonly messages!: MessageService;

  @inject(StorageService)
  protected readonly storage!: StorageService;

  @inject(StatusBar)
  protected readonly statusBar!: StatusBar;

  @inject(ProgressService)
  protected readonly progressService!: ProgressService;

  @inject(VSXExtensionsModel)
  protected readonly extensions!: VSXExtensionsModel;

  registerCommands(registry: CommandRegistry): void {
    registry.registerCommand(IMPORT_VSCODE_COMMAND, {
      execute: () => this.runImport(),
    });
  }

  onStart(): void {
    // Bottom-left status-bar entry, matching where VS Code surfaces this.
    this.statusBar.setElement(STATUS_BAR_ID, {
      text: '$(cloud-download) Import from VS Code',
      tooltip: 'Import your VS Code settings and extensions',
      alignment: StatusBarAlignment.LEFT,
      priority: 50,
      command: IMPORT_VSCODE_COMMAND.id,
    });
    void this.maybePromptFirstRun();
  }

  /** Offer the import once, on first launch, only if a VS Code install exists. */
  protected async maybePromptFirstRun(): Promise<void> {
    try {
      const prompted = await this.storage.getData<boolean>(PROMPTED_KEY, false);
      if (prompted) {
        return;
      }
      await this.storage.setData(PROMPTED_KEY, true);
      const data = await this.fetchData();
      if (!data.found) {
        return; // nothing to import — don't nag
      }
      const action = await this.messages.info(
        `Found VS Code (${data.variant}). Import its settings and ` +
          `${data.extensions.length} extensions into Undisclosed?`,
        'Import',
        'Not now'
      );
      if (action === 'Import') {
        await this.applyImport(data);
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[undisclosed-import] first-run prompt failed:', err);
    }
  }

  /** Command/button entry point: fetch fresh then import. */
  protected async runImport(): Promise<void> {
    const data = await this.fetchData();
    if (!data.found) {
      this.messages.info('No VS Code installation was found to import from.');
      return;
    }
    await this.applyImport(data);
  }

  protected async applyImport(data: VscodeImportData): Promise<void> {
    // 1) Settings -> user preferences. Best-effort per key: VS Code has keys
    //    Theia doesn't know, which can throw; skip those rather than abort.
    let applied = 0;
    let skipped = 0;
    for (const [key, value] of Object.entries(data.settings || {})) {
      try {
        await this.preferences.set(key, value, PreferenceScope.User);
        applied++;
      } catch {
        skipped++;
      }
    }

    // 2) Extensions -> install from Open VSX. Some (MS-proprietary) won't be
    //    there; collect those to report rather than fail the whole run.
    let installed = 0;
    let already = 0;
    const unavailable: string[] = [];
    await this.progressService.withProgress(
      `Importing ${data.extensions.length} extensions from Open VSX`,
      'notification',
      async () => {
        for (const id of data.extensions) {
          if (this.extensions.isInstalled(id)) {
            already++;
            continue;
          }
          try {
            const ext = await this.extensions.resolve(id);
            await ext.install();
            installed++;
          } catch {
            unavailable.push(id);
          }
        }
      }
    );

    const parts = [
      `Applied ${applied} settings` + (skipped ? ` (${skipped} skipped)` : ''),
      `installed ${installed} extensions` +
        (already ? ` (${already} already present)` : ''),
    ];
    if (unavailable.length) {
      parts.push(`${unavailable.length} not available on Open VSX`);
    }
    this.messages.info(`Import complete: ${parts.join(', ')}.`);
  }

  protected async fetchData(): Promise<VscodeImportData> {
    const res = await fetch(VSCODE_IMPORT_ROUTE, {
      headers: { Accept: 'application/json' },
    });
    if (!res.ok) {
      throw new Error(`import endpoint returned ${res.status}`);
    }
    return (await res.json()) as VscodeImportData;
  }
}
