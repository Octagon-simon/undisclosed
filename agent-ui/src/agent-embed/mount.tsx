// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

/**
 * Embed entry for the Undisclosed agent UI.
 *
 * The agent panel (`ChatBox` + its providers) is built here with Undisclosed's own
 * Vite toolchain — so `import.meta.env`, Tailwind `ds-*` tokens, and i18n all
 * work — and exposed as a single `mountAgentPanel(el, config)`. A different host
 * (e.g. the Theia agent widget's `ReactWidget`) loads the built library and
 * mounts it into its OWN DOM node: native render, same window, no iframe, one
 * source of truth.
 *
 * Everything host-specific is INJECTED via `config` (base URL, token, host
 * adapter) — no IPC, no reliance on the Electron shell. See
 * AGENT_DECOUPLING_AUDIT.md.
 */

import AgentEmbedPanel, { type AgentPanelApi } from './AgentEmbedPanel';
import { ThemeProvider } from '@/components/Layout/ThemeProvider';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ConnectionProvider } from '@/context/ConnectionContext';
import { createHost, HostProvider } from '@/host';
import { setOpenFolderRoot } from '@/lib/openFolder';
import type { AppHost } from '@/host/types';
import i18n from '@/i18n';
import { useAuthStore } from '@/store/authStore';
import { injectHost } from '@/store/chatStore';
import { setConnectionConfig } from '@/store/connectionStore';
import { ensureProjectLoaded } from '@/components/ProjectPageSidebar/projectNav';
import { createEmbedConversation } from './conversation';
import { useProjectStore } from '@/store/projectStore';
import {
  getVisibleProjectMetasForSpace,
  useSpaceStore,
} from '@/store/spaceStore';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createRef, StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter } from 'react-router-dom';
// Global Tailwind / ds-* tokens — bundled into the library so the panel is
// styled wherever it's mounted (Vite inlines/extracts this at build time).
import '@/style/index.css';

export interface AgentPanelConfig {
  /** Brain (agent backend) base URL, e.g. "http://localhost:5001". */
  baseUrl: string;
  /** Cloud proxy base URL (providers, configs, history). Omit for Brain-only. */
  proxyBaseUrl?: string;
  /** Bearer token for the backend (seeded into authStore). */
  token?: string | null;
  /** Numeric user id that pairs with the token. */
  userId?: number | null;
  /** Account email — the Brain's /chat requires it as a string. */
  email?: string | null;
  /** Host's open folder (e.g. Theia's workspace root). Binds the active space
   *  to it so the agent works on what the user is editing. */
  workspaceRoot?: string;
  /**
   * Host-capability adapter (file access, etc.). Omit for the default browser
   * host; pass a Theia/no-op adapter to override desktop-only behavior.
   */
  host?: AppHost;
}

/** What `mountAgentPanel` returns: the panel's imperative API + `unmount`. The
 *  host (e.g. Theia title-bar toolbar) drives New/History/governance through it. */
export interface AgentPanelHandle extends AgentPanelApi {
  unmount(): void;
}

/**
 * Mount the Undisclosed agent panel into `element`. Returns a handle (imperative API
 * + `unmount`). Idempotent per element (unmount before re-mounting the node).
 */
