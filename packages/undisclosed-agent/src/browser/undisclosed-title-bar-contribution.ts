// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Custom macOS title bar.
//
// Why this exists: macOS 26 "Tahoe" left-aligns the OS window title by default
// (there is no AppKit switch to re-center it). Theia only ever uses the NATIVE
// macOS title bar — its centered `CustomTitleWidget` path is gated to
// Windows/Linux (see `ElectronMenuContribution.getTitleBarStyle` and
// `FrontendConfigProvider`), and the Electron main hard-returns `native` on OSX.
// So on Tahoe our title ("research.md - eigent-theia") drifted to the far left,
// right of the traffic lights.
//
// We can't re-center the stock title, so we replace the CONTENT of the title bar
// area while keeping the native traffic lights:
//   1. The Electron window is created with `titleBarStyle: "hiddenInset"`
//      (`apps/desktop/package.json` -> theia.frontend.config.electron.windowOptions).
//      That keeps the native close/min/max "traffic lights" but hides the native
//      title TEXT and makes the whole bar part of the web content.
//   2. This contribution paints a drag-region strip across the top with the title
//      re-centered, and pushes the Theia shell down by the strip height so the
//      activity bar / editor never sit under the traffic lights.
//
// Gated to Electron + macOS: on Windows/Linux Theia already draws its own
// centered custom title bar (with its own window controls), and in the browser
// there is no OS chrome to replace.

import { inject, injectable } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser';
import { isOSX } from '@theia/core/lib/common/os';
import { WindowTitleService } from '@theia/core/lib/browser/window/window-title-service';

/** DOM id of the strip, also used to detect a stale bar across reloads. */
const TITLEBAR_ID = 'undisclosed-titlebar';
/** DOM id of the injected stylesheet (injected at most once). */
const STYLE_ID = 'undisclosed-titlebar-style';
/**
 * Strip height in px. Kept equal to the native macOS title bar height (~28px) so
 * Electron's default `hiddenInset` traffic-light position lines up exactly. If
 * you want a taller bar, bump this AND set an explicit `trafficLightPosition` in
 * the window options to re-center the lights.
 */
const TITLEBAR_HEIGHT = 36;

@injectable()
export class UndisclosedTitleBarContribution
  implements FrontendApplicationContribution
{
  @inject(WindowTitleService)
  protected readonly windowTitleService!: WindowTitleService;

  onStart(): void {
    if (!this.isElectronMac()) {
      return;
    }
    this.injectStyles();
    const label = this.createBar();
    // Keep the strip in sync with the editor/folder title ("file - workspace").
    this.windowTitleService.onDidChangeTitle((title) => {
      label.textContent = title || this.fallbackTitle();
    });
  }

  protected isElectronMac(): boolean {
    if (!isOSX || typeof window === 'undefined') {
      return false;
    }
    // Theia opens "secondary windows" (moved editors) as separate documents
    // (`secondary-window.html`) backed by ordinary FRAMED windows with their own
    // native title bar. Skip them so we don't stack a second strip on top.
    if (window.location.pathname.endsWith('secondary-window.html')) {
      return false;
    }
    return !!(window as unknown as { electronTheiaCore?: unknown })
      .electronTheiaCore;
  }

  protected fallbackTitle(): string {
    return document.title || '';
  }

  protected createBar(): HTMLElement {
    // Drop any bar left over from a previous render (e.g. hot reload / reload).
    document.getElementById(TITLEBAR_ID)?.remove();

    const bar = document.createElement('div');
    bar.id = TITLEBAR_ID;
    bar.setAttribute('role', 'banner');

    // Equal left/right spacers keep the label centered in the WINDOW (not just
    // in the leftover space) and stop it sliding under the traffic lights.
    const left = document.createElement('div');
    left.className = 'undisclosed-titlebar-spacer';

    const label = document.createElement('div');
    label.className = 'undisclosed-titlebar-label';
    label.textContent = this.windowTitleService.title || this.fallbackTitle();

    const right = document.createElement('div');
    right.className = 'undisclosed-titlebar-spacer';

    bar.append(left, label, right);
    document.body.appendChild(bar);
    document.documentElement.classList.add('undisclosed-custom-titlebar');
    return label;
  }

  protected injectStyles(): void {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) {
      return;
    }
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      :root {
        --undisclosed-titlebar-height: ${TITLEBAR_HEIGHT}px;
      }

      #${TITLEBAR_ID} {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        height: var(--undisclosed-titlebar-height);
        z-index: 4000;
        display: flex;
        align-items: center;
        box-sizing: border-box;
        /* Whole strip drags the window, like the native title bar. */
        -webkit-app-region: drag;
        -webkit-user-select: none;
        user-select: none;
        /* Dark glassy look: a translucent wash of the activity-bar (left rail)
           colour, blurred so whatever sits behind reads through. The first
           background is the opaque fallback for engines without color-mix;
           the second overrides it with an alpha-blended, theme-aware tint. */
        background: var(--theia-activityBar-background, #1e1e1e);
        background: color-mix(in srgb,
          var(--theia-activityBar-background, #1e1e1e) 70%, transparent);
        -webkit-backdrop-filter: saturate(180%) blur(24px);
        backdrop-filter: saturate(180%) blur(24px);
        color: var(--theia-titleBar-activeForeground, var(--theia-foreground, #cccccc));
        /* border-bottom: 1px solid var(--theia-titleBar-border,
           var(--theia-panel-border, rgba(128, 128, 128, 0.35))); */
        /* Faint top highlight: reads as a light "glass" edge in both themes. */
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
        font-family: var(--theia-ui-font-family);
        font-size: var(--theia-ui-font-size1, 13px);
        line-height: 1;
      }

      #${TITLEBAR_ID} .undisclosed-titlebar-spacer {
        flex: 0 0 auto;
        width: 78px;
      }

      #${TITLEBAR_ID} .undisclosed-titlebar-label {
        flex: 1 1 auto;
        min-width: 0;
        padding: 0 8px;
        text-align: center;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      /* Reserve the strip at the top of the shell so the activity bar + editor
         start BELOW the native traffic lights instead of under them. */
      html.undisclosed-custom-titlebar .theia-ApplicationShell {
        top: var(--undisclosed-titlebar-height) !important;
        height: auto !important;
      }
    `;
    document.head.appendChild(style);
  }
}
