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
 * Shared conversation/project row actions — pin, delete, and archive ("end") —
 * plus their confirm dialogs, so the classic left `ProjectPageSidebar` and the
 * editor-first `AgentPanelHistory` offer identical behavior from one source of
 * truth. Reads everything it needs from the stores directly.
 */

import {
  fetchDelete,
  fetchPut,
  proxyFetchDelete,
  proxyFetchGet,
} from '@/api/http';
import AlertDialog from '@/components/ui/alertDialog';
import { useHost } from '@/host';
import { setProjectAchievedState } from '@/lib/projectAchievement';
import { useAuthStore } from '@/store/authStore';
import { usePageTabStore } from '@/store/pageTabStore';
import { useProjectRuntimeStore } from '@/store/projectRuntimeStore';
import { useSpaceStore } from '@/store/spaceStore';
import { ChatTaskStatus } from '@/types/constants';
import { useCallback, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ensureProjectLoaded } from './projectNav';

const PINNED_STORAGE_KEY = 'eigent-pinned-projects';

function readPinned(): Set<string> {
  try {
    return new Set(
      JSON.parse(localStorage.getItem(PINNED_STORAGE_KEY) ?? '[]') as string[]
    );
  } catch {
    return new Set();
  }
}

export interface ProjectNavActions {
  pinnedProjectIds: Set<string>;
  handlePinProject: (projectId: string) => void;
  requestDeleteProject: (projectId: string) => void;
  requestAchieveProject: (projectId: string) => void;
  /** The delete + archive confirm dialogs; render once in the consumer. */
  dialogs: ReactNode;
}

