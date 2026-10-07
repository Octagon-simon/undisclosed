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
import { GitCommitGuardContribution } from './git-commit-guard-contribution';
import { TerminalWidget } from '@theia/terminal/lib/browser/base/terminal-widget';
import { PersistentTerminalWidget } from './persistent-terminal-widget';
import { UndisclosedWelcomeWidget } from './undisclosed-welcome-widget';
import { UndisclosedWelcomeContribution } from './undisclosed-welcome-contribution';
import { UndisclosedExplorerAutoRevealContribution } from './undisclosed-explorer-auto-reveal-contribution';
import { UndisclosedTitleBarContribution } from './undisclosed-title-bar-contribution';
import { WebviewEnvironment } from '@theia/plugin-ext/lib/main/browser/webview/webview-environment';
import { UndisclosedWebviewEnvironment } from './undisclosed-webview-environment';

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

  // Phase 4: make every terminal a PersistentTerminalWidget so scrollback
  // survives a reload (VS Code "session restored"). @theia/terminal binds
  // TerminalWidget -> TerminalWidgetImpl in transient scope and its WidgetFactory
  // resolves TerminalWidget from a child container, so rebinding here propagates
  // to newly created terminals. The subclass only ADDS serialize/restore and
  // degrades to a normal terminal if the addon fails, so this is non-breaking.
  rebind(TerminalWidget).to(PersistentTerminalWidget).inTransientScope();

  // NOTE (Theia 1.76): the Source Control UI is now served by the built-in
  // `vscode.git` extension (upstream removed `@theia/git`). The previous
  // `MenusContributionPointHandler` rebind that suppressed vscode.git's SCM
  // menus to avoid duplicating @theia/git has been retired — suppressing them
  // now would remove Source Control entirely. Its API stays available as-is.

  // Webview resource URLs lose the empty-authority separator under the stock
  // @theia/plugin-ext URI.resolve(), 404ing every webview asset (pets render a
  // blue fallback). Bind the concat-based subclass so the '//' survives.
  rebind(WebviewEnvironment)
    .to(UndisclosedWebviewEnvironment)
    .inSingletonScope();

  bindViewContribution(bind, UndisclosedAgentContribution);
  bind(FrontendApplicationContribution).toService(UndisclosedAgentContribution);
  bind(TabBarToolbarContribution).toService(UndisclosedAgentContribution);
  bind(UndisclosedAgentLayoutContribution).toSelf().inSingletonScope();
  bind(FrontendApplicationContribution).toService(UndisclosedAgentLayoutContribution);
  // Also a TabBarToolbarContribution + CommandContribution: it adds the bottom
  // panel Expand/restore button (resizes the bottom area, keeping side bars).
  bind(TabBarToolbarContribution).toService(UndisclosedAgentLayoutContribution);
  bind(CommandContribution).toService(UndisclosedAgentLayoutContribution);
  bind(UndisclosedAgentWidget).toSelf();
  bind(WidgetFactory)
    .toDynamicValue((ctx) => ({
      id: UndisclosedAgentWidget.ID,
      createWidget: () => ctx.container.get<UndisclosedAgentWidget>(UndisclosedAgentWidget),
    }))
    .inSingletonScope();

  // Branded welcome shown in the main area when no workspace is open.
  bind(UndisclosedWelcomeWidget).toSelf();
  bind(WidgetFactory)
    .toDynamicValue((ctx) => ({
      id: UndisclosedWelcomeWidget.ID,
      createWidget: () =>
        ctx.container.get<UndisclosedWelcomeWidget>(UndisclosedWelcomeWidget),
    }))
    .inSingletonScope();
  bind(UndisclosedWelcomeContribution).toSelf().inSingletonScope();
  bind(FrontendApplicationContribution).toService(
    UndisclosedWelcomeContribution
  );

  // Re-sync the Explorer with the active editor on every tab click, including a
  // re-click of the already-active tab (the stock navigator only reacts to
  // current-widget *changes*). See undisclosed-explorer-auto-reveal-contribution.ts.
  bind(UndisclosedExplorerAutoRevealContribution).toSelf().inSingletonScope();
  bind(FrontendApplicationContribution).toService(
    UndisclosedExplorerAutoRevealContribution
  );

  // Custom centered macOS title bar: replaces the (macOS 26) native, left
  // aligned window title while keeping the native traffic lights. Electron +
  // macOS only; a no-op in the browser and on Windows/Linux, where Theia
  // already draws its own centered title bar.
  bind(UndisclosedTitleBarContribution).toSelf().inSingletonScope();
  bind(FrontendApplicationContribution).toService(
    UndisclosedTitleBarContribution
  );

  // Extra git commands (Undo Last Commit, unstage/discard all) + AI commit
  // message button in the Source Control toolbar.
  bind(GitExtrasContribution).toSelf().inSingletonScope();
  bind(CommandContribution).toService(GitExtrasContribution);
  bind(MenuContribution).toService(GitExtrasContribution);
  bind(TabBarToolbarContribution).toService(GitExtrasContribution);

  // Stop the Source Control commit box from hanging on an empty message: force
  // the prompt flow (not the editor hand-off) and show an inline validation.
  bind(GitCommitGuardContribution).toSelf().inSingletonScope();
  bind(FrontendApplicationContribution).toService(GitCommitGuardContribution);
});
