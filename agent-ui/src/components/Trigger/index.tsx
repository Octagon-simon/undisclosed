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

import { TriggerDialog } from '@/components/Trigger/TriggerDialog';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { TooltipSimple } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { proxyFetchWorkspaceTriggers } from '@/service/triggerApi';
import { useProjectStore } from '@/store/projectStore';
import { useSpaceStore } from '@/store/spaceStore';
import { useTriggerStore } from '@/store/triggerStore';
import {
  ArrowUpDown,
  Plus,
  RefreshCw,
  SquareChevronRight,
  SquareCode,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Trigger } from '@/types';
import Overview, { sortTriggersList, type TriggerSortKey } from './Triggers';

type TriggerPanelProps = {
  className?: string;
  sortBy: TriggerSortKey;
  onSortByChange: (sortBy: TriggerSortKey) => void;
  selectedTriggerId: number | null;
  onSelectedTriggerIdChange: (id: number | null) => void;
  isExecutionLogsOpen: boolean;
  onExecutionLogsOpenChange: (open: boolean) => void;
  isDialogOpen: boolean;
  onDialogOpenChange: (open: boolean) => void;
};

export default function TriggerPanel({
  className,
  sortBy,
  onSortByChange,
  selectedTriggerId,
  onSelectedTriggerIdChange,
  isExecutionLogsOpen,
  onExecutionLogsOpenChange,
  isDialogOpen,
  onDialogOpenChange,
}: TriggerPanelProps) {
  const { t } = useTranslation();
  const { triggers, setTriggers } = useTriggerStore();
  const activeProjectId = useProjectStore((state) => state.activeProjectId);
  const activeSpaceId = useSpaceStore((state) => state.activeSpaceId);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Fetch the ACTIVE WORKSPACE's triggers. Automations are attached either to
  // the whole folder-space (visible across every conversation in it) or to one
  // conversation. We never fall back to a global, unscoped list: an unscoped
  // call would leak another workspace's triggers into this screen. Within the
  // workspace we show the workspace-scoped triggers plus the conversation-scoped
  // ones that belong to the conversation currently open.
  const refreshTriggers = useCallback(async () => {
    if (!activeSpaceId) {
      setTriggers([]);
      return;
    }
    setIsRefreshing(true);
    try {
      const response = await proxyFetchWorkspaceTriggers(
        activeSpaceId,
        undefined,
        undefined,
        1,
        200
      );
      const items = ((response.items || []) as Trigger[]).filter(
        (trigger: Trigger) =>
          trigger.scope === 'workspace' ||
          trigger.project_id === activeProjectId
      );
      setTriggers(items);
    } catch (error) {
      console.error('Failed to fetch triggers:', error);
      toast.error(
        t('triggers.failed-to-load', { defaultValue: 'Failed to load triggers' })
      );
    } finally {
      setIsRefreshing(false);
    }
  }, [activeSpaceId, activeProjectId, setTriggers, t]);

  // Refresh on entry (mount) and whenever the active project changes. This is
  // the "refresh on page enter" behaviour for the Automations screen.
  useEffect(() => {
    void refreshTriggers();
  }, [refreshTriggers]);

  const sortedTriggersForHeader = useMemo(
    () => sortTriggersList(triggers, sortBy),
    [triggers, sortBy]
  );

  const triggerSortLabel = useMemo(() => {
    switch (sortBy) {
      case 'createdAt':
        return t('triggers.created-time');
      case 'lastExecutionTime':
        return t('triggers.last-execution-label');
      case 'tokens':
        return t('triggers.token-cost');
      default:
        return t('triggers.created-time');
    }
  }, [sortBy, t]);

  return (
    <div
      className={cn(
        'flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden',
        className
      )}
    >
      <div className="border-b-1 flex w-full shrink-0 items-center justify-between gap-2 border-x-0 border-t-0 border-solid border-ds-border-neutral-subtle-default px-2 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2 px-1 text-body-md font-bold text-ds-text-neutral-muted-default">
          <span className="truncate">{t('triggers.title')}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <TooltipSimple
            content={t('triggers.refresh', { defaultValue: 'Refresh' })}
            variant="instant"
            side="bottom"
          >
            <Button
              variant="ghost"
              size="icon"
              className="opacity-70"
              aria-label={t('triggers.refresh', { defaultValue: 'Refresh' })}
              disabled={isRefreshing}
              onClick={() => void refreshTriggers()}
            >
              <RefreshCw
                className={cn('h-4 w-4', isRefreshing && 'animate-spin')}
              />
            </Button>
          </TooltipSimple>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                buttonContent="text"
                size="sm"
                className="rounded-lg"
              >
                {triggerSortLabel}
                <ArrowUpDown />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onSortByChange('createdAt')}>
                {t('triggers.created-time')}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => onSortByChange('lastExecutionTime')}
              >
                {t('triggers.last-execution-label')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            variant="primary"
            size="sm"
            className="items-center justify-center rounded-lg"
            onClick={() => onDialogOpenChange(true)}
          >
            <Plus />
            {t('triggers.create')}
          </Button>
          <TooltipSimple
            content={
              isExecutionLogsOpen
                ? t('triggers.fold-execution-logs')
                : t('triggers.open-execution-logs')
            }
            variant="instant"
            side="bottom"
          >
            <Button
              variant="ghost"
              size="icon"
              className="opacity-70"
              disabled={sortedTriggersForHeader.length === 0}
              onClick={() => {
                if (isExecutionLogsOpen) {
                  onExecutionLogsOpenChange(false);
                  return;
                }

                if (!selectedTriggerId && sortedTriggersForHeader.length > 0) {
                  onSelectedTriggerIdChange(sortedTriggersForHeader[0].id);
                }

                onExecutionLogsOpenChange(true);
              }}
            >
              {isExecutionLogsOpen ? (
                <SquareChevronRight className="h-4 w-4" />
              ) : (
                <SquareCode className="h-4 w-4" />
              )}
            </Button>
          </TooltipSimple>
          <TriggerDialog
            selectedTrigger={null}
            isOpen={isDialogOpen}
            onOpenChange={onDialogOpenChange}
            onTriggerCreated={() => void refreshTriggers()}
          />
        </div>
      </div>
      {/* The list is backed by the REST API (`/api/v1/trigger/*`), NOT the
          execution WebSocket, so it must stay interactive even when the live
          event socket is down. Gating it on `wsConnectionStatus` greyed out the
          whole list and killed pointer events with `pointer-events-none` — and
          because the EMBEDDED panel never runs `useExecutionSubscription`, the
          status stayed 'disconnected' forever, leaving Automations permanently
          read-only (rows unclickable, no Slack select, no webhook copy). The
          socket input is gone; interactivity no longer depends on it. */}
      <div className="min-h-0 w-full flex-1">
        <Overview
          sortBy={sortBy}
          selectedTriggerId={selectedTriggerId}
          onSelectedTriggerIdChange={onSelectedTriggerIdChange}
          isExecutionLogsOpen={isExecutionLogsOpen}
          onExecutionLogsOpenChange={onExecutionLogsOpenChange}
          onRefresh={refreshTriggers}
        />
      </div>
    </div>
  );
}
