// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Branded welcome shown in the main editor area when NO workspace is open — the
// editor was otherwise plain black in that state. Offers the one thing the user
// actually needs (open a folder) plus recents, styled with Theia theme vars so
// it fits light/dark.

import * as React from '@theia/core/shared/react';
import {
  inject,
  injectable,
  postConstruct,
} from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { CommandService } from '@theia/core/lib/common';
import { WorkspaceCommands } from '@theia/workspace/lib/browser/workspace-commands';

@injectable()
export class UndisclosedWelcomeWidget extends ReactWidget {
  static readonly ID = 'undisclosed.welcome';
  static readonly LABEL = 'Welcome';

  @inject(CommandService)
  protected readonly commands!: CommandService;

  @postConstruct()
  protected init(): void {
    this.id = UndisclosedWelcomeWidget.ID;
    this.title.label = UndisclosedWelcomeWidget.LABEL;
    this.title.caption = UndisclosedWelcomeWidget.LABEL;
    this.title.iconClass = 'codicon codicon-home';
    this.title.closable = true;
    this.addClass('undisclosed-welcome');
    this.update();
  }

  protected run(commandId: string): void {
    void this.commands.executeCommand(commandId);
  }

  protected render(): React.ReactNode {
    const wrap: React.CSSProperties = {
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '10px',
      padding: '32px',
      textAlign: 'center',
      color: 'var(--theia-foreground)',
      background: 'var(--theia-editor-background)',
      userSelect: 'none',
    };
    const title: React.CSSProperties = {
      margin: 0,
      fontSize: '28px',
      fontWeight: 700,
      letterSpacing: '0.5px',
    };
    const sub: React.CSSProperties = {
      margin: '0 0 12px',
      fontSize: '13px',
      opacity: 0.7,
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
    const hint: React.CSSProperties = {
      marginTop: '14px',
      fontSize: '12px',
      opacity: 0.55,
    };

    // The real brand mark (matches apps/desktop/build/icon.svg, the dock/DMG
    // icon): three white "redaction bars" of descending width on the dark
    // gradient squircle. Self-contained so it reads as the logo in any theme.
    const logo = (
      <svg
        width="72"
        height="72"
        viewBox="0 0 1024 1024"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Undisclosed"
        style={{ marginBottom: '10px' }}
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

    return (
      <div style={wrap}>
        {logo}
        <h1 style={title}>Undisclosed</h1>
        <p style={sub}>
          Your on-device AI editor. Open a folder to start editing — the agent
          panel on the right is ready whenever you need it.
        </p>
        <div style={row}>
          <button
            style={primaryBtn}
            onClick={() => this.run(WorkspaceCommands.OPEN_WORKSPACE.id)}
          >
            Open Folder…
          </button>
          <button
            style={secondaryBtn}
            onClick={() => this.run(WorkspaceCommands.OPEN_RECENT_WORKSPACE.id)}
          >
            Open Recent…
          </button>
        </div>
        <div style={hint}>Tip: press ⌘⇧A to chat with the agent.</div>
      </div>
    );
  }
}
