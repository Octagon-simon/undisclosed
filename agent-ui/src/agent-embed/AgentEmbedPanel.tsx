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
 * The body `mountAgentPanel` renders: Eigent's `ChatBox` (or the History list),
 * WITHOUT its own header. In an embedded host (the Theia agent widget) the
 * actions — New / History / governance — live in the host's NATIVE title bar,
 * which drives this panel through the imperative `AgentPanelApi` exposed via
 * ref. See mount.tsx.
 */

import AgentPanelHistory from '@/components/CodeAgentWorkspace/AgentPanelHistory';
import AgentUsageStats from '@/components/CodeAgentWorkspace/AgentUsageStats';
import { useEmbedNav } from '@/agent-embed/embedNav';
import { useProjectStore } from '@/store/projectStore';
import { useAuthStore, type GovernanceMode } from '@/store/authStore';
import { ArrowLeft, Bot } from 'lucide-react';
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import ChatBox from '@/components/ChatBox';
import AgentConnectors from '@/components/CodeAgentWorkspace/AgentConnectors';
import AgentMemorySettings from '@/components/CodeAgentWorkspace/AgentMemorySettings';
import AgentSkills from '@/components/CodeAgentWorkspace/AgentSkills';
import AgentModels from '@/components/CodeAgentWorkspace/AgentModels';
import AgentSettings from '@/components/CodeAgentWorkspace/AgentSettings';
import BrowserTakeControl from '@/components/BrowserAgentWorkspace/BrowserTakeControl';

type PanelBody =
  | 'conversation'
  | 'history'
  | 'stats'
  | 'skills'
  | 'connectors'
  | 'memory'
  | 'models'
  | 'settings'
  | 'browser';

/** A management screen (skills/connectors) with a back-to-conversation header. */
function ManagedScreen({
  title,
  onBack,
  children,
}: {
  title: string;
  onBack: () => void;
  children: React.ReactNode;
}) {
  // Just a "Back" affordance — no title and no border. Each screen renders its
  // own title row below, and the panel toolbar already has a divider, so a
  // second bordered header here read as a heavy "box" around the row.
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center px-2 py-1.5">
        <button
          type="button"
          onClick={onBack}
          aria-label={title ? `Back from ${title}` : 'Back'}
          className="flex items-center gap-1 rounded-md px-1.5 py-1 text-label-xs text-ds-text-neutral-subtle-default outline-none transition-colors hover:bg-ds-bg-neutral-muted-default"
        >
          <ArrowLeft size={14} aria-hidden />
          Back
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}

/** Imperative surface the host title bar drives the panel through. */
export interface AgentPanelApi {
  newConversation(): void;
  toggleHistory(): void;
  showConversation(): void;
  isHistoryOpen(): boolean;
  /** Show the usage/overview screen. */
  showStats(): void;
  /** Show the memory settings screen. */
  showMemory(): void;
  /** Show the model configuration (BYOK) screen. */
  showModels(): void;
  /** Show the settings screen (language, …). */
  showSettings(): void;
  /** Show the live agent-browser view / take-control screen. */
  showBrowser(): void;
  getGovernance(): GovernanceMode;
  setGovernance(mode: GovernanceMode): void;
  /** Reasoning "thinking" block visibility (persisted flag). */
  getShowThinking(): boolean;
  setShowThinking(value: boolean): void;
}

