// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { injectable, postConstruct } from '@theia/core/shared/inversify';
import { BaseWidget, Message } from '@theia/core/lib/browser';

/** Signature exposed by the prebuilt agent bundle (Eigent's mountAgentPanel). */
type MountFn = (
  element: HTMLElement,
  config: {
    baseUrl: string;
    token?: string | null;
    userId?: number | null;
  }
) => () => void;

const BUNDLE_JS = '/eigent-agent/agent-embed.umd.js';
const BUNDLE_CSS = '/eigent-agent/style.css';
const GLOBAL = 'EigentAgentEmbed';

// TODO: injected session hand-off. Local Brain renders + streams without a
// cloud token; cloud features (model routing, history sync) need one.
const BRAIN_BASE_URL = 'http://localhost:5001';

/** Load the self-contained agent bundle once (CSS + UMD script), resolve to its
 *  `mountAgentPanel`. Shared across widget instances. */
let bundlePromise: Promise<MountFn> | undefined;
function loadAgentBundle(): Promise<MountFn> {
  if (bundlePromise) return bundlePromise;
  bundlePromise = new Promise<MountFn>((resolve, reject) => {
    if (!document.getElementById('eigent-agent-css')) {
      const link = document.createElement('link');
      link.id = 'eigent-agent-css';
      link.rel = 'stylesheet';
      link.href = BUNDLE_CSS;
      document.head.appendChild(link);
    }
    const existing = (window as unknown as Record<string, { mountAgentPanel?: MountFn }>)[GLOBAL];
    if (existing?.mountAgentPanel) {
      resolve(existing.mountAgentPanel);
      return;
    }
    const script = document.createElement('script');
    script.src = BUNDLE_JS;
    script.async = true;
    script.onload = () => {
      const mod = (window as unknown as Record<string, { mountAgentPanel?: MountFn }>)[GLOBAL];
      if (mod?.mountAgentPanel) resolve(mod.mountAgentPanel);
      else reject(new Error(`${GLOBAL}.mountAgentPanel missing after load`));
    };
    script.onerror = () => reject(new Error('failed to load agent-embed bundle'));
    document.body.appendChild(script);
  });
  return bundlePromise;
}

/**
 * Right-dock host for Eigent's real agent UI. This widget is just a native
 * Theia container + lifecycle; the actual chat/governance/history UI is the
 * prebuilt Eigent bundle mounted into its node via `mountAgentPanel`. One DOM,
 * one window — no iframe.
 */
@injectable()
export class EigentAgentWidget extends BaseWidget {
  static readonly ID = 'eigent-agent-widget';
  static readonly LABEL = 'Eigent Agent';

  protected host!: HTMLDivElement;
  protected unmountAgent?: () => void;

  @postConstruct()
  protected init(): void {
    this.id = EigentAgentWidget.ID;
    this.title.label = EigentAgentWidget.LABEL;
    this.title.caption = EigentAgentWidget.LABEL;
    this.title.iconClass = 'codicon codicon-hubot';
    this.title.closable = true;
    this.addClass('eigent-agent-widget');
    this.node.style.height = '100%';

    this.host = document.createElement('div');
    this.host.style.height = '100%';
    this.host.style.minHeight = '0';
    this.host.style.overflow = 'hidden';
    this.node.appendChild(this.host);
  }

  protected override onAfterAttach(msg: Message): void {
    super.onAfterAttach(msg);
    void this.mount();
  }

  protected override onBeforeDetach(msg: Message): void {
    this.unmountAgent?.();
    this.unmountAgent = undefined;
    super.onBeforeDetach(msg);
  }

  protected override onCloseRequest(msg: Message): void {
    this.unmountAgent?.();
    this.unmountAgent = undefined;
    super.onCloseRequest(msg);
  }

  private async mount(): Promise<void> {
    if (this.unmountAgent) return;
    try {
      const mountAgentPanel = await loadAgentBundle();
      this.unmountAgent = mountAgentPanel(this.host, {
        baseUrl: BRAIN_BASE_URL,
      });
    } catch (err) {
      this.host.textContent = `Failed to load the Eigent agent: ${
        (err as Error).message
      }`;
    }
  }
}
