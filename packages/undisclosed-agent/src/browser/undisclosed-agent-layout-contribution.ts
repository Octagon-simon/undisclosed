// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { inject, injectable } from '@theia/core/shared/inversify';
import {
  ApplicationShell,
  FrontendApplicationContribution,
  Widget,
} from '@theia/core/lib/browser';
import {
  TabBarToolbarContribution,
  TabBarToolbarRegistry,
} from '@theia/core/lib/browser/shell/tab-bar-toolbar';
import {
  CommandContribution,
  CommandRegistry,
} from '@theia/core/lib/common/command';

/** Command id for our bottom-panel height toggle (expand ↔ restore). */
const TOGGLE_BOTTOM_EXPAND = 'undisclosed.bottom.toggleExpand';

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
  implements
    FrontendApplicationContribution,
    TabBarToolbarContribution,
    CommandContribution
{
  @inject(ApplicationShell)
  protected readonly shell!: ApplicationShell;

  /** True while the bottom panel is in its tall "expanded" size. */
  protected bottomExpanded = false;

  /**
   * Expand/restore button for the bottom panel toolbar (Problems / Output /
   * Terminal / ...). We deliberately do NOT use Theia's `core.toggleMaximized`:
   * that maximizes the widget over the ENTIRE shell — the activity bar, the side
   * panel (explorer) and the menu all vanish, the button that would restore it
   * is gone, and because the maximized widget becomes "current" the wrong
   * toolbar (Source Control's commit/push, etc.) renders on it. Instead we just
   * RESIZE the bottom area taller (covering the editor but leaving the side bars
   * untouched — VS Code's "maximize panel" behaviour), which is fully reversible
   * because the panel stays the bottom area, the terminal stays current, and
   * this button stays visible to toggle back.
   */
  registerToolbarItems(registry: TabBarToolbarRegistry): void {
    registry.registerItem({
      id: TOGGLE_BOTTOM_EXPAND,
      command: TOGGLE_BOTTOM_EXPAND,
      icon: 'codicon codicon-screen-full',
      tooltip: 'Toggle Panel Height (cover the editor / restore)',
      // Keep it to the bottom panel; side panels shouldn't get this.
      isVisible: (widget?: Widget) =>
        !!widget && this.shell.getAreaFor(widget) === 'bottom',
      priority: 100,
    });
  }

  registerCommands(commands: CommandRegistry): void {
    commands.registerCommand(
      { id: TOGGLE_BOTTOM_EXPAND, label: 'Toggle Bottom Panel Height' },
      { execute: () => this.toggleBottomExpand() }
    );
  }

  /**
   * Grow the bottom panel to cover most of the editor, or restore it — by
   * resizing the bottom AREA (side bars untouched). `resize` keeps the panel a
   * normal bottom dock, so unlike maximize it is always reversible and never
   * hides the explorer.
   */
  protected toggleBottomExpand(): void {
    try {
      this.shell.expandPanel('bottom'); // make sure it's visible first
    } catch {
      /* not collapsed */
    }
    const h = typeof window !== 'undefined' ? window.innerHeight : 800;
    // ~88% covers the editor and still leaves the top of the editor peeking;
    // ~33% is a comfortable default working height.
    const size = this.bottomExpanded ? Math.round(h * 0.33) : Math.round(h * 0.88);
    try {
      this.shell.resize(size, 'bottom');
      this.bottomExpanded = !this.bottomExpanded;
    } catch {
      /* resize unavailable — leave as-is */
    }
  }

  constructor() {
    this.injectHeaderStyles();
    this.injectBottomPanelStyles();
  }

  onStart(): void {
    this.injectHeaderStyles();
    this.injectBottomPanelStyles();
    this.setupViewGuard();
  }

  onDidInitializeLayout(): void {
    this.injectHeaderStyles();
    this.injectBottomPanelStyles();
    this.removeViews();
    this.setupViewGuard();
    // Layout restore can re-add a view a tick later; sweep once more. Also pin
    // bottom views that were RESTORED before our onDidAddWidget listener existed
    // (the packaged app restores Problems/Output/etc. at startup, so the add
    // event never fires for them → their × stayed). A sweep covers that.
    this.pinExistingBottomViews();
    setTimeout(() => {
      this.removeViews();
      this.pinExistingBottomViews();
    }, 0);
  }

  /** Pin every already-present bottom view (see pinBottomView). */
  private pinExistingBottomViews(): void {
    try {
      for (const widget of this.shell.widgets) {
        this.pinBottomView(widget);
      }
    } catch {
      /* defensive — never block layout init */
    }
  }

  private setupViewGuard(): void {
    if (this.shell.onDidAddWidget) {
      this.shell.onDidAddWidget((widget) => {
        if (this.isUnwantedView(widget.id, widget.title?.label)) {
          setTimeout(() => widget.close(), 0);
          return;
        }
        // Area isn't reliable synchronously on add; check next tick.
        setTimeout(() => this.pinBottomView(widget), 0);
      });
    }
  }

  /**
   * Make the fixed bottom-panel category views (Problems, Output, Debug Console,
   * …) NON-closable so they persist like VS Code / Antigravity — a close button
   * there just destroys the view, so closing the panel and reopening it drops
   * everything but the terminal. Terminals are left closable: they're individual
   * sessions, not fixed categories (the single fixed "Terminal" category is
   * Phase 3's container). Scoped to the bottom area so side panels are untouched.
   */
  private pinBottomView(widget: Widget): void {
    try {
      if (
        this.shell.getAreaFor(widget) === 'bottom' &&
        !widget.id.startsWith('terminal') &&
        widget.title.closable
      ) {
        widget.title.closable = false;
      }
    } catch {
      /* getAreaFor/title unavailable — leave as-is */
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

  /**
   * SPIKE — restyle the bottom panel's tab strip (Problems / Output / Terminal /
   * each terminal is its own tab in Theia, since Theia 1.60 has no VS Code-style
   * terminal-group view) to match the VS Code / Antigravity look the user wants:
   * flat 35px tabs, an accent top-border on the active tab, dimmed inactive text,
   * subtle hover, terminal icon + name, and a close (×) that only shows on hover
   * or for the active tab. Theia already gives most of this (active tab has an
   * inset top-accent box-shadow, and `.theia-tab-icon-label` renders the shell
   * icon); this just polishes spacing/typography/close-affordance.
   *
   * Targets `#theia-bottom-content-panel` (Theia's bottom dock) so it never leaks
   * into the left/right side bars. Same inject-once <style> pattern as the header
   * styles. Selectors verified against @theia/core sidepanel.css (Lumino `lm-`).
   */
  private injectBottomPanelStyles(): void {
    if (typeof document === 'undefined') {
      return;
    }
    const styleId = 'undisclosed-bottom-panel-style';
    if (document.getElementById(styleId)) {
      return;
    }
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = `
      /* Tab strip: flat, panel-colored, a hairline bottom border under the row
         (VS Code separates the tab strip from the content this way). */
      #theia-bottom-content-panel .lm-TabBar {
        min-height: 35px !important;
        height: 35px !important;
        background: var(--theia-panel-background, var(--theia-editor-background)) !important;
        border-bottom: 1px solid var(--theia-panel-border, rgba(128, 128, 128, 0.2)) !important;
      }

      /* Individual tabs (incl. each terminal): compact, flat, icon + name.
         Title Case — NOT uppercase (the VS Code panel tabs are Title Case). */
      #theia-bottom-content-panel .lm-TabBar-tab {
        min-height: 35px !important;
        height: 35px !important;
        padding: 0 12px !important;
        border: none !important;
        background: transparent !important;
        font-size: 11px !important;
        font-weight: 400 !important;
        letter-spacing: 0 !important;
        text-transform: none !important;
        display: flex !important;
        align-items: center !important;
        box-sizing: border-box !important;
        transition: background-color 0.1s ease, color 0.1s ease !important;
      }

      #theia-bottom-content-panel .lm-TabBar-tab .theia-tab-icon-label {
        display: inline-flex !important;
        align-items: center !important;
        gap: 6px !important;
      }

      /* Inactive tabs read dimmer; hover lifts them slightly (VS Code feel). */
      #theia-bottom-content-panel .lm-TabBar-tab:not(.lm-mod-current) {
        color: var(--theia-panelTitle-inactiveForeground, #8a8a8a) !important;
      }

      #theia-bottom-content-panel .lm-TabBar-tab:not(.lm-mod-current):hover {
        background: var(--theia-list-hoverBackground, rgba(127, 127, 127, 0.08)) !important;
        color: var(--theia-panelTitle-activeForeground, #cccccc) !important;
      }

      /* Active tab: brighter text + 2px accent TOP border (the VS Code panel
         look). Inset box-shadow draws the top rule without shifting layout. */
      #theia-bottom-content-panel .lm-TabBar-tab.lm-mod-current {
        color: var(--theia-panelTitle-activeForeground, #ffffff) !important;
        background: transparent !important;
        box-shadow: inset 0 2px 0 0 var(--theia-panelTitle-activeBorder, var(--theia-focusBorder, #007acc)) !important;
      }

      /* Badge counts (e.g. Problems' error count) — pill like VS Code. */
      #theia-bottom-content-panel .lm-TabBar-tab .theia-tab-badge,
      #theia-bottom-content-panel .lm-TabBar-tab .notification-count {
        margin-left: 6px !important;
        min-width: 16px !important;
        padding: 0 5px !important;
        border-radius: 10px !important;
        font-size: 9px !important;
        line-height: 16px !important;
        text-align: center !important;
        background: var(--theia-badge-background, #4d4d4d) !important;
        color: var(--theia-badge-foreground, #ffffff) !important;
      }

      /* Close (×): ONLY on closable tabs. Fixed category views (Problems,
         Output, Debug Console) are non-closable (lm-mod-closable absent) and get
         no × at all — closing them would destroy the view. Closable tabs (each
         terminal) show × on hover / when active. Must require .lm-mod-closable,
         else our own rule re-showed the × on the pinned views. */
      #theia-bottom-content-panel .lm-TabBar-tab:not(.lm-mod-closable) .lm-TabBar-tabCloseIcon {
        display: none !important;
      }
      #theia-bottom-content-panel .lm-TabBar-tab.lm-mod-closable .lm-TabBar-tabCloseIcon {
        opacity: 0 !important;
        transition: opacity 0.1s ease !important;
      }
      #theia-bottom-content-panel .lm-TabBar-tab.lm-mod-closable:hover .lm-TabBar-tabCloseIcon,
      #theia-bottom-content-panel .lm-TabBar-tab.lm-mod-closable.lm-mod-current .lm-TabBar-tabCloseIcon {
        opacity: 0.75 !important;
      }
      #theia-bottom-content-panel .lm-TabBar-tab.lm-mod-closable .lm-TabBar-tabCloseIcon:hover {
        opacity: 1 !important;
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
