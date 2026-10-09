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
    this.injectActivityBarStyles();
    this.injectBottomPanelStyles();
    this.injectExtensionsListStyles();
  }

  onStart(): void {
    this.injectHeaderStyles();
    this.injectActivityBarStyles();
    this.injectBottomPanelStyles();
    this.injectExtensionsListStyles();
    this.setupViewGuard();
  }

  onDidInitializeLayout(): void {
    this.injectHeaderStyles();
    this.injectActivityBarStyles();
    this.injectBottomPanelStyles();
    this.injectExtensionsListStyles();
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
        /* Keep the panel's original font (the UI sans stack); no mono override.
           Spec Section 1 suggested font-mono, but the user asked to keep the
           font the agent panel already had. */
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
  /**
   * Restyle the left activity bar to match the Antigravity reference: brighter
   * icons, a subtle rounded highlight behind the hovered/active item, and a left
   * accent bar + full-strength icon on the active view. Theia's default active
   * state was near-invisible (icons at ~40% opacity, no highlight), so it was
   * hard to tell which side view was open. Uses VS Code activityBar theme vars
   * (with fallbacks) so it follows light/dark and custom themes.
   */
  private injectActivityBarStyles(): void {
    if (typeof document === 'undefined') {
      return;
    }
    const styleId = 'undisclosed-activity-bar-style';
    if (document.getElementById(styleId)) {
      return;
    }
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = `
      /* Each activity-bar item is a positioned box so we can draw a centered
         highlight pill (::before) and a left accent bar (::after) behind the
         icon without affecting layout. */
      .theia-app-left .lm-TabBar-tab {
        position: relative !important;
      }

      /* Icons: a touch larger and readable when inactive. We drive brightness
         with opacity on the theme FOREGROUND (not the theme's
         inactiveForeground, which some themes set as low as 40% — too dim vs the
         Antigravity reference), so inactive reads at a comfortable 62% and stays
         correct in light themes too. 18px is the single source of truth for
         EVERY icon in the rail (see the plugin + bottom-menu rules below). */
      .theia-app-left .lm-TabBar-tab .lm-TabBar-tabIcon.codicon {
        font-size: 18px !important;
        color: var(--theia-activityBar-foreground, #ffffff) !important;
        opacity: 0.62 !important;
        transition: opacity 0.12s ease !important;
        position: relative !important;
        z-index: 1 !important;
      }
      .theia-app-left .lm-TabBar-tab:hover .lm-TabBar-tabIcon.codicon {
        opacity: 0.85 !important;
      }

      /* Extension/plugin-contributed view icons default to ~24px — larger than
         the built-in codicons, which made the rail look ragged. Normalize them
         to the same 18px, covering font-, mask-, and background-image glyphs. */
      .theia-app-left .lm-TabBar-tab .lm-TabBar-tabIcon.theia-plugin-view-container {
        font-size: 18px !important;
        -webkit-mask-size: 18px 18px !important;
        mask-size: 18px 18px !important;
        background-size: 18px 18px !important;
        opacity: 0.62 !important;
        transition: opacity 0.12s ease !important;
        position: relative !important;
        z-index: 1 !important;
      }
      .theia-app-left .lm-TabBar-tab:hover .lm-TabBar-tabIcon.theia-plugin-view-container {
        opacity: 0.85 !important;
      }
      .theia-app-left .lm-TabBar-tab.lm-mod-current .lm-TabBar-tabIcon.theia-plugin-view-container {
        opacity: 1 !important;
      }

      /* Bottom sidebar menu (Settings gear, overflow "…", Accounts) also renders
         at ~24px — bring it in line with the rail size + inactive brightness so
         the whole left column is consistent. */
      .theia-sidebar-menu .theia-sidebar-menu-item .codicon {
        font-size: 18px !important;
        color: var(--theia-activityBar-foreground, #ffffff) !important;
        opacity: 0.62 !important;
        transition: opacity 0.12s ease !important;
      }
      .theia-sidebar-menu .theia-sidebar-menu-item:hover .codicon {
        opacity: 0.9 !important;
      }

      /* Centered rounded highlight — appears on hover and (stronger) when the
         view is open. */
      .theia-app-left .lm-TabBar-tab::before {
        content: '';
        position: absolute;
        left: 50%;
        top: 50%;
        width: 34px;
        height: 34px;
        transform: translate(-50%, -50%);
        border-radius: 10px;
        background: transparent;
        transition: background-color 0.12s ease;
        pointer-events: none;
      }
      .theia-app-left .lm-TabBar-tab:hover::before {
        background: var(--theia-activityBar-activeBackground, rgba(255, 255, 255, 0.08)) !important;
      }
      .theia-app-left .lm-TabBar-tab.lm-mod-current::before {
        background: var(--theia-activityBar-activeBackground, rgba(255, 255, 255, 0.13)) !important;
      }

      /* Active view: full-strength icon + a 2px left accent bar (the VS Code /
         Antigravity activity-bar active indicator). */
      .theia-app-left .lm-TabBar-tab.lm-mod-current .lm-TabBar-tabIcon.codicon {
        color: var(--theia-activityBar-foreground, #ffffff) !important;
        opacity: 1 !important;
      }
      .theia-app-left .lm-TabBar-tab.lm-mod-current::after {
        content: '';
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        width: 2px;
        height: 24px;
        border-radius: 0 2px 2px 0;
        background: var(--theia-activityBar-activeBorder, var(--theia-focusBorder, #4c8bf5));
      }

      /* Activity-bar items are view toggles, not documents — never show a × on
         them (Theia marks them closable, which would otherwise reveal one). */
      .theia-app-left .lm-TabBar-tab .lm-TabBar-tabCloseIcon {
        display: none !important;
      }
    `;
    document.head.appendChild(style);
  }

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
        color: var(--theia-panelTitle-inactiveForeground, rgba(255, 255, 255, 0.55)) !important;
      }

      #theia-bottom-content-panel .lm-TabBar-tab:not(.lm-mod-current):hover {
        background: var(--theia-list-hoverBackground, rgba(127, 127, 127, 0.08)) !important;
        color: var(--theia-panelTitle-activeForeground, #e6e6e6) !important;
      }

      /* Active tab: reads as a clearly SELECTED tab — a subtle raised fill (the
         content/editor background, so it visually connects to the panel body
         below), full-strength + slightly heavier text, and a 2px accent top
         border. Inset box-shadow draws the top rule without shifting layout. */
      #theia-bottom-content-panel .lm-TabBar-tab.lm-mod-current {
        color: var(--theia-panelTitle-activeForeground, #ffffff) !important;
        font-weight: 600 !important;
        background: var(--theia-editor-background, rgba(255, 255, 255, 0.05)) !important;
        box-shadow: inset 0 2px 0 0 var(--theia-panelTitle-activeBorder, var(--theia-focusBorder, #4c8bf5)) !important;
      }

      /* Active tab's icon also brightens (Problems' warning icon, terminal glyph,
         etc.), so the whole tab reads active — not just its label. */
      #theia-bottom-content-panel .lm-TabBar-tab.lm-mod-current .lm-TabBar-tabIcon,
      #theia-bottom-content-panel .lm-TabBar-tab.lm-mod-current .theia-tab-icon-label {
        color: var(--theia-panelTitle-activeForeground, #ffffff) !important;
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

  /**
   * Keep each VSX extension row's Install/Uninstall action on-screen when the
   * publisher name is long (e.g. Cherry Markdown).
   *
   * A row's action bar (@theia/vsx-registry) is a flex row with
   * `justify-content: space-between`:
   *   [verified icon + publisher name]  ...  [action button(s)]
   * The publisher span carries `.noWrapInfo` (which does ellipsize), but as a
   * flex item it keeps the default `min-width: auto`, so its min-content width
   * is the full, unbreakable publisher name. That inflates the publisher cell
   * and `space-between` pushes the Install button past the right edge, so it
   * only reappears once the panel is widened. Let the publisher cell shrink and
   * ellipsize, and pin the action(s) so the NAME truncates instead of the
   * button disappearing. (The package `style/` file is not loaded by Theia
   * 1.60, so this lives here with the other injected shell styles.)
   */
  private injectExtensionsListStyles(): void {
    if (typeof document === 'undefined') {
      return;
    }
    const styleId = 'undisclosed-extensions-list-style';
    if (document.getElementById(styleId)) {
      return;
    }
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = `
      .theia-vsx-extension-action-bar .theia-vsx-extension-publisher-container {
        flex: 1 1 auto !important;
        min-width: 0 !important;
        overflow: hidden !important;
      }
      .theia-vsx-extension-action-bar .theia-vsx-extension-publisher-container .codicon {
        flex: 0 0 auto !important;
      }
      .theia-vsx-extension-action-bar .theia-vsx-extension-publisher {
        flex: 1 1 auto !important;
        min-width: 0 !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
      }
      .theia-vsx-extension-action-bar .action {
        flex-shrink: 0 !important;
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
