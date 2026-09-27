// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { injectable } from '@theia/core/shared/inversify';
import { TerminalWidgetImpl } from '@theia/terminal/lib/browser/terminal-widget-impl';
import { SerializeAddon } from 'xterm-addon-serialize';

/**
 * Terminal that survives a window reload WITH its scrollback (VS Code / Antigravity
 * "--- Session restored ---" behaviour), which stock Theia does not do.
 *
 * Theia already reconnects the PTY on reload (see `TerminalWidgetImpl.restoreState`,
 * which calls `start(terminalId)`), but the previous on-screen scrollback is lost —
 * reattaching only streams NEW output. We close that gap by:
 *   1. loading xterm's `SerializeAddon` once the terminal exists (`init`),
 *   2. serialising the visible buffer into the persisted layout state (`storeState`),
 *   3. replaying it into the fresh xterm once it opens after a reload (`restoreState`).
 *
 * Everything is defensively guarded: if the addon can't load or serialise, the
 * terminal behaves exactly like a stock Theia terminal (no crash, just no
 * scrollback restore). NOTE: this only helps a WEB/renderer reload — a full
 * desktop (Electron/backend) restart kills the PTYs, so there is no live process
 * to reattach to; the saved scrollback is still shown as frozen history.
 */
@injectable()
export class PersistentTerminalWidget extends TerminalWidgetImpl {
  /** Max scrollback lines to persist — capped so layout state stays small. */
  protected static readonly MAX_SCROLLBACK = 1000;

  protected readonly serializeAddon = new SerializeAddon();
  /** Loaded lazily so a failed addon load never blocks the terminal. */
  protected serializeReady = false;

  protected ensureSerializeAddon(): void {
    if (this.serializeReady) {
      return;
    }
    try {
      // `this.term` is created by the base `init()` before this runs.
      this.term.loadAddon(this.serializeAddon);
      this.serializeReady = true;
    } catch {
      /* addon incompatible/unavailable — degrade to a normal terminal */
    }
  }

  override init(): void {
    super.init();
    this.ensureSerializeAddon();
    // VS Code / Antigravity name terminals by their PROCESS (zsh, claude, …),
    // not "Terminal N". Theia only reflects a server/program title when the
    // terminal was created with `useServerTitle` (the default `terminal:new`
    // isn't), so its `onTitleChange` handler drops them. Re-apply them here:
    // whenever the shell or a running program emits a title escape sequence,
    // show it on the tab. Combined with the initial shell name below, this
    // tracks the running process for programs that set their title.
    try {
      this.toDispose.push(
        this.term.onTitleChange((title: string) => {
          const t = (title || '').trim();
          if (t) {
            this.title.label = t;
          }
        })
      );
    } catch {
      /* xterm not ready — keep the default label */
    }
  }

  override async start(id?: number): Promise<number> {
    const result = await super.start(id);
    void this.applyProcessName();
    return result;
  }

  /**
   * Name the tab after the shell process (e.g. "zsh") instead of "Terminal N",
   * unless a server/program title has already renamed it. Theia only exposes the
   * SHELL executable (not the foreground child), so this gives the VS Code shell
   * name; a program that emits a title sequence then refines it via the
   * onTitleChange handler above. Best-effort — never throws.
   */
  protected async applyProcessName(): Promise<void> {
    try {
      const info = await this.processInfo;
      const exe = (info?.executable || '').split(/[/\\]/).pop();
      // Only override while it's still the stock "Terminal[ N]" label, so we
      // never clobber a real title the program already set.
      if (exe && /^Terminal\b/i.test(this.title.label)) {
        this.title.label = exe;
      }
    } catch {
      /* processInfo unavailable — leave the default label */
    }
  }

  override storeState(): object {
    const base = super.storeState() as { terminalId?: number } & object;
    // Base returns {} for transient / pseudo terminals — nothing to restore.
    if (!base || typeof (base as { terminalId?: number }).terminalId !== 'number') {
      return base;
    }
    try {
      this.ensureSerializeAddon();
      if (this.serializeReady) {
        const savedScrollback = this.serializeAddon.serialize({
          scrollback: PersistentTerminalWidget.MAX_SCROLLBACK,
        });
        return { ...base, savedScrollback };
      }
    } catch {
      /* serialize failed — persist without scrollback */
    }
    return base;
  }

  override restoreState(oldState: object): void {
    // Base reattaches to the surviving PTY (or disposes transient terminals).
    super.restoreState(oldState);
    const saved = (oldState as { savedScrollback?: string })?.savedScrollback;
    if (!saved) {
      return;
    }
    // Replay the saved buffer once the fresh xterm has opened; writing before
    // then is dropped. One-shot so a later reconnect doesn't re-dump history.
    const sub = this.onDidOpen(() => {
      sub.dispose();
      try {
        this.term.write(saved);
        this.term.write(
          '\r\n\x1b[38;5;242m─── Session restored ───\x1b[0m\r\n'
        );
      } catch {
        /* write failed — leave the live terminal as-is */
      }
    });
    this.toDispose.push(sub);
  }
}
