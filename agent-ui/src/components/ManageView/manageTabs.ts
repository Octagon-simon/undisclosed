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
 * The space-scoped "Manage" surfaces (Context · Scheduled · Dispatch), grouped
 * into one view with internal tabs in the editor-first shell. Each maps to an
 * existing `WorkspaceTab`, so the underlying views + their state are reused
 * as-is; the Manage chrome just presents them as tabs. See
 * EDITOR_FIRST_SHELL_PLAN.md (Phase 2).
 */

import type { WorkspaceTabId } from '@/store/pageTabStore';
import { Cast, Inbox, Zap, type LucideIcon } from 'lucide-react';

export interface ManageTabDef {
  /** Underlying WorkspaceTab id the Manage tab drives. */
  tab: Extract<WorkspaceTabId, 'inbox' | 'triggers' | 'dispatch'>;
  /** i18n key for the label. */
  labelKey: string;
  Icon: LucideIcon;
}

export const MANAGE_TABS: readonly ManageTabDef[] = [
  { tab: 'inbox', labelKey: 'layout.context-tab', Icon: Inbox },
  { tab: 'triggers', labelKey: 'layout.scheduled-tab', Icon: Zap },
  { tab: 'dispatch', labelKey: 'layout.dispatch-tab', Icon: Cast },
] as const;

export const MANAGE_TAB_IDS = MANAGE_TABS.map((m) => m.tab) as ReadonlyArray<
  ManageTabDef['tab']
>;

export function isManageTab(tab: WorkspaceTabId): tab is ManageTabDef['tab'] {
  return (MANAGE_TAB_IDS as readonly string[]).includes(tab);
}