export function mountAgentPanel(
  element: HTMLElement,
  config: AgentPanelConfig
): AgentPanelHandle {
  // 1) Inject transport config — the real http.ts short-circuits IPC/build-env
  //    when brainEndpoint/proxyEndpoint are set, so this points the stack at the
  //    backend (Brain) and, when given, the cloud proxy (providers/configs).
  setConnectionConfig({
    brainEndpoint: config.baseUrl.replace(/\/+$/, ''),
    ...(config.proxyBaseUrl
      ? { proxyEndpoint: config.proxyBaseUrl.replace(/\/+$/, '') }
      : {}),
  });

  // 2) Seed auth (token + user id + email) so buildBrainHeaders attaches the
  //    Bearer and the /chat payload has a valid email (the Brain requires it).
  if (config.token !== undefined || config.email !== undefined) {
    useAuthStore.setState({
      token: config.token ?? null,
      user_id: config.userId ?? null,
      ...(config.email !== undefined ? { email: config.email ?? null } : {}),
    });
  }

  // 3) Host adapter for chatStore's non-transport capabilities.
  const host = config.host ?? createHost();
  injectHost(host);

  // 3a) Live editor-context sync: mirror the host's active editor into a store
  //     the send path reads, so the agent knows which file the user is looking
  //     at without shelling out. Best-effort; hosts without an editor omit it.
  let unsubscribeActiveEditor: (() => void) | undefined;
  void import('@/store/activeEditorStore')
    .then(({ useActiveEditorStore }) => {
      const set = useActiveEditorStore.getState().setActiveEditor;
      set(host.getActiveEditor?.() ?? null);
      unsubscribeActiveEditor = host.onActiveEditorChanged?.((info) =>
        set(info)
      );
    })
    .catch((err) =>
      console.warn('[agent-embed] active-editor sync failed:', err)
    );

  // 3b) Load the user's skills from the Brain (`/skills`). The desktop app does
  //     this at startup; the embed has no such trigger, so the composer's skill
  //     picker + `#` autocomplete came up empty. Best-effort, non-blocking.
  void import('@/store/skillsStore')
    .then((m) => m.useSkillsStore.getState().syncFromDisk())
    .catch((err) => console.warn('[agent-embed] skills sync failed:', err));

  // 4) Bootstrap context. ChatBox renders from a PER-PROJECT chat store; a bare
  //    embed has none (the host page has its own empty storage). Scope ONE SPACE
  //    PER FOLDER so History shows only the current folder's conversations
  //    (Antigravity model). Best-effort + async — the UI renders immediately.
  //    Record the open folder up front so every chat request can forward it as
  //    space_root_path even before bootstrapWorkspace finishes (it isn't awaited,
  //    so a conversation started immediately would otherwise miss the folder).
  setOpenFolderRoot(config.workspaceRoot);
  void bootstrapWorkspace(config.userId ?? undefined, config.workspaceRoot);

  // Scope marker: the agent stylesheet scopes its global resets under this
  // class (see vite.config.agent-embed.ts) so they don't leak into the host.
  element.classList.add('undisclosed-agent-root');

  // Keep Cmd/Ctrl+A local to the panel's own inputs. Theia binds select-all
  // globally and it fires on the active editor even when a chatbox input is
  // focused. A window CAPTURE listener runs before Theia's handler; when the
  // target is one of our inputs we stop propagation (but not the default), so
  // the browser selects the input's text and Theia never sees the key.
  const selectAllGuard = (e: KeyboardEvent) => {
    if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
    if (e.key !== 'a' && e.key !== 'A') return;
    const t = e.target as HTMLElement | null;
    if (!t || !element.contains(t)) return;
    if (
      t.tagName === 'INPUT' ||
      t.tagName === 'TEXTAREA' ||
      t.isContentEditable
    ) {
      e.stopPropagation();
    }
  };
  window.addEventListener('keydown', selectAllGuard, true);

  const queryClient = new QueryClient();
  const apiRef = createRef<AgentPanelApi>();
  const root: Root = createRoot(element);
  root.render(
    <StrictMode>
      <HostProvider host={host}>
        {/* No desktop host in an embedded context → ConnectionProvider
            resolves the channel to "web" automatically. */}
        <ConnectionProvider>
          <I18nextProvider i18n={i18n}>
            <QueryClientProvider client={queryClient}>
              <ThemeProvider>
                <TooltipProvider>
                  {/* ChatBox has a few router-aware children; a MemoryRouter
                      satisfies the context without owning app navigation. */}
                  <MemoryRouter>
                    <AgentEmbedPanel ref={apiRef} />
                  </MemoryRouter>
                  {/* Toasts portal to <body>; without this the embed showed
                      NOTHING for any toast (errors, "connector added", etc.). */}
                  <Toaster style={{ zIndex: 999999, position: 'fixed' }} />

                </TooltipProvider>
              </ThemeProvider>
            </QueryClientProvider>
          </I18nextProvider>
        </ConnectionProvider>
      </HostProvider>
    </StrictMode>
  );

  // Delegate the imperative API to the mounted panel's ref (populated after the
  // first render — before any host toolbar click can arrive).
  return {
    unmount: () => {
      window.removeEventListener('keydown', selectAllGuard, true);
      unsubscribeActiveEditor?.();
      root.unmount();
      element.classList.remove('undisclosed-agent-root');
    },
    newConversation: () => apiRef.current?.newConversation(),
    toggleHistory: () => apiRef.current?.toggleHistory(),
    showConversation: () => apiRef.current?.showConversation(),
    isHistoryOpen: () => apiRef.current?.isHistoryOpen() ?? false,
    showStats: () => apiRef.current?.showStats(),
    showMemory: () => apiRef.current?.showMemory(),
    showModels: () => apiRef.current?.showModels(),
    showSettings: () => apiRef.current?.showSettings(),
    showBrowser: () => apiRef.current?.showBrowser(),
    getGovernance: () => apiRef.current?.getGovernance() ?? 'auto',
    setGovernance: (mode) => apiRef.current?.setGovernance(mode),
    getShowThinking: () => apiRef.current?.getShowThinking() ?? true,
    setShowThinking: (value) => apiRef.current?.setShowThinking(value),
  };
}

