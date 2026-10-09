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
 * Boxed "Thought Process" disclosure for a reasoning model's thoughts
 * (reasoning_ content), shown above the final answer. Only rendered when the
 * END message carries reasoning.
 *
 * Phase 1 of the panel revamp (see `agent-panel-integration-plan.md`): the box
 * is the shared `PanelSection` shell, so it is pixel-identical to the Execution
 * Summary box below it. The header row is `Brain` + "Thought Process" + an
 * optional duration pill on the left, and the step count + rotating chevron on
 * the right (`justify-between`). The reasoning renders under a hairline, only
 * while open.
 *
 * The elapsed pill (`durationMs`) and `stepCount` are optional. `UserQueryGroup`
 * feeds `durationMs` from the turn's task timer (`@/lib/taskTime`), the same
 * figure the old work log showed as "Worked for Xs"; a pre-formatted `duration`
 * string is also accepted (used by the stories). When neither is given the header
 * degrades to just the title + chevron.
 */

import ShinyText from '@/components/ui/ShinyText/ShinyText';
import { cn } from '@/lib/utils';
import { AnimatePresence, motion } from 'framer-motion';
import { Brain, ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { Trans } from 'react-i18next';
import { PanelSection, Pill } from './PanelSection';
import { formatSplittingElapsed } from './TokenUtils';

export function ThinkingBlock({
  reasoning,
  duration,
  durationMs,
  stepCount,
  defaultOpen = false,
  running = false,
}: {
  /** Reasoning text; when empty the block does not render at all. */
  reasoning?: string;
  /** Pre-formatted elapsed label, e.g. "Worked for 53s". */
  duration?: string;
  /**
   * Elapsed work time (ms) for the turn, rendered as a localized
   * "Worked for Xs" pill. Preferred over `duration` (a pre-formatted label) and
   * ignored when that is supplied. The same figure the work log shows.
   */
  durationMs?: number;
  /** Number of work-log steps, rendered as "N steps completed". */
  stepCount?: number;
  /** Initial disclosure state. Collapsed by default; pass true to start open. */
  defaultOpen?: boolean;
  /**
   * Live turn, still thinking. The header then reads "Thinking" with the same
   * running shimmer the activity classifier puts on a running step (the loader),
   * instead of the finished "Thought Process" label. Once the turn settles the
   * block falls back to "Thought Process".
   */
  running?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const text = (reasoning ?? '').trim();
  if (!text) return null;

  const stepsLabel =
    typeof stepCount === 'number'
      ? `${stepCount} step${stepCount === 1 ? '' : 's'} completed`
      : null;

  return (
    <PanelSection
      icon={
        <Brain
          className="h-4 w-4 text-ds-text-information-default-default"
          aria-hidden
        />
      }
      title={
        <>
          {running ? (
            // Live: present-continuous "Thinking" with the running shimmer
            // (the same loader the classifier shows for an in-flight step).
            <ShinyText
              text="Thinking"
              speed={2.5}
              className="!text-sm font-medium"
            />
          ) : (
            'Thought Process'
          )}
          {duration ? (
            <Pill>{duration}</Pill>
          ) : typeof durationMs === 'number' && durationMs > 0 ? (
            <Pill>
              <Trans
                i18nKey="chat.worked-for"
                values={{ time: formatSplittingElapsed(durationMs) }}
                components={{ elapsed: <span className="tabular-nums" /> }}
              />
            </Pill>
          ) : null}
        </>
      }
      meta={
        <>
          {stepsLabel}
          <ChevronDown
            aria-hidden
            className={cn(
              'h-3.5 w-3.5 shrink-0 text-ds-icon-neutral-subtle-default transition-transform',
              !open && '-rotate-90'
            )}
          />
        </>
      }
      onToggle={() => setOpen((v) => !v)}
      expanded={open}
      className='mx-sm'
    >
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            {/* The reasoning body is capped and scrolls instead of growing
                unbounded — a long chain-of-thought otherwise pushes the answer
                far off-screen. Short thoughts stay compact (max-height, not a
                fixed height), so there's no empty gap when there's little to
                say. `overscroll-contain` keeps the wheel from chaining to the
                panel behind it. */}
            <div className="mt-2.5 max-h-64 overflow-y-auto overscroll-contain whitespace-pre-wrap px-3 pt-2.5 text-label-xs leading-relaxed text-ds-text-neutral-subtle-default">
              {text}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </PanelSection>
  );
}
