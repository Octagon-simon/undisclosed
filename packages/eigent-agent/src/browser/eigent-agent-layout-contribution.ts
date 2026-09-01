// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  ApplicationShell,
  FrontendApplicationContribution,
} from '@theia/core/lib/browser';

/** Widget ids removed from the default layout (unwanted stock-Theia views). */
const REMOVE_VIEW_IDS = [
  'outline-view',
  'open-editors',
  'theia-open-editors-widget',
  'open-editors-widget',
  'navigator-open-editors',
  'files:open-editors',
];

/**
 * Trims stock-Theia views we don't want in the editor-first shell — currently
 * the Outline view and Open Editors view. Closes them on layout restore and prevents
 * automatic launch.
 */
@injectable()
export class EigentAgentLayoutContribution
  implements FrontendApplicationContribution
{
  @inject(ApplicationShell)
  protected readonly shell!: ApplicationShell;

  constructor() {
    this.injectHeaderStyles();
  }

  onStart(): void {
    this.injectHeaderStyles();
    this.setupViewGuard();
  }

  onDidInitializeLayout(): void {
    this.injectHeaderStyles();
    this.removeViews();
    this.setupViewGuard();
    // Layout restore can re-add a view a tick later; sweep once more.
    setTimeout(() => this.removeViews(), 0);
  }

  private setupViewGuard(): void {
    if (this.shell.onDidAddWidget) {
      this.shell.onDidAddWidget((widget) => {
        if (this.isUnwantedView(widget.id, widget.title?.label)) {
          setTimeout(() => widget.close(), 0);
        }
      });
    }
  }

  private isUnwantedView(id: string, label?: string): boolean {
    const lowerId = id.toLowerCase();
    const lowerLabel = (label || '').toLowerCase();
    return (
      REMOVE_VIEW_IDS.includes(id) ||
      lowerId.includes('open-editor') ||
      lowerLabel.includes('open editor')
    );
  }

  private injectHeaderStyles(): void {
    if (typeof document === 'undefined') {
      return;
    }
    const styleId = 'eigent-agent-header-style';
    if (document.getElementById(styleId)) {
      return;
    }
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = `
      /* 1. Header Toolbar Layout & Alignment */
      .theia-sidepanel-toolbar.theia-right-side-panel,
      #theia-right-content-panel .theia-sidepanel-toolbar,
      #theia-right-side-panel .theia-sidepanel-toolbar {
        border-bottom: 1px solid var(--theia-sideBar-border, var(--theia-panel-border, rgba(255, 255, 255, 0.12))) !important;
        background-color: var(--theia-sideBar-background, var(--theia-editor-background)) !important;
        box-sizing: border-box !important;
        min-height: 35px !important;
        height: 35px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: space-between !important;
        padding: 0 6px 0 12px !important;
      }

      /* Panel Title ("EIGENT AGENT") Flush Left */
      .theia-sidepanel-toolbar.theia-right-side-panel .theia-sidepanel-title,
      #theia-right-content-panel .theia-sidepanel-title {
        font-size: 11px !important;
        font-weight: 600 !important;
        letter-spacing: 0.5px !important;
        text-transform: uppercase !important;
        color: var(--theia-sideBarTitle-foreground, var(--theia-sideBar-foreground, var(--theia-foreground))) !important;
        padding: 0 !important;
        margin: 0 !important;
      }

      /* 2. Toolbar Icon Spacing & No-Shift Click States (+, History, ..., X) */
      .theia-sidepanel-toolbar.theia-right-side-panel .lm-TabBar-toolbar,
      #theia-right-content-panel .lm-TabBar-toolbar {
        display: flex !important;
        align-items: center !important;
        gap: 2px !important;
      }

      .theia-sidepanel-toolbar.theia-right-side-panel .item,
      #theia-right-content-panel .item {
        width: 26px !important;
        height: 26px !important;
        min-width: 26px !important;
        min-height: 26px !important;
        box-sizing: border-box !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        transform: none !important;
        margin: 0 !important;
        padding: 0 !important;
        border-radius: 4px !important;
        cursor: pointer !important;
        opacity: 0.7 !important;
        transition: background-color 0.12s ease, opacity 0.12s ease !important;
      }

      .theia-sidepanel-toolbar.theia-right-side-panel .item *,
      #theia-right-content-panel .item * {
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        transform: none !important;
        margin: 0 !important;
      }

      .theia-sidepanel-toolbar.theia-right-side-panel .item:hover,
      #theia-right-content-panel .item:hover {
        background-color: var(--theia-toolbar-hoverBackground, var(--theia-list-hoverBackground, rgba(127, 127, 127, 0.12))) !important;
        opacity: 1 !important;
      }

      .theia-sidepanel-toolbar.theia-right-side-panel .item:active,
      .theia-sidepanel-toolbar.theia-right-side-panel .item.active,
      .theia-sidepanel-toolbar.theia-right-side-panel .item.toggled,
      #theia-right-content-panel .item:active,
      #theia-right-content-panel .item.active,
      #theia-right-content-panel .item.toggled,
      /* The ⋯ (menu) item's "menu open" active class lands on its chevron
         wrapper (which we hide), not the .item — so the ⋯ never highlighted
         while History (toggled) did. Reflect it onto the whole item. */
      .theia-sidepanel-toolbar.theia-right-side-panel .item.menu:has(> div.active),
      #theia-right-content-panel .item.menu:has(> div.active) {
        /* Subtle NEUTRAL highlight for pressed / toggled (History open) / open-menu
           states — the theme's activeSelectionBackground is a strong accent (red
           here) that dominated and read as "the active button" even when you'd
           just clicked a different one. */
        background-color: rgba(127, 127, 127, 0.22) !important;
        opacity: 1 !important;
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        transform: none !important;
      }

      /* 3. Chatbox & Panel Typography */
      .eigent-agent-root,
      .eigent-agent-root *,
      .eigent-agent-root textarea,
      .eigent-agent-root input,
      .eigent-agent-root [contenteditable] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji" !important;
      }

      .eigent-agent-root code,
      .eigent-agent-root pre,
      .eigent-agent-root code *,
      .eigent-agent-root pre * {
        font-family: var(--theia-editor-font-family, ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace) !important;
      }
    `;
    document.head.appendChild(style);
  }

  private removeViews(): void {
    // (The right tab strip is handled by EigentSidePanelHandler, not here.)
    for (const widget of this.shell.widgets) {
      if (this.isUnwantedView(widget.id, widget.title?.label)) {
        widget.close();
      }
    }
  }
}
