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
 * Panel-native Automations (triggers) surface for the embedded agent.
 *
 * This is a SURFACING layer, not a rebuild: it wraps the SAME
 * `components/Trigger` panel the desktop workspace mounts (`pages/Workspace.tsx`
 * -> `<TriggerPanel>`), backed by the SAME store (`store/triggerStore`) and API
 * (`service/triggerApi` -> `/api/v1/trigger/*`). The only thing it adds is the
 * handful of local UI-state values that the classic page keeps at page level
 * (sort key, selected trigger, execution-logs drawer, create dialog), so the
 * component is self-contained and can be dropped into a narrow panel body.
 */

import TriggerPanel from '@/components/Trigger';
import {
  EXECUTION_LOGS_OPEN_STORAGE_KEY,
  type TriggerSortKey,
} from '@/components/Trigger/Triggers';
import { useProjectStore } from '@/store/projectStore';
import { useEffect, useState } from 'react';

export default function AgentTriggers() {
  const activeProjectId = useProjectStore((s) => s.activeProjectId);

  const [sortBy, setSortBy] = useState<TriggerSortKey>('createdAt');
  const [selectedTriggerId, setSelectedTriggerId] = useState<number | null>(
    null
  );
  const [isExecutionLogsOpen, setExecutionLogsOpen] = useState(() => {
    if (typeof window === 'undefined') {
      return false;
    }
    return (
      window.localStorage.getItem(EXECUTION_LOGS_OPEN_STORAGE_KEY) === 'true'
    );
  });
  const [isDialogOpen, setDialogOpen] = useState(false);

  // Execution logs are per-trigger, so drop the selection when the active
  // conversation changes (mirrors the workspace page's behaviour).
  useEffect(() => {
    setSelectedTriggerId(null);
  }, [activeProjectId]);

  // Remember the drawer's open/closed preference across remounts, same key the
  // workspace uses so the choice is shared.
  useEffect(() => {
    window.localStorage.setItem(
      EXECUTION_LOGS_OPEN_STORAGE_KEY,
      String(isExecutionLogsOpen)
    );
  }, [isExecutionLogsOpen]);

  return (
    <TriggerPanel
      className="h-full"
      sortBy={sortBy}
      onSortByChange={setSortBy}
      selectedTriggerId={selectedTriggerId}
      onSelectedTriggerIdChange={setSelectedTriggerId}
      isExecutionLogsOpen={isExecutionLogsOpen}
      onExecutionLogsOpenChange={setExecutionLogsOpen}
      isDialogOpen={isDialogOpen}
      onDialogOpenChange={setDialogOpen}
    />
  );
}
