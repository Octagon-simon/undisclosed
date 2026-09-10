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
export class UndisclosedAgentLayoutContribution
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
    const styleId = 'undisclosed-agent-header-style';
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

      /* Panel Title ("UNDISCLOSED AGENT") Flush Left */
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
      .undisclosed-agent-root,
      .undisclosed-agent-root *,
      .undisclosed-agent-root textarea,
      .undisclosed-agent-root input,
      .undisclosed-agent-root [contenteditable] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji" !important;
      }

      .undisclosed-agent-root code,
      .undisclosed-agent-root pre,
      .undisclosed-agent-root code *,
      .undisclosed-agent-root pre * {
        font-family: var(--theia-editor-font-family, ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace) !important;
      }

      /* 4. "Find All References" peek — the CLICKED (selected/focused) row was
         pink-on-pink: the theme's strong accent selection background plus a
         same-hue match highlight hid the symbol text. workbench.colorCustomizations
         didn't override it here, so force it in CSS: neutral selection + a
         high-contrast, transparent-background match highlight that reads on any
         row state. (Hover is fine; this only fixes the selected/focused state.) */
      .monaco-editor .reference-zone-widget .ref-tree .monaco-list-row.selected,
      .monaco-editor .reference-zone-widget .ref-tree .monaco-list-row.focused,
      .monaco-editor .peekview-widget .ref-tree .monaco-list-row.selected,
      .monaco-editor .peekview-widget .ref-tree .monaco-list-row.focused {
        background-color: #37373d !important;
        color: #ffffff !important;
      }
      .monaco-editor .reference-zone-widget .ref-tree .monaco-list-row .highlight,
      .monaco-editor .peekview-widget .ref-tree .monaco-list-row .highlight,
      .monaco-editor .reference-zone-widget .ref-tree .referenceMatch .highlight,
      .monaco-editor .peekview-widget .ref-tree .referenceMatch .highlight {
        background-color: transparent !important;
        color: #ffcc66 !important;
        font-weight: 700 !important;
      }

      /* 5. Divider after our editor "Chat with Agent" action so it doesn't run
         into the next item (e.g. Lacuna's "Generate Tests"). A border-right
         traced the item's rounded corner (curved + shadowy), so use a straight
         pseudo-element rule instead and strip any inherited radius/shadow.
         (id has a dot → attribute selector, not "#id".) */
      .lm-TabBar-toolbar [id="undisclosed-agent.open"],
      .p-TabBar-toolbar [id="undisclosed-agent.open"] {
        position: relative !important;
        overflow: visible !important;
        margin-right: 12px !important;
        border-radius: 0 !important;
        box-shadow: none !important;
      }
      .lm-TabBar-toolbar [id="undisclosed-agent.open"]::after,
      .p-TabBar-toolbar [id="undisclosed-agent.open"]::after {
        content: "" !important;
        position: absolute !important;
        right: -6px !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        width: 1px !important;
        height: 14px !important;
        background: var(--theia-editorGroup-border, var(--theia-panel-border, rgba(127, 127, 127, 0.4))) !important;
        pointer-events: none !important;
      }
    `;
    document.head.appendChild(style);
  }

  private removeViews(): void {
    // (The right tab strip is handled by UndisclosedSidePanelHandler, not here.)
    for (const widget of this.shell.widgets) {
      if (this.isUnwantedView(widget.id, widget.title?.label)) {
        widget.close();
      }
    }
  }
}
