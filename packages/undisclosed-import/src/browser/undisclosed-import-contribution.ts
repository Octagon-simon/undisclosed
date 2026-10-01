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
import { backendUrl } from './backend-url';
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
/** Persisted summary of the last import so the status bar can show a stable
 *  "done" state across launches (the button otherwise looked identical whether
 *  or not an import had ever run — you couldn't tell if it was done). */
const RESULT_KEY = 'undisclosed.import.vscode.result';

interface ImportResult {
  /** Extensions now present in Undisclosed out of VS Code's list. */
  installed: number;
  /** Total extensions VS Code had. */
  total: number;
  /** Settings keys applied. */
  settings: number;
  at: number;
}

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
    // Reflect a prior import's result so the button reads as "done" instead of
    // looking un-run forever.
    void this.storage
      .getData<ImportResult | undefined>(RESULT_KEY, undefined)
      .then((prev) => (prev ? this.setStatusDone(prev) : this.setStatusIdle()))
      .catch(() => this.setStatusIdle());
    void this.maybePromptFirstRun();
  }

  /** The pre-import call-to-action. */
  protected setStatusIdle(): void {
    this.statusBar.setElement(STATUS_BAR_ID, {
      text: '$(cloud-download) Import from VS Code',
      tooltip: 'Import your VS Code settings and extensions',
      alignment: StatusBarAlignment.LEFT,
      priority: 50,
      command: IMPORT_VSCODE_COMMAND.id,
    });
  }

  /** In-progress state — spinner, non-clickable. */
  protected setStatusImporting(): void {
    this.statusBar.setElement(STATUS_BAR_ID, {
      text: '$(sync~spin) Importing from VS Code…',
      tooltip: 'Importing your VS Code settings and extensions…',
      alignment: StatusBarAlignment.LEFT,
      priority: 50,
    });
  }

  /** Done state — shows extension coverage (installed / VS Code total) so you
   *  can see how much carried over; click to re-check / re-import. */
  protected setStatusDone(r: ImportResult): void {
    this.statusBar.setElement(STATUS_BAR_ID, {
      text: `$(check) VS Code imported (${r.installed}/${r.total})`,
      tooltip:
        `Imported ${r.installed} of ${r.total} VS Code extensions ` +
        `and ${r.settings} settings. Some VS Code extensions aren't on ` +
        `Open VSX, so the count can be lower than VS Code's. ` +
        `Click to re-check / re-import.`,
      alignment: StatusBarAlignment.LEFT,
      priority: 50,
      command: IMPORT_VSCODE_COMMAND.id,
    });
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
    this.setStatusImporting();
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

    // Coverage = how many of VS Code's extensions are now present here (freshly
    // installed + already had). This is the "check from both platforms" number:
    // Undisclosed-installed / VS Code-total.
    const total = data.extensions.length;
    const present = data.extensions.filter((id) =>
      this.extensions.isInstalled(id)
    ).length;
    const result: ImportResult = {
      installed: present,
      total,
      settings: applied,
      at: Date.now(),
    };
    try {
      await this.storage.setData(RESULT_KEY, result);
    } catch {
      /* storage unavailable — status still updates for this session */
    }
    this.setStatusDone(result);

    const parts = [
      `Applied ${applied} settings` + (skipped ? ` (${skipped} skipped)` : ''),
      `${present}/${total} extensions now present` +
        (installed ? ` (${installed} newly installed)` : '') +
        (already ? ` (${already} already had)` : ''),
    ];
    if (unavailable.length) {
      parts.push(`${unavailable.length} not on Open VSX`);
    }
    this.messages.info(`VS Code import complete: ${parts.join(', ')}.`);
  }

  protected async fetchData(): Promise<VscodeImportData> {
    // Absolute backend URL — a relative path resolves to file:// in the packaged
    // Electron app and 404s (ERR_FILE_NOT_FOUND).
    const res = await fetch(backendUrl(VSCODE_IMPORT_ROUTE), {
      headers: { Accept: 'application/json' },
    });
    if (!res.ok) {
      throw new Error(`import endpoint returned ${res.status}`);
    }
    return (await res.json()) as VscodeImportData;
  }
}
