// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

// Main-process half of the "agent needs attention" alert.
//
// The renderer tells us when a blocking prompt (an agent question or a tool
// approval) appears and when it is answered. If the window is not focused at
// that moment we bounce the Dock icon (macOS), flash the taskbar entry
// (Windows/Linux) and post one native notification. Everything stops as soon as
// the user comes back or the prompt is resolved.
//
// Focus is decided HERE, not in the renderer: BrowserWindow.isFocused() is
// authoritative even when the window is occluded, minimised or the whole app is
// hidden with Cmd+H, where document.hasFocus() is not.

import { injectable } from '@theia/core/shared/inversify';
import {
  ElectronMainApplication,
  ElectronMainApplicationContribution,
} from '@theia/core/lib/electron-main/electron-main-application';
import {
  ATTENTION_CLEAR_CHANNEL,
  ATTENTION_REQUEST_CHANNEL,
  AgentAttentionRequest,
  sanitizeAttentionId,
  sanitizeAttentionRequest,
} from '../electron-common/attention';

interface AttentionWindow {
  isDestroyed(): boolean;
  isFocused(): boolean;
  isMinimized(): boolean;
  show(): void;
  restore(): void;
  focus(): void;
  flashFrame(flag: boolean): void;
}

interface AttentionNotification {
  on(event: 'click' | 'close', handler: () => void): void;
  show(): void;
  close(): void;
}

interface AttentionElectron {
  app: {
    isHidden(): boolean;
    focus(options?: { steal?: boolean }): void;
    on(event: 'browser-window-focus' | 'activate', handler: () => void): void;
    dock?: {
      bounce(type: 'critical' | 'informational'): number;
      cancelBounce(id: number): void;
    };
  };
  ipcMain: {
    on(
      channel: string,
      listener: (event: { sender: unknown }, ...args: unknown[]) => void
    ): void;
  };
  BrowserWindow: {
    fromWebContents(contents: unknown): AttentionWindow | null;
    getAllWindows(): AttentionWindow[];
  };
  Notification: {
    new (options: {
      title: string;
      body: string;
      silent?: boolean;
    }): AttentionNotification;
    isSupported(): boolean;
  };
}

/** Bounce id per unresolved prompt; `has(id)` doubles as the dedupe set. */
type PendingPrompts = Map<string, number>;

@injectable()
export class AgentAttentionContribution
  implements ElectronMainApplicationContribution
{
  private electron: AttentionElectron | undefined;
  private readonly pending: PendingPrompts = new Map();
  private notification: AttentionNotification | undefined;

  onStart(_application: ElectronMainApplication): void {
    const electron = require('electron') as AttentionElectron;
    this.electron = electron;
    electron.ipcMain.on(ATTENTION_REQUEST_CHANNEL, (event, raw) =>
      this.handleRequest(event.sender, raw)
    );
    electron.ipcMain.on(ATTENTION_CLEAR_CHANNEL, (_event, raw) =>
      this.handleClear(raw)
    );
    // Any way back into the app retires the current alert.
    electron.app.on('browser-window-focus', () => this.retireAll());
    electron.app.on('activate', () => this.retireAll());
  }

  private handleRequest(sender: unknown, raw: unknown): void {
    const request = sanitizeAttentionRequest(raw);
    const electron = this.electron;
    if (!request || !electron) {
      return;
    }
    const window =
      electron.BrowserWindow.fromWebContents(sender) ??
      electron.BrowserWindow.getAllWindows()[0];
    if (!window || window.isDestroyed()) {
      return;
    }
    // The user is looking at the app already; nothing to interrupt them with.
    if (window.isFocused() && !electron.app.isHidden()) {
      return;
    }
    if (this.pending.has(request.id)) {
      return; // same prompt reported twice (re-render, duplicate SSE frame)
    }

    if (process.platform === 'darwin' && electron.app.dock) {
      // 'critical' keeps bouncing until the app is activated, which is what a
      // blocked run warrants; 'informational' bounces once and is easy to miss.
      this.pending.set(request.id, electron.app.dock.bounce('critical'));
    } else {
      this.pending.set(request.id, 0);
      window.flashFrame(true);
    }
    this.showNotification(electron, window, request);
  }

  private handleClear(raw: unknown): void {
    const id = sanitizeAttentionId(raw);
    if (id) {
      this.cancel(id);
    }
  }

  private showNotification(
    electron: AttentionElectron,
    window: AttentionWindow,
    request: AgentAttentionRequest
  ): void {
    const { Notification } = electron;
    if (typeof Notification?.isSupported === 'function' && !Notification.isSupported()) {
      return;
    }
    // One banner at a time: a burst of prompts must not stack up.
    this.notification?.close();
    let notification: AttentionNotification;
    try {
      notification = new Notification({
        title: request.title,
        body: request.body,
        silent: false,
      });
    } catch (_error) {
      return; // notifications unavailable (unsigned dev build, permissions)
    }
    notification.on('close', () => {
      if (this.notification === notification) {
        this.notification = undefined;
      }
    });
    notification.on('click', () => {
      if (window.isDestroyed()) {
        return;
      }
      if (window.isMinimized()) {
        window.restore();
      }
      window.show();
      window.focus();
      if (process.platform === 'darwin') {
        electron.app.focus({ steal: true });
      }
      this.retireAll();
    });
    this.notification = notification;
    notification.show();
  }

  /** Drop one prompt: stop its bounce, and stop flashing once none are left. */
  private cancel(id: string): void {
    const bounceId = this.pending.get(id);
    if (bounceId === undefined) {
      return;
    }
    this.pending.delete(id);
    this.cancelBounce(bounceId);
    if (this.pending.size === 0) {
      this.stopFlashing();
    }
  }

  /** The user is back: retire every pending alert at once. */
  private retireAll(): void {
    for (const bounceId of this.pending.values()) {
      this.cancelBounce(bounceId);
    }
    this.pending.clear();
    this.stopFlashing();
    this.notification?.close();
    this.notification = undefined;
  }

  private cancelBounce(bounceId: number): void {
    const dock = this.electron?.app.dock;
    if (bounceId > 0 && dock) {
      dock.cancelBounce(bounceId);
    }
  }

  private stopFlashing(): void {
    const windows = this.electron?.BrowserWindow.getAllWindows() ?? [];
    for (const window of windows) {
      if (!window.isDestroyed()) {
        window.flashFrame(false);
      }
    }
  }
}
