// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Branded empty-editor state: shown in the main area whenever there is no
// editor open (fresh launch or every tab closed). Leads with the brand mark
// and keeps the useful actions + keyboard shortcuts at the bottom.

// Theia 1.76's `@theia/core/shared/react` is a CommonJS `export =` module, so
// it must be default-imported (a namespace import fails with TS2497).
import React from '@theia/core/shared/react';
import {
  inject,
  injectable,
  postConstruct,
} from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { CommandService } from '@theia/core/lib/common';
import { WorkspaceCommands } from '@theia/workspace/lib/browser/workspace-commands';
import { WorkspaceService } from '@theia/workspace/lib/browser';

const isMac = (): boolean =>
  typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent);

interface Shortcut {
  label: string;
  keys: string;
  commandId: string;
}

@injectable()
export class UndisclosedWelcomeWidget extends ReactWidget {
  static readonly ID = 'undisclosed.welcome';
  static readonly LABEL = 'Welcome';

  @inject(CommandService)
  protected readonly commands!: CommandService;

  @inject(WorkspaceService)
  protected readonly workspaceService!: WorkspaceService;

  @postConstruct()
  protected init(): void {
    this.id = UndisclosedWelcomeWidget.ID;
    this.title.label = UndisclosedWelcomeWidget.LABEL;
    this.title.caption = UndisclosedWelcomeWidget.LABEL;
    this.title.iconClass = 'codicon codicon-home';
    this.title.closable = false;
    this.addClass('undisclosed-welcome');
    this.update();
  }

  protected run(commandId: string): void {
    void this.commands.executeCommand(commandId);
  }

  protected getShortcuts(): Shortcut[] {
    const mod = isMac() ? '⌘' : 'Ctrl';
    const modShift = isMac() ? '⌘⇧' : 'Ctrl+Shift';
    return [
      {
        label: 'Chat with Undisclosed',
        keys: `${modShift}A`,
        commandId: 'undisclosed-agent.open',
      },
      {
        label: 'Command palette',
        keys: `${modShift}P`,
        commandId: 'workbench.action.showCommands',
      },
      {
        label: 'Go to file',
        keys: `${mod}P`,
        commandId: 'file-search.openFile',
      },
      {
        label: 'Toggle terminal',
        keys: isMac() ? '⌃`' : 'Ctrl+`',
        commandId: 'workbench.action.terminal.toggleTerminal',
      },
    ];
  }

  protected render(): React.ReactNode {
    const wrap: React.CSSProperties = {
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      color: 'var(--theia-foreground)',
      background: 'var(--theia-editor-background)',
      userSelect: 'none',
    };
    const center: React.CSSProperties = {
      flex: 1,
      minHeight: 0,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '10px',
      padding: '32px',
      textAlign: 'center',
    };
    const title: React.CSSProperties = {
      margin: 0,
      fontSize: '26px',
      fontWeight: 700,
      letterSpacing: '0.2px',
    };
    const sub: React.CSSProperties = {
      margin: '2px 0 12px',
      fontSize: '13px',
      opacity: 0.65,
      maxWidth: '420px',
      lineHeight: 1.5,
    };
    const row: React.CSSProperties = { display: 'flex', gap: '10px' };
    const primaryBtn: React.CSSProperties = {
      padding: '8px 18px',
      fontSize: '13px',
      fontWeight: 600,
      borderRadius: '6px',
      border: 'none',
      cursor: 'pointer',
      color: 'var(--theia-button-foreground)',
      background: 'var(--theia-button-background)',
    };
    const secondaryBtn: React.CSSProperties = {
      ...primaryBtn,
      color: 'var(--theia-button-secondaryForeground, var(--theia-foreground))',
      background:
        'var(--theia-button-secondaryBackground, var(--theia-editorWidget-background, rgba(127,127,127,0.14)))',
    };
    const footer: React.CSSProperties = {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '4px 6px',
      padding: '12px 24px 20px',
      borderTop:
        '1px solid var(--theia-editorWidget-border, rgba(127,127,127,0.16))',
    };
    const shortcutBtn: React.CSSProperties = {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '7px',
      padding: '5px 9px',
      border: 'none',
      borderRadius: '6px',
      background: 'transparent',
      color: 'inherit',
      font: 'inherit',
      fontSize: '12px',
      opacity: 0.78,
      cursor: 'pointer',
    };
    const kbd: React.CSSProperties = {
      fontFamily:
        'var(--theia-code-font-family, ui-monospace, SFMono-Regular, Menlo, monospace)',
      fontSize: '11px',
      lineHeight: 1,
      padding: '4px 6px',
      borderRadius: '4px',
      border: '1px solid var(--theia-input-border, rgba(127,127,127,0.28))',
      background:
        'var(--theia-input-background, rgba(127,127,127,0.10))',
      whiteSpace: 'nowrap',
    };

    // The real brand mark (matches apps/desktop/build/icon.svg, the dock/DMG
    // icon): three white "redaction bars" of descending width on the dark
    // gradient squircle. Self-contained so it reads as the logo in any theme.
    const logo = (
      <svg
        width="84"
        height="84"
        viewBox="0 0 1024 1024"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Undisclosed"
        style={{ marginBottom: '8px' }}
      >
        <defs>
          <linearGradient id="undisclosed-welcome-bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#2b2b30" />
            <stop offset="1" stopColor="#121214" />
          </linearGradient>
        </defs>
        <rect
          x="64"
          y="64"
          width="896"
          height="896"
          rx="200"
          fill="url(#undisclosed-welcome-bg)"
        />
        <g transform="translate(192,192) scale(13.3333)" fill="#ffffff">
          <rect x="7" y="13" width="34" height="6.4" rx="3.2" />
          <rect x="7" y="24" width="25" height="6.4" rx="3.2" opacity="0.82" />
          <rect x="7" y="35" width="16" height="6.4" rx="3.2" opacity="0.64" />
        </g>
      </svg>
    );

    const workspaceOpened = this.workspaceService.opened;

    return (
      <div style={wrap}>
        <div style={center}>
          {logo}
          <h1 style={title}>Undisclosed</h1>
          <p style={sub}>
            {workspaceOpened
              ? 'Open a file to start editing, or ask the agent to do it for you.'
              : 'Your on-device AI editor. Open a folder to get started.'}
          </p>
          {!workspaceOpened && (
            <div style={row}>
              <button
                style={primaryBtn}
                onClick={() => this.run(WorkspaceCommands.OPEN_FOLDER.id)}
              >
                Open Folder…
              </button>
              <button
                style={secondaryBtn}
                onClick={() =>
                  this.run(WorkspaceCommands.OPEN_RECENT_WORKSPACE.id)
                }
              >
                Open Recent…
              </button>
            </div>
          )}
        </div>
        <div style={footer}>
          {this.getShortcuts().map((shortcut) => (
            <button
              key={shortcut.commandId}
              type="button"
              style={shortcutBtn}
              onClick={() => this.run(shortcut.commandId)}
              title={`${shortcut.label} (${shortcut.keys})`}
            >
              <span>{shortcut.label}</span>
              <kbd style={kbd}>{shortcut.keys}</kbd>
            </button>
          ))}
        </div>
      </div>
    );
  }
}
