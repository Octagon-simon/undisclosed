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

import { GlobalSearchDialog } from '@/components/GlobalSearch';
import { Button } from '@/components/ui/button';
import { TooltipSimple } from '@/components/ui/tooltip';
import { ensureScratchSpaceWorkspaceBinding } from '@/lib/scratchSpaceWorkspace';
import {
  getContextTabBindingLabel,
  isUnboundUntitledSpace,
} from '@/lib/spaceLabel';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/store/authStore';
import type { ChatStore } from '@/store/chatStore';
import { usePageTabStore } from '@/store/pageTabStore';
import { useProjectRuntimeStore } from '@/store/projectRuntimeStore';
import {
  getVisibleProjectMetasForSpace,
  useSpaceStore,
} from '@/store/spaceStore';
import { useTriggerStore } from '@/store/triggerStore';
import { Cast, Inbox, LayoutGrid, Plus, Zap, ZapOff } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  NavTab,
  NavTabReconnectSuffix,
  triggerListenerLeadIconClass,
} from './NavTab';
import { ProjectNavList } from './ProjectNavList';
import {
  buildNavProjects,
  ensureProjectLoaded as ensureProjectLoadedShared,
  projectHasStarted as projectHasStartedShared,
  shouldShowProjectInNavList as shouldShowProjectInNavListShared,
} from './projectNav';
import { useProjectNavActions } from './useProjectNavActions';

export interface ProjectPageSidebarProps {
  chatStore: ChatStore | null;
  className?: string;
}

let didAttemptBootSessionResume = false;

