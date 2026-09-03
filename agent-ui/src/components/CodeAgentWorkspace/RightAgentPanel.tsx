// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
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
 * Rich, resizable right-rail agent panel for the editor-first layout
 * (Antigravity style). Wraps the existing `ChatBox` (which already owns the
 * message list + composer) with rich chrome above it: a header with a live
 * status dot + governance badge, a project-context strip, and a plan/progress
 * strip. See RIGHT_AGENT_PANEL_PLAN.md.
 */

import ChatBox from '@/components/ChatBox';
import { Button } from '@/components/ui/button';
import { TooltipSimple } from '@/components/ui/tooltip';
import useChatStoreAdapter from '@/hooks/useChatStoreAdapter';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/store/authStore';
import { useProjectStore } from '@/store/projectStore';
import { useSpaceStore } from '@/store/spaceStore';
import { ChatTaskStatus } from '@/types/constants';
import {
  Bot,
  History,
  PanelRightClose,
  Plus,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import AgentPanelHistory from './AgentPanelHistory';

const MIN_W = 320;
const MAX_W = 720;

export default function RightAgentPanel({
  onCollapse,
}: {
  onCollapse: () => void;
}) {
  const { t } = useTranslation();
  const { chatStore } = useChatStoreAdapter();
  const activeProjectId = useProjectStore((s) => s.activeProjectId);
  const createProject = useProjectStore((s) => s.createProject);

  // The panel body is either the live conversation or the History list (the
  // conversation list that *replaces* the conversation, mirroring the classic
  // left-nav projects list).
  const [body, setBody] = useState<'conversation' | 'history'>('conversation');

  // `+ New` = a fresh project ("new workspace") in the active space. Empty,
  // non-started projects are filtered out of History until the user chats, so
  // this never litters the list. Stays in the Code view (no tab switch).
  const handleNewProject = useCallback(() => {
    createProject(t('layout.new-project'));
    setBody('conversation');
  }, [createProject, t]);
  const governanceMode = useAuthStore((s) => s.governanceMode);
  // The bound folder is the active space's rootPath (Decision A); fall back to
  // the ad-hoc last-opened folder when the space has no bound root yet.
  const spaceFolder = useSpaceStore((s) =>
    s.activeSpaceId ? (s.spaces[s.activeSpaceId]?.rootPath ?? null) : null
  );
  const lastFolder = useAuthStore((s) => s.codeEditorLastFolder);
  const dockWidth = useAuthStore((s) => s.codeEditorDockWidth);
  const setDockWidth = useAuthStore((s) => s.setCodeEditorDockWidth);

  const [width, setWidth] = useState(dockWidth);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  // Active task snapshot for the status dot + plan strip. `useChatStoreAdapter`
  // returns a reactive state snapshot, so reading it directly re-renders on
  // change (same pattern as WorkforceMenu).
  const activeTaskId = chatStore?.activeTaskId as string | undefined;
  const task = activeTaskId ? chatStore?.tasks?.[activeTaskId] : undefined;

  const running = task?.status === ChatTaskStatus.RUNNING;
  const progress = Math.max(
    0,
    Math.min(100, Math.round((task as any)?.progressValue ?? 0))
  );
  const boundFolder = spaceFolder ?? lastFolder;
  const folderName = boundFolder ? boundFolder.split(/[/\\]/).pop() : null;
  const isAsk = governanceMode === 'ask';

  // Resize the dock. The move/up handlers live inside `startDrag` as local
  // closures, so there's no self-referencing useCallback (which `exhaustive-deps`
  // can't satisfy without a cycle) and the add/remove listener identities always
  // match. A ref holds the teardown so an unmount mid-drag still cleans up.
  const cleanupDragRef = useRef<() => void>(() => {});

  const startDrag = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startW: width };
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';

      const onMove = (ev: MouseEvent) => {
        if (!dragRef.current) return;
        // Panel is on the right; dragging the left edge left widens it.
        const next =
          dragRef.current.startW + (dragRef.current.startX - ev.clientX);
        setWidth(Math.max(MIN_W, Math.min(MAX_W, next)));
      };
      const onUp = () => {
        dragRef.current = null;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        setWidth((w) => {
          setDockWidth(w);
          return w;
        });
        cleanupDragRef.current();
      };
      cleanupDragRef.current = () => {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };

      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
    [width, setDockWidth]
  );

  // Remove any in-flight drag listeners if the panel unmounts mid-drag.
  useEffect(() => () => cleanupDragRef.current(), []);

  return (
    <div
      className="relative flex h-full shrink-0 flex-col border-l border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-subtle-default"
      style={{ width }}
    >
      {/* Resize handle on the left border */}
      <div
        onMouseDown={startDrag}
        className="hover:bg-ds-border-neutral-strong-default/40 absolute -left-1 top-0 z-20 h-full w-2 cursor-col-resize"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize agent panel"
      />

      {/* Header */}
      <div className="flex shrink-0 items-center justify-between gap-2 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-ds-bg-brand-subtle-default">
            <Bot
              className="h-4 w-4 text-ds-icon-brand-default-default"
              aria-hidden
            />
          </span>
          <span className="truncate text-body-sm font-semibold text-ds-text-neutral-default-default">
            Undisclosed Agent
          </span>
          <TooltipSimple content={running ? 'Running' : 'Ready'} side="bottom">
            <span
              className={cn(
                'h-2 w-2 shrink-0 rounded-full',
                running
                  ? 'animate-pulse bg-ds-bg-status-running-default-default'
                  : 'bg-ds-bg-status-completed-default-default'
              )}
              aria-label={running ? 'Running' : 'Ready'}
            />
          </TooltipSimple>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <TooltipSimple
            content={
              isAsk
                ? 'Approval required for risky actions'
                : 'Actions run automatically'
            }
            side="bottom"
          >
            <span
              className={cn(
                'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-label-xs font-semibold',
                isAsk
                  ? 'bg-ds-bg-warning-subtle-default text-ds-text-warning-strong-default'
                  : 'bg-ds-bg-neutral-muted-default text-ds-text-neutral-subtle-default'
              )}
            >
              {isAsk ? (
                <ShieldAlert className="h-3 w-3" aria-hidden />
              ) : (
                <ShieldCheck className="h-3 w-3" aria-hidden />
              )}
              {isAsk ? 'Ask' : 'Auto'}
            </span>
          </TooltipSimple>
          <TooltipSimple content="New project" side="bottom">
            <Button
              variant="ghost"
              size="sm"
              buttonContent="icon-only"
              onClick={handleNewProject}
              aria-label="New project"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </TooltipSimple>
          <TooltipSimple
            content={body === 'history' ? 'Back to conversation' : 'History'}
            side="bottom"
          >
            <Button
              variant={body === 'history' ? 'secondary' : 'ghost'}
              size="sm"
              buttonContent="icon-only"
              onClick={() =>
                setBody((m) => (m === 'history' ? 'conversation' : 'history'))
              }
              aria-label="Toggle conversation history"
              aria-pressed={body === 'history'}
            >
              <History className="h-4 w-4" />
            </Button>
          </TooltipSimple>
          <TooltipSimple content="Collapse panel" side="bottom">
            <Button
              variant="ghost"
              size="sm"
              buttonContent="icon-only"
              onClick={onCollapse}
              aria-label="Collapse agent panel"
            >
              <PanelRightClose className="h-4 w-4" />
            </Button>
          </TooltipSimple>
        </div>
      </div>

      {/* Context strip */}
      {folderName ? (
        <div className="flex shrink-0 items-center gap-1.5 border-t border-solid border-ds-border-neutral-subtle-default px-3 py-1.5">
          <span className="truncate text-label-xs text-ds-text-neutral-subtle-default">
            <span className="font-semibold text-ds-text-neutral-default-default">
              {folderName}
            </span>{' '}
            · workspace folder
          </span>
        </div>
      ) : null}

      {/* Plan / progress strip */}
      {progress > 0 ? (
        <div className="flex shrink-0 flex-col gap-1 border-t border-solid border-ds-border-neutral-subtle-default px-3 py-2">
          <div className="flex items-center justify-between">
            <span className="text-label-xs font-semibold text-ds-text-neutral-default-default">
              Plan
            </span>
            <span className="text-label-xs tabular-nums text-ds-text-neutral-subtle-default">
              {progress}%
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-ds-bg-neutral-muted-default">
            <div
              className="h-full rounded-full bg-ds-bg-brand-default-default transition-[width] duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      ) : null}

      {/* Conversation + composer (ChatBox owns both). The agent chat is scoped
          to an active project; when none is active the editor is just a folder,
          so show a clear empty state instead of a blank ChatBox. */}
      <div className="min-h-0 flex-1 overflow-hidden border-t border-solid border-ds-border-neutral-subtle-default">
        {body === 'history' ? (
          <AgentPanelHistory
            onSelected={() => setBody('conversation')}
            onNewProject={handleNewProject}
          />
        ) : activeProjectId ? (
          <ChatBox />
        ) : (
          <div className="flex h-full w-full items-center justify-center p-6">
            <div className="flex max-w-[280px] flex-col items-center gap-2 text-center">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ds-bg-brand-subtle-default">
                <Bot
                  className="h-5 w-5 text-ds-icon-brand-default-default"
                  aria-hidden
                />
              </span>
              <div className="text-body-sm font-semibold text-ds-text-neutral-default-default">
                No active project
              </div>
              <div className="text-label-xs text-ds-text-neutral-subtle-default">
                Open or start a project to chat with the agent about your code.
                The editor on the left works independently.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
