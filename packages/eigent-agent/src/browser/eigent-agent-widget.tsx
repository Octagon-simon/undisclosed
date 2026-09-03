// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import {
  inject,
  injectable,
  postConstruct,
} from '@theia/core/shared/inversify';
import {
  BaseWidget,
  Message,
  OpenerService,
  open,
} from '@theia/core/lib/browser';
import URI from '@theia/core/lib/common/uri';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { FileService } from '@theia/filesystem/lib/browser/file-service';

export type GovernanceMode = 'ask' | 'auto';

/** Imperative handle the bundle returns; the title-bar toolbar drives it. */
export interface AgentPanelHandle {
  unmount(): void;
  newConversation(): void;
  toggleHistory(): void;
  showConversation(): void;
  isHistoryOpen(): boolean;
  showStats(): void;
  showMemory(): void;
  showModels(): void;
  showSettings(): void;
  showBrowser(): void;
  getGovernance(): GovernanceMode;
  setGovernance(mode: GovernanceMode): void;
  getShowThinking(): boolean;
  setShowThinking(value: boolean): void;
}

/** Signature exposed by the prebuilt agent bundle (Undisclosed's mountAgentPanel). */
type MountFn = (
  element: HTMLElement,
  config: {
    baseUrl: string;
    proxyBaseUrl?: string;
    token?: string | null;
    userId?: number | null;
    email?: string | null;
    workspaceRoot?: string;
    host?: {
      electronAPI: unknown;
      ipcRenderer: unknown;
      openFile?(path: string): void | Promise<void>;
      readFileAsDataUrl?(path: string): Promise<string | null>;
    };
  }
) => AgentPanelHandle;

const BUNDLE_JS = '/eigent-agent/agent-embed.umd.js';
const BUNDLE_CSS = '/eigent-agent/style.css';
// Remaps --ds-* tokens to Theia's --theia-* theme vars; loaded AFTER the bundle
// CSS so it wins, theming the panel to match the active editor theme.
const THEME_CSS = '/eigent-agent/theme.css';
const GLOBAL = 'EigentAgentEmbed';

/** Best-effort image MIME from a file name, for building a `data:` URL. */
function mimeFromPath(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  switch (ext) {
    case 'png':
      return 'image/png';
    case 'jpg':
    case 'jpeg':
      return 'image/jpeg';
    case 'gif':
      return 'image/gif';
    case 'webp':
      return 'image/webp';
    case 'bmp':
      return 'image/bmp';
    case 'svg':
      return 'image/svg+xml';
    case 'avif':
      return 'image/avif';
    case 'ico':
      return 'image/x-icon';
    default:
      return 'application/octet-stream';
  }
}

function injectStylesheet(id: string, href: string): void {
  if (document.getElementById(id)) return;
  const link = document.createElement('link');
  link.id = id;
  link.rel = 'stylesheet';
  link.href = href;
  document.head.appendChild(link);
}

// Brain (agent runtime) — CORS-open, so the browser can call it directly.
const BRAIN_BASE_URL = 'http://localhost:5001';

/** Load the self-contained agent bundle once (CSS + UMD script), resolve to its
 *  `mountAgentPanel`. Shared across widget instances. */
