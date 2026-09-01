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
 * Shared timeline row types + the narration row renderer, split out of
 * `TaskWorkLogAccordion` so both it and `ActivityTraceCard` can consume the
 * same paired-tool-call timeline without importing from each other.
 */

import ShinyText from '@/components/ui/ShinyText/ShinyText';
import { cn } from '@/lib/utils';
import { memo } from 'react';

export type ToolItem = {
  kind: 'tool';
  id: string;
  rowTitle: string;
  toolkitName: string;
  method: string;
  /** Concatenated input + output (markdown-rendered when expanded). */
  detail: string;
  /** The tool call request/arguments (from ACTIVATE_TOOLKIT). */
  input: string;
  /** The tool call response/result (from DEACTIVATE_TOOLKIT). */
  output: string;
  status: 'running' | 'done';
};

export type MessageItem = {
  kind: 'message';
  id: string;
  text: string;
  source: 'reasoning' | 'notice' | 'toolkit_message';
  /**
   * `running` is true while the agent action that emitted this narration is
   * still in flight (e.g. the matching tool hasn't deactivated yet). Used to
   * shimmer the inline text and to drive the live status row.
   */
  running: boolean;
  /** Stable handle so DEACTIVATE_TOOLKIT can flip the sibling narration off. */
  pairKey: string | null;
};

export type TimelineItem = ToolItem | MessageItem;

const TOOL_INLINE_PREVIEW_MAX = 200;

/** Uppercase the first character of agent narration so rows read cleanly. */
function capitalizeFirst(text: string): string {
  if (!text) return text;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function truncateText(text: string, max: number): string {
  const t = text.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

export const InlineMessageRow = memo(function InlineMessageRow({
  text,
  source,
  running,
}: {
  text: string;
  source: MessageItem['source'];
  running: boolean;
}) {
  const display = capitalizeFirst(
    source === 'toolkit_message'
      ? truncateText(text, TOOL_INLINE_PREVIEW_MAX)
      : text
  );
  // Reasoning is the agent's primary narration ("open DuckDuckGo to search
  // for…"); render at default text intensity. Notices and toolkit-message
  // narration stay subtle so the eye stays on tool titles + reasoning.
  const colorClass =
    source === 'reasoning'
      ? 'text-ds-text-neutral-subtle-default'
      : 'text-ds-text-neutral-default-default';
  try {
    // eslint-disable-next-line no-console
    console.debug('[INLINE MESSAGE ROW]', { text: display.slice(0, 120), source, running });
  } catch {}
  return (
    <div className="w-full min-w-0">
      {running ? (
        <ShinyText
          text={display}
          speed={2.5}
          className={cn(
            'whitespace-pre-wrap break-words !text-label-sm font-normal',
            colorClass
          )}
        />
      ) : (
        <span
          className={cn(
            'm-0 whitespace-pre-wrap break-words !text-label-sm font-medium',
            colorClass
          )}
        >
          {display}
        </span>
      )}
    </div>
  );
});
InlineMessageRow.displayName = 'InlineMessageRow';