/**
 * Bind the agent to ONE SPACE PER FOLDER: find-or-create a space bound to the
 * host's open folder and make it active, so History is scoped to that folder
 * (not all conversations). No folder → the hydrated scratch/blank space.
 */
async function bootstrapWorkspace(
  userId: string | number | undefined,
  workspaceRoot: string | undefined
): Promise<void> {
  try {
    await useSpaceStore.getState().hydrateFromServer(userId);
  } catch (err) {
    console.warn('[agent-embed] space hydrate failed:', err);
  }

  if (workspaceRoot) {
    const ss = useSpaceStore.getState();
    const normalized = workspaceRoot.replace(/\/+$/, '');
    let spaceId = ss
      .getAllSpaces()
      .find((s) => (s.rootPath ?? '').replace(/\/+$/, '') === normalized)?.id;
    if (!spaceId) {
      const name = normalized.split(/[/\\]/).pop() || 'Workspace';
      try {
        spaceId = await ss.createSpaceOnServer({
          name,
          sourceType: 'folder',
          rootPath: normalized,
          setActive: false,
        });
      } catch (err) {
        console.warn('[agent-embed] create folder space failed:', err);
      }
    }
    if (spaceId && useSpaceStore.getState().activeSpaceId !== spaceId) {
      ss.setActiveSpace(spaceId);
    }
  }

  await ensureActiveProjectForSpace();
}

/**
 * Ensure a project in the ACTIVE space is active — resume the folder's most
 * recent real conversation, else start a fresh one so ChatBox has a live chat
 * store. Also handles the case where the active project belonged to a different
 * (previous) space after a folder switch.
 */
async function ensureActiveProjectForSpace(): Promise<void> {
  const projectStore = useProjectStore.getState();
  const activeSpaceId = useSpaceStore.getState().activeSpaceId;
  if (!activeSpaceId) {
    if (!projectStore.activeProjectId) {
      await createEmbedConversation('New Project');
    }
    return;
  }
  try {
    await useSpaceStore.getState().syncProjectsFromServer(activeSpaceId);
  } catch {
    /* offline or already synced */
  }
  const ss = useSpaceStore.getState();
  const metas = getVisibleProjectMetasForSpace(
    ss.projectsBySpaceId,
    activeSpaceId
  );
  const activeInSpace =
    !!projectStore.activeProjectId &&
    metas.some((m) => m.id === projectStore.activeProjectId);
  if (activeInSpace) {
    // The right project is already active, but on a fresh page (folder switch
    // reloads the whole workbench) its chat store isn't hydrated yet — without
    // this the conversation renders empty and looks lost. Re-load it.
    await ensureProjectLoaded(
      projectStore,
      projectStore.activeProjectId as string
    ).catch(() => undefined);
    return;
  }
  if (metas.length > 0) {
    const lastId = ss.lastVisitedProjectBySpace[activeSpaceId];
    const pick = metas.find((m) => m.id === lastId) ?? metas[0];
    projectStore.setActiveProject(pick.id);
    await ensureProjectLoaded(projectStore, pick.id).catch(() => undefined);
  } else {
    await createEmbedConversation('New Project');
  }
}

export default mountAgentPanel;