const AgentEmbedPanel = forwardRef<AgentPanelApi>((_props, ref) => {
  const { t } = useTranslation();
  const activeProjectId = useProjectStore((s) => s.activeProjectId);
  const setGovernanceMode = useAuthStore((s) => s.setGovernanceMode);

  const [body, setBody] = useState<PanelBody>('conversation');

  // Shared composer pickers (skills/connectors) can't reach this body state, so
  // their "Manage …" action requests a screen here; consume + clear it.
  const requestedScreen = useEmbedNav((s) => s.requested);
  const clearRequest = useEmbedNav((s) => s.clearRequest);
  useEffect(() => {
    if (requestedScreen) {
      setBody(requestedScreen);
      clearRequest();
    }
  }, [requestedScreen, clearRequest]);

  const newConversation = useCallback(() => {
    // Create the empty conversation SYNCHRONOUSLY so the panel switches to a
    // clean task immediately — no async server round-trip during which the
    // previous (possibly unfinished, plan-bearing) conversation stays active
    // and its plan bleeds into the "new" one. The project is scoped to the
    // active space (folder) and the backend persists it on the first message.
    setBody('conversation');
    useProjectStore.getState().createProject(t('layout.new-project'));
  }, [t]);

  useImperativeHandle(
    ref,
    (): AgentPanelApi => ({
      newConversation,
      toggleHistory: () =>
        setBody((m) => (m === 'history' ? 'conversation' : 'history')),
      showConversation: () => setBody('conversation'),
      isHistoryOpen: () => body === 'history',
      showStats: () => setBody((m) => (m === 'stats' ? 'conversation' : 'stats')),
      showMemory: () =>
        setBody((m) => (m === 'memory' ? 'conversation' : 'memory')),
      showModels: () =>
        setBody((m) => (m === 'models' ? 'conversation' : 'models')),
      showSettings: () =>
        setBody((m) => (m === 'settings' ? 'conversation' : 'settings')),
      showBrowser: () =>
        setBody((m) => (m === 'browser' ? 'conversation' : 'browser')),
      getGovernance: () => useAuthStore.getState().governanceMode,
      setGovernance: (mode) => setGovernanceMode(mode),
      getShowThinking: () => useAuthStore.getState().showThinking,
      setShowThinking: (value) =>
        useAuthStore.getState().setShowThinking(value),
    }),
    [newConversation, setGovernanceMode, body]
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-ds-bg-neutral-subtle-default">
      <div className="min-h-0 flex-1 overflow-hidden">
        {body === 'skills' ? (
          <ManagedScreen
            title="Skills"
            onBack={() => setBody('conversation')}
          >
            <AgentSkills />
          </ManagedScreen>
        ) : body === 'connectors' ? (
          <ManagedScreen
            title="Connectors"
            onBack={() => setBody('conversation')}
          >
            <AgentConnectors />
          </ManagedScreen>
        ) : body === 'memory' ? (
          <ManagedScreen title="Memory" onBack={() => setBody('conversation')}>
            <AgentMemorySettings />
          </ManagedScreen>
        ) : body === 'models' ? (
          <ManagedScreen title="Models" onBack={() => setBody('conversation')}>
            <AgentModels />
          </ManagedScreen>
        ) : body === 'settings' ? (
          <ManagedScreen title="Settings" onBack={() => setBody('conversation')}>
            <AgentSettings />
          </ManagedScreen>
        ) : body === 'browser' ? (
          <ManagedScreen title="Browser" onBack={() => setBody('conversation')}>
            <BrowserTakeControl />
          </ManagedScreen>
        ) : body === 'stats' ? (
          <AgentUsageStats />
        ) : body === 'history' ? (
          <div className="h-full min-h-0 px-2 py-2">
            <AgentPanelHistory
              onSelected={() => setBody('conversation')}
              onNewProject={newConversation}
            />
          </div>
        ) : activeProjectId ? (
          <ChatBox />
        ) : (
          <div className="flex h-full w-full items-center justify-center p-6 text-center">
            <div className="flex max-w-[300px] flex-col items-center gap-2">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ds-bg-brand-subtle-default">
                <Bot
                  className="h-5 w-5 text-ds-icon-brand-default-default"
                  aria-hidden
                />
              </span>
              <div className="text-body-sm font-semibold text-ds-text-neutral-default-default">
                No active workspace folder
              </div>
              <div className="text-label-xs leading-relaxed text-ds-text-neutral-subtle-default">
                Open a folder in the editor (File → Open Folder) to work on a
                project, and the agent will operate there. Or use{' '}
                <span className="font-semibold">New</span> in the title bar for a
                temporary conversation.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

AgentEmbedPanel.displayName = 'AgentEmbedPanel';
export default AgentEmbedPanel;
