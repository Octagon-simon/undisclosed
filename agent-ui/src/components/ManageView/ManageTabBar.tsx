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
 * Internal tab bar for the grouped "Manage" view (Context · Scheduled ·
 * Dispatch). Rendered above the active Manage surface in the editor-first
 * shell so the three space-scoped surfaces read as one view with tabs, while
 * each still renders its existing component + state from `Workspace.tsx`.
 */

import { cn } from '@/lib/utils';
import { usePageTabStore } from '@/store/pageTabStore';
import { useTranslation } from 'react-i18next';
import { MANAGE_TABS } from './manageTabs';

export default function ManageTabBar() {
  const { t } = useTranslation();
  const activeWorkspaceTab = usePageTabStore((s) => s.activeWorkspaceTab);
  const setActiveWorkspaceTab = usePageTabStore((s) => s.setActiveWorkspaceTab);

  return (
    <div
      role="tablist"
      aria-label={t('layout.manage-tab', { defaultValue: 'Manage' })}
      className="flex shrink-0 items-center gap-1 px-2 pb-1 pt-2"
    >
      {MANAGE_TABS.map(({ tab, labelKey, Icon }) => {
        const isActive = activeWorkspaceTab === tab;
        return (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => setActiveWorkspaceTab(tab)}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-body-sm font-semibold transition-colors duration-150',
              isActive
                ? 'bg-ds-bg-neutral-muted-default text-ds-text-neutral-default-default'
                : 'text-ds-text-neutral-subtle-default hover:bg-ds-bg-neutral-default-hover hover:text-ds-text-neutral-default-default'
            )}
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            {t(labelKey)}
          </button>
        );
      })}
    </div>
  );
}
