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
 * Shared project-navigation logic so the classic left `ProjectPageSidebar` and
 * the editor-first `RightAgentPanel` History both derive the conversation list
 * (and hydrate a selected project) from a single source of truth — no drift.
 *
 * These are pure functions over the `projectStore` instance + imported helpers;
 * the *shell action* on select (flip a tab vs. switch the panel body) stays with
 * each consumer.
 */

import { proxyFetchGet } from '@/api/http';
import { isProjectAchieved } from '@/lib/projectAchievement';
import {
  buildTaskQuestionsById,
  computeProjectFreshnessAnchor,
} from '@/lib/replay';
import {
  getSessionNavLeadFromHistoryProject,
  resolveProjectNavLeadPresentation,
} from '@/lib/sessionNavLead';
import type { ProjectStore } from '@/store/projectStore';
import { getVisibleProjectMetasForSpace } from '@/store/spaceStore';
import { ChatTaskStatus } from '@/types/constants';
import type { ProjectNavItem } from './ProjectNavListRows';

/** A visible project meta as produced by `getVisibleProjectMetasForSpace`. */
export type NavProjectMeta = ReturnType<
  typeof getVisibleProjectMetasForSpace
>[number];

/**
 * Whether a project has any real activity yet (used to decide if it belongs in
 * the nav list and whether to open it as a live project vs. the new-project
 * composer).
 */
export function projectHasStarted(
  projectStore: ProjectStore,
  projectId: string
): boolean {
  const projectChatStore = projectStore.peekActiveChatStore(projectId);
  const projectChatState = projectChatStore?.getState();
  const projectTask = projectChatState?.activeTaskId
    ? projectChatState.tasks[projectChatState.activeTaskId]
    : undefined;
  return Boolean(
    projectTask &&
    ((projectTask.messages?.length || 0) > 0 ||
      projectTask.hasMessages ||
      projectTask.status !== ChatTaskStatus.PENDING)
  );
}

/** Whether a project should appear in the conversation/history list. */
export function shouldShowProjectInNavList(
  projectStore: ProjectStore,
  project: NavProjectMeta
): boolean {
  if (project.metadata?.historyId) return true;
  const historyDisplayName =
    typeof project.metadata?.historyDisplayName === 'string'
      ? project.metadata.historyDisplayName.trim()
      : '';
  if (historyDisplayName) return true;

  const normalizedName = (project.name ?? '').trim().toLowerCase();
  if (
    normalizedName &&
    normalizedName !== 'new project' &&
    normalizedName !== 'new space'
  ) {
    return true;
  }

  return projectHasStarted(projectStore, project.id);
}

/** Map visible project metas → the `ProjectNavItem[]` the list renders. */
export function buildNavProjects(args: {
  projectMetas: NavProjectMeta[];
  navLeadByProjectId: Record<
    string,
    ReturnType<typeof getSessionNavLeadFromHistoryProject>
  >;
  historyLoadingProjectIds: Record<string, boolean>;
  pinnedProjectIds: Set<string>;
  projectStore: ProjectStore;
  newProjectLabel: string;
}): ProjectNavItem[] {
  const {
    projectMetas,
    navLeadByProjectId,
    historyLoadingProjectIds,
    pinnedProjectIds,
    projectStore,
    newProjectLabel,
  } = args;
  return projectMetas
    .filter((project) => shouldShowProjectInNavList(projectStore, project))
    .map((project) => {
      const projectChatStore = projectStore.peekActiveChatStore(project.id);
      const projectChatState = projectChatStore?.getState();
      const activeTask = projectChatState?.activeTaskId
        ? projectChatState.tasks[projectChatState.activeTaskId]
        : undefined;
      return {
        id: project.id,
        title:
          project.name && project.name !== 'new project'
            ? project.name
            : newProjectLabel,
        sessionLead: resolveProjectNavLeadPresentation({
          cachedLead: navLeadByProjectId[project.id],
          isHistoryLoading: Boolean(historyLoadingProjectIds[project.id]),
          isAchieved: isProjectAchieved(project.metadata),
        }),
        achieved: isProjectAchieved(project.metadata),
        pinned: pinnedProjectIds.has(project.id),
        source: activeTask?.source,
      };
    });
}

/**
 * Ensure a project's chat store is hydrated (from remote history if needed)
 * before it's shown. Idempotent — no-ops when already loaded and not pending
 * remote hydration.
 */
export async function ensureProjectLoaded(
  projectStore: ProjectStore,
  projectId: string
): Promise<void> {
  const project = projectStore.getProjectById(projectId);
  const needsRemoteHistoryHydration =
    project?.metadata?.remoteHistoryHydrationPending === true;
  if (
    projectStore.peekActiveChatStore(projectId) &&
    !needsRemoteHistoryHydration
  ) {
    return;
  }

  try {
    const historyProject = await proxyFetchGet(
      `/api/v1/chat/histories/grouped/${projectId}`,
      { include_tasks: true }
    );
    const taskIdsList = (historyProject?.tasks ?? [])
      .map((task: { task_id?: string | null }) => task.task_id)
      .filter((taskId: string | null | undefined): taskId is string =>
        Boolean(taskId)
      );

    if (taskIdsList.length === 0) {
      if (needsRemoteHistoryHydration) {
        projectStore.updateProject(projectId, {
          metadata: { remoteHistoryHydrationPending: false },
        });
        return;
      }
      projectStore.appendInitChatStore(projectId);
      return;
    }

    projectStore.setProjectNavLead(
      projectId,
      getSessionNavLeadFromHistoryProject(historyProject)
    );

    const firstTask = historyProject.tasks[0];
    const taskQuestionsById = buildTaskQuestionsById(historyProject?.tasks);
    if (needsRemoteHistoryHydration) {
      await projectStore.mergeProjectHistory(
        projectId,
        historyProject.tasks,
        firstTask?.question || historyProject.last_prompt || ''
      );
      return;
    }
    await projectStore.loadProjectFromHistory(
      taskIdsList,
      firstTask?.question || historyProject.last_prompt || '',
      projectId,
      firstTask?.id != null ? String(firstTask.id) : undefined,
      historyProject.project_name,
      undefined,
      taskQuestionsById,
      computeProjectFreshnessAnchor(historyProject)
    );
  } catch (error) {
    console.error(`Failed to load Project ${projectId} from history:`, error);
    if (!projectStore.peekActiveChatStore(projectId)) {
      projectStore.appendInitChatStore(projectId);
    }
  }
}
