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

import { formatTokenCount, type ContextWindowLevel } from '@/lib/contextWindow';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';
import { Sparkles, TriangleAlert, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

export interface ContextWindowNoticeProps {
  /** Stable key for this notice (task + threshold + window); drives the timer. */
  id: string;
  /** Tokens in the latest request (input + output). */
  used: number;
  /** Resolved context window for the active model. */
  windowTokens: number;
  level: Exclude<ContextWindowLevel, 'ok'>;
  onGenerateHandoff: () => void;
  onStartNewChat: () => void;
  onDismiss: () => void;
  /** Auto-dismiss delay in ms; pass 0 to keep it until dismissed. */
  autoDismissMs?: number;
}

/**
 * Token-window nudge shown above the composer when the live conversation is
 * approaching its model's context window. Fades in, holds, and auto-dismisses;
 * it never blocks sending - it points the user at the token-cheap exit
 * (a handoff) and the fresh-chat bump.
 */
export function ContextWindowNotice({
  id,
  used,
  windowTokens,
  level,
  onGenerateHandoff,
  onStartNewChat,
  onDismiss,
  autoDismissMs = 12_000,
}: ContextWindowNoticeProps) {
  const { t } = useTranslation();
  const [hovered, setHovered] = useState(false);
  const isCritical = level === 'critical';

  // Reset the hold timer whenever a new notice mounts (or the threshold
  // escalates), and pause while the pointer is over it so a user mid-read
  // doesn't lose the banner out from under them.
  useEffect(() => {
    if (hovered || autoDismissMs <= 0) return;
    const timer = window.setTimeout(onDismiss, autoDismissMs);
    return () => window.clearTimeout(timer);
  }, [id, hovered, autoDismissMs, onDismiss]);

  const message = t('chat.context-window-warning', {
    defaultValue:
      'This conversation is nearing its model window ({{used}} of {{window}} context). Consider generating a handoff and continuing in a new chat.',
    used: formatTokenCount(used),
    window: formatTokenCount(windowTokens),
  });

  return (
    <motion.div
      key={id}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      transition={{ duration: 0.45, ease: [0.23, 1, 0.32, 1] }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      role="status"
      className={cn(
        'pointer-events-auto flex w-full items-start gap-3 rounded-xl border px-4 py-2.5 shadow-sm',
        isCritical
          ? 'border-text-error/30 bg-surface-error-subtle text-text-error'
          : 'border-border-warning bg-surface-warning text-text-warning'
      )}
    >
      <span className="mt-0.5 shrink-0">
        {isCritical ? (
          <TriangleAlert className="size-4" aria-hidden />
        ) : (
          <Sparkles className="size-4" aria-hidden />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-body-sm font-medium leading-snug">{message}</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
          <button
            type="button"
            onClick={onGenerateHandoff}
            className={cn(
              'text-body-sm font-semibold underline underline-offset-4',
              isCritical ? 'text-text-error' : 'text-text-heading'
            )}
          >
            {t('chat.context-window-generate-handoff', {
              defaultValue: 'Generate handoff',
            })}
          </button>
          <button
            type="button"
            onClick={onStartNewChat}
            className="text-body-sm font-medium text-text-secondary underline-offset-4 hover:text-text-primary hover:underline"
          >
            {t('chat.context-window-start-new-chat', {
              defaultValue: 'Start new chat',
            })}
          </button>
        </div>
      </div>

      <button
        type="button"
        onClick={onDismiss}
        aria-label={t('chat.context-window-dismiss', {
          defaultValue: 'Dismiss context window notice',
        })}
        className="flex size-7 shrink-0 items-center justify-center rounded-md text-icon-secondary transition-colors hover:bg-fill-fill-transparent-hover hover:text-icon-primary"
      >
        <X className="size-4" />
      </button>
    </motion.div>
  );
}
