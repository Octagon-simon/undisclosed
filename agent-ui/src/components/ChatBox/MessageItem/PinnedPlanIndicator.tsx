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
 * A compact, PINNED plan/todo indicator for the agent panel.
 *
 * Reads the active task's `taskInfo` (the decomposed subtasks — each has
 * `content` + `status`) and shows an unobtrusive "Plan · done/total" pill with a
 * slim progress bar, stuck to the top of the conversation viewport. Clicking it
 * reveals the full checklist with per-item status. When there's no plan yet
 * (`taskInfo` empty) it renders nothing, so it never clutters an idle panel.
 *
 * Mounted as a sticky sibling in `ProjectSection` — the same reliable placement
 * the Stop button / approval prompt use (portals/overlays were tried there and
 * didn't show). Deliberately separate from the inline, transient `PlanTaskBox`
 * planning card: this one persists and stays reachable during the whole run.
 */

import type { VanillaChatStore } from '@/store/chatStore';
import { TaskStatus, type TaskStatusType } from '@/types/constants';
import {
  CheckCircle2,
  ChevronDown,
  Circle,
  ClipboardList,
  Loader2,
  XCircle,
} from 'lucide-react';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

export interface PinnedPlanIndicatorProps {
  chatStore: VanillaChatStore;
  taskId: string | null;
}

function useTaskInfo(
  chatStore: VanillaChatStore,
  taskId: string | null
): TaskInfo[] {
  return useSyncExternalStore(
    (cb) => chatStore.subscribe(cb),
    () => (taskId ? (chatStore.getState().tasks[taskId]?.taskInfo ?? EMPTY) : EMPTY),
    () => (taskId ? (chatStore.getState().tasks[taskId]?.taskInfo ?? EMPTY) : EMPTY)
  );
}
const EMPTY: TaskInfo[] = [];

function StatusGlyph({ status }: { status?: TaskStatusType }) {
  if (status === TaskStatus.COMPLETED) {
    return (
      <CheckCircle2
        size={18}
        aria-hidden
        className="shrink-0 text-ds-icon-success-default-default"
      />
    );
  }
  if (status === TaskStatus.FAILED) {
    return (
      <XCircle
        size={18}
        aria-hidden
        className="shrink-0 text-ds-icon-error-default-default"
      />
    );
  }
  if (status === TaskStatus.RUNNING) {
    return (
      <Loader2
        size={18}
        aria-hidden
        className="shrink-0 animate-spin text-ds-icon-information-default-default"
      />
    );
  }
  // EMPTY / undefined → pending
  return (
    <Circle
      size={18}
      aria-hidden
      className="shrink-0 text-ds-icon-neutral-subtle-default"
    />
  );
}

export function PinnedPlanIndicator({
  chatStore,
  taskId,
}: PinnedPlanIndicatorProps) {
  const taskInfo = useTaskInfo(chatStore, taskId);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close the checklist when clicking outside it.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const total = taskInfo.length;
  if (total === 0) return null; // no plan yet → no clutter

  const done = taskInfo.filter((t) => t.status === TaskStatus.COMPLETED).length;
  const failed = taskInfo.filter((t) => t.status === TaskStatus.FAILED).length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const allDone = done === total;

  return (
    <div className="pointer-events-none sticky top-2 z-20 mb-2 flex w-full justify-center px-2">
      <div ref={rootRef} className="pointer-events-auto w-full max-w-[560px]">
        {/* Collapsed pill */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={`Plan progress: ${done} of ${total} done`}
          className="flex w-full items-center gap-2.5 rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-subtle-default px-4 py-2.5 shadow-sm outline-none backdrop-blur-md transition-colors hover:bg-ds-bg-neutral-muted-default focus:outline-none focus-visible:outline-none"
        >
          <ClipboardList
            size={16}
            aria-hidden
            className="shrink-0 text-ds-icon-neutral-subtle-default"
          />
          <span className="text-body-sm font-bold text-ds-text-neutral-default-default">
            Plan
          </span>
          <span className="text-body-sm font-normal tabular-nums text-ds-text-neutral-subtle-default">
            {done}/{total}
            {failed > 0 ? ` · ${failed} failed` : ''}
          </span>
          {/* slim progress bar */}
          <span className="mx-1 h-1.5 flex-1 overflow-hidden rounded-full bg-ds-bg-neutral-muted-default">
            <span
              className={`block h-full rounded-full transition-[width] duration-300 ${
                allDone
                  ? 'bg-ds-icon-success-default-default'
                  : 'bg-ds-icon-information-default-default'
              }`}
              style={{ width: `${pct}%` }}
            />
          </span>
          <ChevronDown
            size={16}
            aria-hidden
            className={`shrink-0 text-ds-icon-neutral-subtle-default transition-transform ${
              open ? 'rotate-180' : ''
            }`}
          />
        </button>

        {/* Expanded checklist */}
        {open ? (
          <div className="mt-1.5 max-h-[50vh] overflow-y-auto rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-subtle-default p-2.5 shadow-lg backdrop-blur-md">
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
              {taskInfo.map((item, i) => (
                <li
                  key={item.id || i}
                  className="flex items-start gap-2.5 rounded-lg px-3 py-2.5 transition-colors hover:bg-ds-bg-neutral-muted-default"
                >
                  <span className="mt-px">
                    <StatusGlyph status={item.status} />
                  </span>
                  <span
                    className={`text-body-sm leading-relaxed ${
                      item.status === TaskStatus.COMPLETED
                        ? 'text-ds-text-neutral-subtle-default line-through'
                        : 'text-ds-text-neutral-default-default'
                    }`}
                  >
                    {item.content || `Subtask ${i + 1}`}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
