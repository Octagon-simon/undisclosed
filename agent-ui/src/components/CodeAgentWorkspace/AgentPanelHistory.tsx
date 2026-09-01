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
 * History body for the editor-first agent panel: the conversation list (the
 * former left-nav "projects" list) that *replaces* the panel's conversation
 * view. Selecting a conversation activates + hydrates it and returns to the
 * conversation view. Reuses the same `ProjectNavList` + shared `projectNav`
 * derivation as the classic sidebar, so the two never drift.
 */

import { ProjectNavList } from '@/components/ProjectPageSidebar/ProjectNavList';
import {
  buildNavProjects,
  ensureProjectLoaded,
} from '@/components/ProjectPageSidebar/projectNav';
import { useProjectNavActions } from '@/components/ProjectPageSidebar/useProjectNavActions';
import { useProjectRuntimeStore } from '@/store/projectRuntimeStore';
import {
  getVisibleProjectMetasForSpace,
  useSpaceStore,
} from '@/store/spaceStore';
import { useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';

export default function AgentPanelHistory({
  onSelected,
  onNewProject,
}: {
  /** Called after a conversation is activated so the panel can leave History. */
  onSelected: () => void;
  /** Start a fresh conversation (same handler as the header `+ New`). */
  onNewProject: () => void;
}) {
  const { t } = useTranslation();
  const projectStore = useProjectRuntimeStore();
  const activeProjectId = useProjectRuntimeStore((s) => s.activeProjectId);
  const navLeadByProjectId = useProjectRuntimeStore(
    (s) => s.navLeadByProjectId
  );
  const historyLoadingProjectIds = useProjectRuntimeStore(
    (s) => s.historyLoadingProjectIds
  );
  const activeSpaceId = useSpaceStore((s) => s.activeSpaceId);
  const projectsBySpaceId = useSpaceStore((s) => s.projectsBySpaceId);
  const {
    pinnedProjectIds,
    handlePinProject,
    requestDeleteProject,
    requestAchieveProject,
    dialogs,
  } = useProjectNavActions();

  // Titles are generated server-side a few seconds into a run (from the first
  // message), and single-agent runs don't push a live title event — so a fresh
  // conversation stays "New Project" in the store until something re-reads the
  // server. Opening History is exactly that moment: pull the latest project
  // names for the active folder so titles aren't stale.
  useEffect(() => {
    if (!activeSpaceId) return;
    void useSpaceStore.getState().syncProjectsFromServer(activeSpaceId);
  }, [activeSpaceId]);

  const projectMetas = useMemo(
    () => getVisibleProjectMetasForSpace(projectsBySpaceId, activeSpaceId),
    [projectsBySpaceId, activeSpaceId]
  );

  const navProjects = useMemo(
    () =>
      buildNavProjects({
        projectMetas,
        navLeadByProjectId,
        historyLoadingProjectIds,
        pinnedProjectIds,
        projectStore,
        newProjectLabel: t('layout.new-project'),
      }),
    [
      projectMetas,
      navLeadByProjectId,
      historyLoadingProjectIds,
      pinnedProjectIds,
      projectStore,
      t,
    ]
  );

  const handleSelect = async (projectId: string) => {
    projectStore.setActiveProject(projectId);
    // Pin this conversation as the folder's last-visited so a later folder
    // switch resumes THIS exact conversation (not just the most recent one).
    // setActiveProject records it too, but only when the project shell already
    // carries its spaceId — recording it here with the current active space is
    // an explicit guarantee.
    if (activeSpaceId) {
      useSpaceStore.getState().setLastVisitedProject(activeSpaceId, projectId);
    }
    await ensureProjectLoaded(projectStore, projectId);
    onSelected();
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {navProjects.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6 text-center">
          <div className="text-label-xs text-ds-text-neutral-subtle-default">
            No conversations yet. Start one with{' '}
            <span className="font-semibold text-ds-text-neutral-default-default">
              + New
            </span>
            .
          </div>
        </div>
      ) : (
        <ProjectNavList
          className="flex min-h-0 flex-1 flex-col"
          projects={navProjects}
          activeProjectId={activeProjectId}
          onProjectClick={handleSelect}
          onDeleteProject={requestDeleteProject}
          onAchieveProject={requestAchieveProject}
          onPinProject={handlePinProject}
          onNewProject={onNewProject}
          folded={false}
        />
      )}
      {dialogs}
    </div>
  );
}
