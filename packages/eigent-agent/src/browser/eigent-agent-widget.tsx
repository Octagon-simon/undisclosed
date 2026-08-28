// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import * as React from '@theia/core/shared/react';
import { injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';

/**
 * Native Theia panel for Eigent's agent, docked in the right side panel.
 *
 * This is the *proof* that Eigent's own UI can be a first-class Theia view (not
 * an external dock beside an iframe — the code-server problem). For now it
 * renders a placeholder; later it hosts the decoupled Eigent agent UI (chat,
 * governance, history) driven by the Eigent backend over REST/SSE.
 */
@injectable()
export class EigentAgentWidget extends ReactWidget {
  static readonly ID = 'eigent-agent-widget';
  static readonly LABEL = 'Eigent Agent';

  @postConstruct()
  protected init(): void {
    this.id = EigentAgentWidget.ID;
    this.title.label = EigentAgentWidget.LABEL;
    this.title.caption = EigentAgentWidget.LABEL;
    // Codicon shipped with Theia; robot/agent glyph.
    this.title.iconClass = 'codicon codicon-hubot';
    this.title.closable = true;
    this.node.tabIndex = 0;
    this.addClass('eigent-agent-widget');
    this.update();
  }

  protected render(): React.ReactNode {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          minHeight: 0,
          fontFamily: 'var(--theia-ui-font-family)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 12px',
            borderBottom: '1px solid var(--theia-panel-border)',
          }}
        >
          <span
            className="codicon codicon-hubot"
            style={{ color: 'var(--theia-icon-foreground)' }}
          />
          <span style={{ fontWeight: 600, fontSize: 13 }}>Eigent Agent</span>
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 11,
              opacity: 0.7,
              border: '1px solid var(--theia-panel-border)',
              borderRadius: 10,
              padding: '1px 8px',
            }}
          >
            Native panel ✓
          </span>
        </div>

        {/* Body */}
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 12 }}>
          <p style={{ fontSize: 13, lineHeight: 1.5, margin: '0 0 12px' }}>
            This panel is a first-class Theia view contributed by the{' '}
            <code>eigent-agent</code> extension — rendered with React, native to
            the editor. No competing built-in chat, no iframe-beside-iframe.
          </p>
          <p style={{ fontSize: 12, opacity: 0.7, margin: 0 }}>
            Next: host Eigent's decoupled agent UI here (chat, governance,
            history), driven by the Eigent backend over REST/SSE.
          </p>
        </div>

        {/* Composer placeholder */}
        <div
          style={{
            borderTop: '1px solid var(--theia-panel-border)',
            padding: 10,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              border: '1px solid var(--theia-input-border, var(--theia-panel-border))',
              borderRadius: 8,
              padding: '8px 10px',
              opacity: 0.6,
              fontSize: 12,
            }}
          >
            <span className="codicon codicon-sparkle" />
            <span>Ask the agent…</span>
          </div>
        </div>
      </div>
    );
  }
}