let bundlePromise: Promise<MountFn> | undefined;
function loadAgentBundle(): Promise<MountFn> {
  if (bundlePromise) return bundlePromise;
  bundlePromise = new Promise<MountFn>((resolve, reject) => {
    // Order matters: bundle CSS first, then the Theia theme override.
    injectStylesheet('eigent-agent-css', BUNDLE_CSS);
    injectStylesheet('eigent-agent-theme-css', THEME_CSS);
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
 * Right-dock host for Undisclosed's real agent UI. This widget is just a native
 * Theia container + lifecycle; the actual chat/governance/history UI is the
 * prebuilt Undisclosed bundle mounted into its node via `mountAgentPanel`. One DOM,
 * one window — no iframe.
 */
@injectable()
export class EigentAgentWidget extends BaseWidget {
  static readonly ID = 'eigent-agent-widget';
  static readonly LABEL = 'Undisclosed Agent';

  @inject(WorkspaceService)
  protected readonly workspaceService!: WorkspaceService;

  @inject(OpenerService)
  protected readonly openerService!: OpenerService;

  @inject(FileService)
  protected readonly fileService!: FileService;

  protected host!: HTMLDivElement;
  protected handle?: AgentPanelHandle;

  /**
   * Open a file the agent touched in Theia's editor (wired to the trace's
   * click-to-open filenames). Resolves relative paths against the workspace
   * root; accepts absolute or file:// paths too.
   */
  private async openFileInEditor(path: string): Promise<void> {
    if (!path) return;
    try {
      let uri: URI;
      if (path.startsWith('file://')) {
        uri = new URI(path);
      } else if (path.startsWith('/')) {
        uri = new URI('file://' + path);
      } else {
        const roots = await this.workspaceService.roots;
        const root = roots[0]?.resource;
        uri = root ? root.resolve(path) : new URI('file://' + path);
      }
      await open(this.openerService, uri);
    } catch (err) {
      console.warn('[eigent-agent] openFile failed for', path, err);
    }
  }

  /**
   * Read a file the agent output (referenced by relative/absolute path in its
   * markdown) and return it as a `data:` URL so the embed can render it inline.
   * The desktop app does this over Electron; the browser embed has no such API,
   * so we read the bytes through Theia's FileService. Relative paths resolve
   * against the workspace root, matching `openFileInEditor`. Returns `null` on
   * any failure so the caller falls back to alt text.
   */
  private async readFileAsDataUrl(path: string): Promise<string | null> {
    if (!path) return null;
    try {
      let uri: URI;
      if (path.startsWith('file://')) {
        uri = new URI(path);
      } else if (path.startsWith('/')) {
        uri = new URI('file://' + path);
      } else {
        const roots = await this.workspaceService.roots;
        const root = roots[0]?.resource;
        uri = root ? root.resolve(path) : new URI('file://' + path);
      }
      const content = await this.fileService.readFile(uri);
      const bytes = content.value.buffer;
      let binary = '';
      for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      const base64 = btoa(binary);
      return `data:${mimeFromPath(uri.path.base)};base64,${base64}`;
    } catch (err) {
      console.warn('[eigent-agent] readFileAsDataUrl failed for', path, err);
      return null;
    }
  }

  // --- title-bar toolbar delegates (called by the view's toolbar commands) ---
  newConversation(): void {
    this.handle?.newConversation();
  }
  toggleHistory(): void {
    this.handle?.toggleHistory();
  }
  isHistoryOpen(): boolean {
    return this.handle?.isHistoryOpen() ?? false;
  }
  showStats(): void {
    this.handle?.showStats();
  }
  showMemory(): void {
    this.handle?.showMemory();
  }
  showModels(): void {
    this.handle?.showModels();
  }
  showSettings(): void {
    this.handle?.showSettings();
  }
  showBrowser(): void {
    this.handle?.showBrowser();
  }
  governanceMode(): GovernanceMode {
    return this.handle?.getGovernance() ?? 'auto';
  }
  setGovernance(mode: GovernanceMode): void {
    this.handle?.setGovernance(mode);
  }
  showThinkingEnabled(): boolean {
    return this.handle?.getShowThinking() ?? true;
  }
  setShowThinking(value: boolean): void {
    this.handle?.setShowThinking(value);
  }

  /** The folder open in Theia — bound as the agent's working directory. */
  private async workspaceRoot(): Promise<string | undefined> {
    try {
      const roots = await this.workspaceService.roots;
      return roots[0]?.resource.path.toString() || undefined;
    } catch {
      return undefined;
    }
  }

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
    // NOTE: the first-launch welcome is rendered by the bundle's own empty
    // state (AgentEmbedPanel), not a Theia-side overlay — a widget overlay
    // superimposed on the live conversation and its chips restarted the run.
  }

  protected override onAfterAttach(msg: Message): void {
    super.onAfterAttach(msg);
    void this.mount();
  }

  protected override onBeforeDetach(msg: Message): void {
    this.handle?.unmount();
    this.handle = undefined;
    super.onBeforeDetach(msg);
  }

  protected override onCloseRequest(msg: Message): void {
    this.handle?.unmount();
    this.handle = undefined;
    super.onCloseRequest(msg);
  }


  private async mount(): Promise<void> {
    if (this.handle) return;
    try {
      const [mountAgentPanel, workspaceRoot] = await Promise.all([
        loadAgentBundle(),
        this.workspaceRoot(),
      ]);
      this.handle = mountAgentPanel(this.host, {
        baseUrl: BRAIN_BASE_URL,
        // Cloud-proxy calls go same-origin (this app); the backend forwards
        // /api -> the Undisclosed proxy, avoiding CORS.
        proxyBaseUrl: window.location.origin,
        workspaceRoot,
        token: 'local-session-token',
        userId: 0,
        email: 'local@undisclosed.local',
        // Host bridge: the agent trace's clickable filenames open in Theia's
        // editor. electronAPI/ipcRenderer are null (web host); only openFile
        // is wired.
        host: {
          electronAPI: null,
          ipcRenderer: null,
          openFile: (path: string) => this.openFileInEditor(path),
          readFileAsDataUrl: (path: string) => this.readFileAsDataUrl(path),
        },
      });
    } catch (err) {
      this.host.textContent = `Failed to load the Undisclosed agent: ${
        (err as Error).message
      }`;
    }
  }
}