export function useProjectNavActions(): ProjectNavActions {
  const { t } = useTranslation();
  const host = useHost();
  const ipcRenderer = host?.ipcRenderer;
  const projectStore = useProjectRuntimeStore();
  const activeSpaceId = useSpaceStore((s) => s.activeSpaceId);
  const email = useAuthStore((s) => s.email);
  const setActiveWorkspaceTab = usePageTabStore((s) => s.setActiveWorkspaceTab);
  const requestWorkspaceChatFocus = usePageTabStore(
    (s) => s.requestWorkspaceChatFocus
  );

  const [pinnedProjectIds, setPinnedProjectIds] =
    useState<Set<string>>(readPinned);
  const [deleteProjectId, setDeleteProjectId] = useState<string | null>(null);
  const [deleteProjectLoading, setDeleteProjectLoading] = useState(false);
  const [achieveProjectId, setAchieveProjectId] = useState<string | null>(null);
  const [achieveProjectLoading, setAchieveProjectLoading] = useState(false);
  const [achieveDialogOpen, setAchieveDialogOpen] = useState(false);

  const handlePinProject = useCallback((projectId: string) => {
    setPinnedProjectIds((prev) => {
      const next = new Set(prev);
      if (next.has(projectId)) {
        next.delete(projectId);
      } else {
        next.add(projectId);
      }
      try {
        localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify([...next]));
      } catch {
        /* storage unavailable */
      }
      return next;
    });
  }, []);

  const requestDeleteProject = useCallback((projectId: string) => {
    setDeleteProjectId(projectId);
  }, []);

  const requestAchieveProject = useCallback((projectId: string) => {
    setAchieveProjectId(projectId);
    setAchieveDialogOpen(true);
  }, []);

  const confirmDeleteProject = useCallback(async () => {
    const projectId = deleteProjectId;
    if (!projectId) return;

    setDeleteProjectLoading(true);
    try {
      const projectMeta = useSpaceStore.getState().getProjectMeta(projectId);
      const spaceId = projectMeta?.spaceId ?? activeSpaceId ?? undefined;
      const wasActive = projectStore.activeProjectId === projectId;

      let historyProject: {
        tasks?: Array<{ id?: number; task_id?: string; project_id?: string }>;
      } | null = null;

      try {
        historyProject = await proxyFetchGet(
          `/api/v1/chat/histories/grouped/${projectId}`,
          { include_tasks: true }
        );
      } catch (error) {
        console.warn(
          `[useProjectNavActions] No grouped history for project ${projectId}:`,
          error
        );
      }

      const cleanupPromises = (historyProject?.tasks ?? [])
        .filter((task) => task?.id != null)
        .flatMap((task) => {
          const work: Promise<unknown>[] = [
            proxyFetchDelete(`/api/v1/chat/history/${task.id}`).catch(
              (error) => {
                console.warn(
                  `[useProjectNavActions] Failed to delete history task ${task.task_id}:`,
                  error
                );
              }
            ),
          ];
          if (task.task_id && email && ipcRenderer) {
            work.push(
              ipcRenderer
                .invoke(
                  'delete-task-files',
                  email,
                  task.task_id,
                  task.project_id ?? projectId
                )
                .catch((error: unknown) => {
                  console.warn(
                    `[useProjectNavActions] Local file cleanup failed for task ${task.task_id}:`,
                    error
                  );
                })
            );
          }
          return work;
        });
      await Promise.allSettled(cleanupPromises);

      try {
        await fetchDelete(`/chat/${projectId}`);
      } catch {
        /* Backend may already have removed the chat */
      }

      if (spaceId) {
        try {
          const { proxyUpdateSpaceProject } =
            await import('@/service/spaceApi');
          await proxyUpdateSpaceProject(spaceId, projectId, {
            status: 'archived',
          });
        } catch (error) {
          console.warn(
            `[useProjectNavActions] Failed to archive server project ${projectId}:`,
            error
          );
        }
      }

      projectStore.removeProject(projectId);

      if (wasActive) {
        setActiveWorkspaceTab('workforce');
        requestWorkspaceChatFocus();
      }

      toast.success(t('layout.delete-project-completed'));
    } catch (error) {
      console.error('[useProjectNavActions] Failed to delete project:', error);
      toast.error(t('layout.delete-project-failed'));
    } finally {
      setDeleteProjectLoading(false);
      setDeleteProjectId(null);
    }
  }, [
    activeSpaceId,
    deleteProjectId,
    email,
    ipcRenderer,
    projectStore,
    requestWorkspaceChatFocus,
    setActiveWorkspaceTab,
    t,
  ]);

  const confirmAchieveProject = useCallback(async () => {
    const projectId = achieveProjectId;
    if (!projectId) return;

    setAchieveProjectLoading(true);
    try {
      const wasActive = projectStore.activeProjectId === projectId;
      await ensureProjectLoaded(projectStore, projectId);
      const projectChatStore = projectStore.peekActiveChatStore(projectId);
      const projectChatState = projectChatStore?.getState();
      const taskId = projectChatState?.activeTaskId;
      const task = taskId ? projectChatState?.tasks[taskId] : undefined;

      const hasActiveRun =
        task &&
        (task.status === ChatTaskStatus.RUNNING ||
          task.status === ChatTaskStatus.PAUSE ||
          task.isPending);
      if (taskId && hasActiveRun) {
        await fetchPut(`/task/${taskId}/take-control`, { action: 'stop' });
        projectChatStore?.getState().stopTask(taskId);
        projectChatStore?.getState().setIsPending(taskId, false);
      }

      await setProjectAchievedState({
        projectStore,
        projectId,
        achieved: true,
      });
      if (wasActive) {
        setActiveWorkspaceTab('workforce');
        requestWorkspaceChatFocus();
      }
      toast.success(t('layout.project-ended-successfully'), {
        closeButton: true,
      });
    } catch (error) {
      console.error('[useProjectNavActions] Failed to achieve project:', error);
      toast.error(t('layout.failed-to-end-project'), { closeButton: true });
    } finally {
      setAchieveProjectLoading(false);
      setAchieveProjectId(null);
      setAchieveDialogOpen(false);
    }
  }, [
    achieveProjectId,
    projectStore,
    requestWorkspaceChatFocus,
    setActiveWorkspaceTab,
    t,
  ]);

  const dialogs = (
    <>
      <AlertDialog
        isOpen={deleteProjectId != null}
        onClose={() => {
          if (deleteProjectLoading) return;
          setDeleteProjectId(null);
        }}
        onConfirm={() => void confirmDeleteProject()}
        title={t('layout.delete-project')}
        message={t('layout.delete-project-confirmation')}
        confirmText={t('layout.delete')}
        cancelText={t('layout.cancel')}
        confirmDisabled={deleteProjectLoading}
      />
      <AlertDialog
        isOpen={achieveDialogOpen}
        onClose={() => {
          if (achieveProjectLoading) return;
          setAchieveDialogOpen(false);
          setAchieveProjectId(null);
        }}
        onConfirm={() => void confirmAchieveProject()}
        title={t('layout.end-project')}
        message={t('layout.ending-this-project-will-stop')}
        confirmText={t('layout.yes-end-project')}
        cancelText={t('layout.cancel')}
        confirmVariant="caution"
        confirmDisabled={achieveProjectLoading}
      />
    </>
  );

  return {
    pinnedProjectIds,
    handlePinProject,
    requestDeleteProject,
    requestAchieveProject,
    dialogs,
  };
}
