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
 * Editor-first "Editor view" (Antigravity-style): the code editor is the
 * primary canvas with Undisclosed's rich agent panel (`RightAgentPanel`) docked on
 * the right.
 *
 * The inversion vs Antigravity: Antigravity embeds its agent panel inside the
 * VS Code fork; here we embed VS Code (code-server, in `CodeAgentWorkspace`)
 * and dock Undisclosed's OWN chat/agent UI to the right — native React, so it can be
 * richer and fully under our control.
 */

import CodeAgentWorkspace from '@/components/CodeAgentWorkspace';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { PanelRightOpen } from 'lucide-react';
import { useState } from 'react';
import RightAgentPanel from './RightAgentPanel';

export default function CodeWorkspaceView({ active }: { active: boolean }) {
  const [dockOpen, setDockOpen] = useState(true);

  return (
    <div className="relative flex h-full min-h-0 w-full min-w-0 overflow-hidden">
      {/* Editor canvas (persistent iframe) */}
      <div className="min-h-0 min-w-0 flex-1">
        <CodeAgentWorkspace active={active} />
      </div>

      {/* Rich right-docked agent panel. Only mounted while the editor is
          visible so we don't run a second ChatBox (and its timers) alongside
          the normal workforce chat on other tabs. The editor iframe on the
          left stays mounted regardless — that's what needs to persist. */}
      {active && dockOpen ? (
        <RightAgentPanel onCollapse={() => setDockOpen(false)} />
      ) : null}

      {active && !dockOpen ? (
        <div className="absolute right-2 top-2 z-10">
          <Button
            variant="outline"
            size="sm"
            buttonContent="icon-only"
            onClick={() => setDockOpen(true)}
            aria-label="Open agent panel"
            className={cn('shadow-button-shadow')}
          >
            <PanelRightOpen className="h-4 w-4" />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