export default function ProjectPageSidebar({
  chatStore: _chatStore,
  className,
}: ProjectPageSidebarProps) {
  const activeWorkspaceTab = usePageTabStore((s) => s.activeWorkspaceTab);
  const setActiveWorkspaceTab = usePageTabStore((s) => s.setActiveWorkspaceTab);
  const requestWorkspaceChatFocus = usePageTabStore(
    (s) => s.requestWorkspaceChatFocus
  );
  const requestOpenTriggerAddDialog = usePageTabStore(
    (s) => s.requestOpenTriggerAddDialog
  );
  const projectSidebarFolded = usePageTabStore((s) => s.projectSidebarFolded);
  const unviewedTabs = usePageTabStore((s) => s.unviewedTabs);
  const inboxUnviewedForProjects = usePageTabStore(
    (s) => s.inboxUnviewedForProjects
  );
  const wsConnectionStatus = useTriggerStore((s) => s.wsConnectionStatus);
  const triggerReconnect = useTriggerStore((s) => s.triggerReconnect);
  const triggersListenerConnected = wsConnectionStatus === 'connected';
  const projectStore = useProjectRuntimeStore();
  const navLeadByProjectId = useProjectRuntimeStore(
    (s) => s.navLeadByProjectId
  );
  const historyLoadingProjectIds = useProjectRuntimeStore(
    (s) => s.historyLoadingProjectIds
  );
  const activeProjectId = projectStore.activeProjectId;
  const activeSpaceId = useSpaceStore((s) => s.activeSpaceId);
  const spacesById = useSpaceStore((s) => s.spaces);
  const projectsBySpaceId = useSpaceStore((s) => s.projectsBySpaceId);
  const projectMetasForActiveSpace = useMemo(() => {
    if (!activeSpaceId) return [];
    return getVisibleProjectMetasForSpace(projectsBySpaceId, activeSpaceId);
  }, [activeSpaceId, projectsBySpaceId]);
  const folderTabHasUnviewedFiles =
    !!activeProjectId && inboxUnviewedForProjects.has(activeProjectId);
  const { t } = useTranslation();
  const [globalSearchOpen, setGlobalSearchOpen] = useState(false);
  // Pin / delete / archive ("end") row actions + their confirm dialogs are
  // shared with the editor-first `AgentPanelHistory` via this hook.
  const {
    pinnedProjectIds,
    handlePinProject,
    requestDeleteProject,
    requestAchieveProject,
    dialogs: projectNavDialogs,
  } = useProjectNavActions();

  const scheduledTabLabel = t('layout.scheduled-tab');
  const triggersTabTooltip = scheduledTabLabel;

  const triggersTabAriaLabel = useMemo(() => {
    const base = scheduledTabLabel;
    if (triggersListenerConnected) return base;
    if (wsConnectionStatus === 'connecting') {
      return `${base}, ${t('layout.triggers-connecting')}`;
    }
    return `${base}, ${t('layout.triggers-disconnected')}`;
  }, [scheduledTabLabel, t, triggersListenerConnected, wsConnectionStatus]);

  const email = useAuthStore((s) => s.email);
  const userId = useAuthStore((s) => s.user_id);
  const codeEditorEnabled = useAuthStore((s) => s.codeEditorEnabled);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setGlobalSearchOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const activeSpace = activeSpaceId ? spacesById[activeSpaceId] : null;
  const isActiveSpaceUnbound = isUnboundUntitledSpace(activeSpace, t);
  const contextTabBinding = useMemo(
    () => getContextTabBindingLabel(activeSpace, t),
    [activeSpace, t]
  );

  useEffect(() => {
    if (
      !activeSpace ||
      activeSpace.sourceType !== 'blank' ||
      activeSpace.rootPath
    ) {
      return;
    }
    void ensureScratchSpaceWorkspaceBinding({
      email,
      userId,
      space: activeSpace,
    });
  }, [
    activeSpace,
    activeSpace?.id,
    activeSpace?.rootPath,
    activeSpace?.sourceType,
    email,
    userId,
  ]);

  const projectHasStarted = useCallback(
    (projectId: string) => projectHasStartedShared(projectStore, projectId),
    [projectStore]
  );

  const shouldShowProjectInNavList = useCallback(
    (project: (typeof projectMetasForActiveSpace)[number]) =>
      shouldShowProjectInNavListShared(projectStore, project),
    [projectStore]
  );

  const isProjectNavSelectionActive =
    activeWorkspaceTab === 'project' || activeWorkspaceTab === 'new-project';

  const ensureProjectLoaded = useCallback(
    (projectId: string) => ensureProjectLoadedShared(projectStore, projectId),
    [projectStore]
  );

  const selectProject = useCallback(
    async (projectId: string) => {
      projectStore.setActiveProject(projectId);
      const needsRemoteHistoryHydration =
        projectStore.getProjectById(projectId)?.metadata
          ?.remoteHistoryHydrationPending === true;

      // Already loaded — flip to the live Project shell immediately.
      if (
        projectStore.peekActiveChatStore(projectId) &&
        !needsRemoteHistoryHydration
      ) {
        setActiveWorkspaceTab('project');
        return;
      }

      // Load history first, then choose the right shell. Avoids briefly
      // showing 'project' while empty (which the Session redirect bounces
      // to 'workforce', producing a flicker on slow loads).
      await ensureProjectLoaded(projectId);

      // History-loaded projects are known to have content. Trust the project
      // type tag (set by createProject(REPLAY)) over `projectHasStarted`,
      // which can read a transiently-empty chatStore during the brief
      // window between loadProjectFromHistory's remove+create rebuild.
      const meta = useSpaceStore.getState().getProjectMeta(projectId);
      const projectInStore = projectStore.getProjectById(projectId);
      const isReplayProject = Boolean(
        meta?.metadata?.tags?.includes('replay') ||
        projectInStore?.metadata?.tags?.includes('replay')
      );
      setActiveWorkspaceTab(
        isReplayProject || projectHasStarted(projectId)
          ? 'project'
          : 'new-project'
      );
    },
    [
      ensureProjectLoaded,
      projectHasStarted,
      projectStore,
      setActiveWorkspaceTab,
    ]
  );

  // Boot-time session resume: reopen the last visited Project (the way an
  // editor reopens its last workspace) instead of landing on the empty home
  // tab. One-shot per renderer boot (launch or reload; the flag is module
  // scoped so sidebar remounts within a session never re-trigger it), and
  // only from the pristine boot state (default tab, no active Project), so
  // deliberately navigating home later is never hijacked. Uses the same
  // path as clicking the Project in the sidebar.
  useEffect(() => {
    if (didAttemptBootSessionResume) return;
    // In editor-first mode, Workspace.tsx owns boot navigation (lands on the
    // code editor); don't compete.
    if (codeEditorEnabled) return;
    didAttemptBootSessionResume = true;

    if (activeWorkspaceTab !== 'workforce') return;
    if (projectStore.activeProjectId) return;
    if (!activeSpaceId) return;
    const lastVisitedId =
      useSpaceStore.getState().lastVisitedProjectBySpace[activeSpaceId];
    if (!lastVisitedId) return;
    const lastVisitedMeta = projectMetasForActiveSpace.find(
      (project) => project.id === lastVisitedId
    );
    if (!lastVisitedMeta || !shouldShowProjectInNavList(lastVisitedMeta)) {
      return;
    }
    void selectProject(lastVisitedId);
    // One-shot boot effect: later changes to these values must not
    // re-trigger a resume.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const navProjects = useMemo(
    () =>
      buildNavProjects({
        projectMetas: projectMetasForActiveSpace,
        navLeadByProjectId,
        historyLoadingProjectIds,
        pinnedProjectIds,
        projectStore,
        newProjectLabel: t('layout.new-project'),
      }),
    [
      historyLoadingProjectIds,
      navLeadByProjectId,
      pinnedProjectIds,
      projectMetasForActiveSpace,
      projectStore,
      t,
    ]
  );

  const handleNewProject = useCallback(() => {
    projectStore.setActiveProject(null);
    setActiveWorkspaceTab('new-project');
    requestWorkspaceChatFocus();
  }, [projectStore, requestWorkspaceChatFocus, setActiveWorkspaceTab]);

  const openInboxTab = useCallback(() => {
    let projectId = activeProjectId;

    if (!projectId && activeSpaceId) {
      const spaceStore = useSpaceStore.getState();
      const projectsInSpace = spaceStore.getProjectsForSpace(activeSpaceId);
      if (projectsInSpace.length > 0) {
        const lastVisitedProjectId =
          spaceStore.lastVisitedProjectBySpace[activeSpaceId];
        const targetProject =
          projectsInSpace.find(
            (project) => project.id === lastVisitedProjectId
          ) ?? projectsInSpace[0];
        projectId = targetProject.id;
        projectStore.setActiveProject(projectId);
      }
    }

    if (!projectId) {
      toast.error(t('layout.workspace-select-project'));
      return;
    }

    const projectChatStore = projectStore.peekActiveChatStore(projectId);
    const taskId = projectChatStore?.getState().activeTaskId;
    if (taskId) {
      projectChatStore?.getState().setNuwFileNum(taskId, 0);
    }

    setActiveWorkspaceTab('inbox', {
      clearInboxForProjectId: projectId,
    });

    const needsRemoteHistoryHydration =
      projectStore.getProjectById(projectId)?.metadata
        ?.remoteHistoryHydrationPending === true;
    if (
      !projectStore.peekActiveChatStore(projectId) ||
      needsRemoteHistoryHydration
    ) {
      void ensureProjectLoaded(projectId);
    }
  }, [
    activeProjectId,
    activeSpaceId,
    ensureProjectLoaded,
    projectStore,
    setActiveWorkspaceTab,
    t,
  ]);

  return (
    <>
      <GlobalSearchDialog
        open={globalSearchOpen}
        onOpenChange={setGlobalSearchOpen}
      />
      {projectNavDialogs}

      <aside
        className={cn(
          'box-border flex h-full min-h-0 w-full min-w-0 shrink-0 flex-col items-start overflow-hidden rounded-2xl bg-ds-bg-neutral-default-default p-1',
          className
        )}
      >
        <div className="flex h-full min-h-0 w-full min-w-0 max-w-full flex-col overflow-x-hidden">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <div className="flex w-full shrink-0 flex-col gap-1">
              <div className="flex w-full min-w-0 flex-col gap-1">
                <NavTab
                  active={activeWorkspaceTab === 'workforce'}
                  onClick={() => setActiveWorkspaceTab('workforce')}
                  leading={
                    <LayoutGrid className="h-4 w-4 shrink-0" aria-hidden />
                  }
                  label={t('layout.workspace-tab')}
                  tooltip={t('layout.workspace-tab')}
                  tooltipEnabledWhenCollapsed={!projectSidebarFolded}
                  folded={projectSidebarFolded}
                  ariaLabel={t('layout.workspace-tab')}
                  ariaCurrentPage={activeWorkspaceTab === 'workforce'}
                />
                {/* Context/Scheduled/Dispatch live in the top-bar `Manage ▾`
                    when the editor-first shell is on; keep them here otherwise. */}
                {!codeEditorEnabled && (
                  <>
                    <NavTab
                      active={activeWorkspaceTab === 'inbox'}
                      onClick={openInboxTab}
                      disabled={isActiveSpaceUnbound}
                      leading={
                        <span className="relative inline-flex h-4 w-4 shrink-0">
                          <Inbox className="h-4 w-4 shrink-0" aria-hidden />
                          {folderTabHasUnviewedFiles &&
                          !isActiveSpaceUnbound ? (
                            <span
                              className="absolute -right-1 -top-1 h-2 w-2 shrink-0 rounded-full bg-ds-text-error-default-default ease-in-out"
                              aria-hidden
                            />
                          ) : null}
                        </span>
                      }
                      label={t('layout.context-tab')}
                      trailing={
                        contextTabBinding ? (
                          <div
                            className={cn(
                              'flex shrink-0 flex-col items-center rounded-xl bg-ds-bg-neutral-muted-default px-1.5',
                              contextTabBinding.tooltip && 'pointer-events-auto'
                            )}
                            onClick={
                              contextTabBinding.tooltip
                                ? (e) => e.stopPropagation()
                                : undefined
                            }
                          >
                            {contextTabBinding.tooltip ? (
                              <TooltipSimple
                                content={contextTabBinding.tooltip}
                                side="top"
                                sideOffset={8}
                              >
                                <span className="text-label-xs font-medium text-ds-text-neutral-muted-default">
                                  {contextTabBinding.label}
                                </span>
                              </TooltipSimple>
                            ) : (
                              <span className="text-label-xs font-medium text-ds-text-neutral-muted-default">
                                {contextTabBinding.label}
                              </span>
                            )}
                          </div>
                        ) : undefined
                      }
                      tooltip={
                        isActiveSpaceUnbound
                          ? t('layout.context-tab-unbound-tooltip')
                          : (contextTabBinding?.tooltip ??
                            t('layout.context-tab'))
                      }
                      // Render the tooltip even when disabled so users get a hint
                      // instead of relying on the toast that only fires on click.
                      tooltipEnabledWhenCollapsed={!projectSidebarFolded}
                      folded={projectSidebarFolded}
                      ariaLabel={t('layout.context-tab')}
                      ariaCurrentPage={activeWorkspaceTab === 'inbox'}
                    />
                    <NavTab
                      layout="split"
                      active={activeWorkspaceTab === 'triggers'}
                      onClick={() => setActiveWorkspaceTab('triggers')}
                      leading={
                        triggersListenerConnected ? (
                          <Zap
                            className={cn(
                              'h-4 w-4 shrink-0',
                              triggerListenerLeadIconClass(wsConnectionStatus)
                            )}
                            aria-hidden
                          />
                        ) : (
                          <ZapOff
                            className={cn(
                              'h-4 w-4 shrink-0',
                              triggerListenerLeadIconClass(wsConnectionStatus)
                            )}
                            aria-hidden
                          />
                        )
                      }
                      label={scheduledTabLabel}
                      showNotificationDot={unviewedTabs.has('triggers')}
                      notificationDotTone="attention"
                      notificationDotClassName="h-2 w-2"
                      endAction={
                        triggersListenerConnected ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            buttonContent="icon-only"
                            className={cn(
                              'no-drag mr-1 shrink-0 rounded-xl hover:bg-ds-bg-neutral-strong-default',
                              'focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-border-neutral-default-default'
                            )}
                            aria-label={t('triggers.add-trigger')}
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              requestOpenTriggerAddDialog();
                            }}
                          >
                            <Plus
                              className="h-4 w-4 text-ds-icon-neutral-muted-default"
                              aria-hidden
                            />
                          </Button>
                        ) : (
                          <NavTabReconnectSuffix
                            wsConnectionStatus={wsConnectionStatus}
                            onReconnect={triggerReconnect}
                          />
                        )
                      }
                      tooltip={triggersTabTooltip}
                      tooltipEnabledWhenCollapsed={!projectSidebarFolded}
                      folded={projectSidebarFolded}
                      ariaLabel={triggersTabAriaLabel}
                      ariaCurrentPage={activeWorkspaceTab === 'triggers'}
                    />
                    <NavTab
                      active={activeWorkspaceTab === 'dispatch'}
                      onClick={() => setActiveWorkspaceTab('dispatch')}
                      leading={
                        <Cast className="h-4 w-4 shrink-0" aria-hidden />
                      }
                      label={t('layout.dispatch-tab')}
                      tooltip={t('layout.dispatch-tab')}
                      tooltipEnabledWhenCollapsed={!projectSidebarFolded}
                      folded={projectSidebarFolded}
                      ariaLabel={t('layout.dispatch-tab')}
                      ariaCurrentPage={activeWorkspaceTab === 'dispatch'}
                    />
                  </>
                )}
              </div>
            </div>

            <div className="my-2 px-3">
              <div className="h-px w-full bg-ds-border-neutral-default-default" />
            </div>

            <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
              <ProjectNavList
                className="flex min-h-0 flex-1 flex-col"
                projects={navProjects}
                activeProjectId={
                  isProjectNavSelectionActive ? activeProjectId : null
                }
                onProjectClick={selectProject}
                onDeleteProject={requestDeleteProject}
                onAchieveProject={requestAchieveProject}
                onPinProject={handlePinProject}
                onNewProject={handleNewProject}
                newProjectActive={activeWorkspaceTab === 'new-project'}
                folded={projectSidebarFolded}
              />
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
