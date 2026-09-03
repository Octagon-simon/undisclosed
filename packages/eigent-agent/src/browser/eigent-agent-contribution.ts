// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  AbstractViewContribution,
  FrontendApplicationContribution,
  StorageService,
  Widget,
} from '@theia/core/lib/browser';
import {
  TabBarToolbarContribution,
  TabBarToolbarRegistry,
} from '@theia/core/lib/browser/shell/tab-bar-toolbar';
import {
  Command,
  CommandRegistry,
  MenuModelRegistry,
  MenuPath,
} from '@theia/core/lib/common';
import { EigentAgentWidget } from './eigent-agent-widget';

export const EIGENT_AGENT_TOGGLE_COMMAND_ID = 'eigent-agent:toggle';
const INTRODUCED_KEY = 'eigent-agent.introduced';

const NEW: Command = { id: 'eigent-agent.new-conversation', label: 'New Conversation' };
const HISTORY: Command = { id: 'eigent-agent.history', label: 'History' };
const CLOSE: Command = { id: 'eigent-agent.close', label: 'Close Panel' };
const GOV_ASK: Command = { id: 'eigent-agent.governance-ask' };
const GOV_AUTO: Command = { id: 'eigent-agent.governance-auto' };
const USAGE: Command = { id: 'eigent-agent.usage', label: 'Usage overview' };
const MEMORY: Command = { id: 'eigent-agent.memory', label: 'Memory' };
const MODELS: Command = { id: 'eigent-agent.models', label: 'Models' };
const SETTINGS: Command = { id: 'eigent-agent.settings', label: 'Settings' };
const BROWSER: Command = { id: 'eigent-agent.browser', label: 'Agent browser' };
const THINKING: Command = { id: 'eigent-agent.thinking', label: 'Show thinking' };
/** The `⋯` toolbar item opens this menu. */
const MORE_MENU: MenuPath = ['eigent-agent-more-menu'];

function asAgent(arg: unknown): EigentAgentWidget | undefined {
  return arg instanceof EigentAgentWidget ? arg : undefined;
}

/**
 * The Undisclosed Agent view: opens the panel (right dock, Cmd/Ctrl+Shift+A) and
 * contributes its actions to Theia's NATIVE title-bar toolbar — `+ New`,
 * `History` (toggle), `⋯` (governance), and `✕` (close) — rather than a React
 * header, so the actions sit beside the title (the Antigravity layout).
 */
@injectable()
export class EigentAgentContribution
  extends AbstractViewContribution<EigentAgentWidget>
  implements TabBarToolbarContribution, FrontendApplicationContribution
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

  override registerCommands(commands: CommandRegistry): void {
    super.registerCommands(commands);
    commands.registerCommand(NEW, {
      isVisible: (w) => !!asAgent(w),
      execute: (w) => asAgent(w)?.newConversation(),
    });
    commands.registerCommand(HISTORY, {
      isVisible: (w) => !!asAgent(w),
      isToggled: (w) => asAgent(w)?.isHistoryOpen() ?? false,
      execute: (w) => asAgent(w)?.toggleHistory(),
    });
    commands.registerCommand(CLOSE, {
      isVisible: (w) => !!asAgent(w),
      execute: (w) => asAgent(w)?.close(),
    });
    commands.registerCommand(USAGE, {
      isVisible: (w) => !!asAgent(w),
      execute: (w) => asAgent(w)?.showStats(),
    });
    commands.registerCommand(MEMORY, {
      isVisible: (w) => !!asAgent(w),
      execute: (w) => asAgent(w)?.showMemory(),
    });
    commands.registerCommand(MODELS, {
      isVisible: (w) => !!asAgent(w),
      execute: (w) => asAgent(w)?.showModels(),
    });
    commands.registerCommand(SETTINGS, {
      isVisible: (w) => !!asAgent(w),
      execute: (w) => asAgent(w)?.showSettings(),
    });
    commands.registerCommand(BROWSER, {
      isVisible: (w) => !!asAgent(w),
      execute: (w) => asAgent(w)?.showBrowser(),
    });
    commands.registerCommand(THINKING, {
      isToggled: (w) =>
        (asAgent(w) ?? this.tryGetWidget())?.showThinkingEnabled() ?? true,
      execute: (w) => {
        const widget = asAgent(w) ?? this.tryGetWidget();
        widget?.setShowThinking(!(widget?.showThinkingEnabled() ?? true));
      },
    });
    commands.registerCommand(GOV_ASK, {
      isToggled: (w) => (asAgent(w) ?? this.tryGetWidget())?.governanceMode() === 'ask',
      execute: (w) => (asAgent(w) ?? this.tryGetWidget())?.setGovernance('ask'),
    });
    commands.registerCommand(GOV_AUTO, {
      isToggled: (w) => (asAgent(w) ?? this.tryGetWidget())?.governanceMode() === 'auto',
      execute: (w) => (asAgent(w) ?? this.tryGetWidget())?.setGovernance('auto'),
    });
  }

  override registerMenus(menus: MenuModelRegistry): void {
    super.registerMenus(menus);
    menus.registerMenuAction(MORE_MENU, {
      commandId: USAGE.id,
      label: 'Usage overview',
      order: '0',
    });
    menus.registerMenuAction(MORE_MENU, {
      commandId: MEMORY.id,
      label: 'Memory',
      order: '1',
    });
    menus.registerMenuAction(MORE_MENU, {
      commandId: MODELS.id,
      label: 'Models',
      order: '1.5',
    });
    menus.registerMenuAction(MORE_MENU, {
      commandId: SETTINGS.id,
      label: 'Settings',
      order: '1.7',
    });
    menus.registerMenuAction(MORE_MENU, {
      commandId: THINKING.id,
      label: 'Show thinking',
      order: '2',
    });
    menus.registerMenuAction(MORE_MENU, {
      commandId: GOV_ASK.id,
      label: 'Ask to approve',
      order: 'a',
    });
    menus.registerMenuAction(MORE_MENU, {
      commandId: GOV_AUTO.id,
      label: 'Run automatically',
      order: 'b',
    });
  }

  registerToolbarItems(registry: TabBarToolbarRegistry): void {
    const isVisible = (w: Widget): boolean => !!asAgent(w);
    // Ascending priority renders left→right, so: + New · History · ⋯ · ✕
    // (the Antigravity order).
    registry.registerItem({
      id: NEW.id,
      command: NEW.id,
      tooltip: 'New conversation',
      text: 'New conversation',
      icon: 'codicon codicon-add',
      priority: 1,
      isVisible,
    });
    registry.registerItem({
      id: HISTORY.id,
      command: HISTORY.id,
      tooltip: 'Past conversations',
      text: 'Past conversations',
      icon: 'codicon codicon-history',
      priority: 2,
      isVisible,
    });
    registry.registerItem({
      id: BROWSER.id,
      command: BROWSER.id,
      tooltip: 'Agent browser (live view / take control)',
      text: 'Agent browser',
      icon: 'codicon codicon-globe',
      priority: 3,
      isVisible,
    });
    registry.registerItem({
      id: 'eigent-agent.more',
      icon: 'codicon codicon-ellipsis',
      tooltip: 'Governance mode',
      text: 'Governance mode',
      menuPath: MORE_MENU,
      priority: 4,
      isVisible,
    });
    registry.registerItem({
      id: CLOSE.id,
      command: CLOSE.id,
      tooltip: 'Close panel',
      text: 'Close panel',
      icon: 'codicon codicon-close',
      priority: 5,
      isVisible,
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
