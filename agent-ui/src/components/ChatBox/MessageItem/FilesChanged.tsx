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
 * End-of-task "Files changed" summary — the files the agent wrote/edited during
 * the task, each opening in the editor on click, with the +N/-M diff. A
 * lightweight take on Antigravity's changed-files list (line-by-line accept/
 * reject is a separate, larger piece).
 */

import type { ChangedFile } from '@/lib/activityClassifier';
import { cn } from '@/lib/utils';
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronRight, FileText, GitCompare } from 'lucide-react';
import { useState } from 'react';

function baseName(p: string): string {
  return p.split(/[\\/]/).pop() || p;
}

export function FilesChanged({
  files,
  onOpen,
}: {
  files: ChangedFile[];
  onOpen?: (path: string) => void;
}) {
  // Collapsed by default — a task can touch many files; the header is a compact
  // summary and the list expands on click. No heavy card border (the header row
  // is the only chrome), matching the thinking/activity blocks.
  const [open, setOpen] = useState(false);
  if (!files.length) return null;

  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 rounded-lg px-1.5 py-1 text-left outline-none transition-colors hover:bg-ds-bg-neutral-muted-default"
      >
        <GitCompare
          size={13}
          aria-hidden
          className="shrink-0 text-ds-icon-neutral-subtle-default"
        />
        <span className="flex-1 text-label-xs font-medium text-ds-text-neutral-subtle-default">
          {files.length} file{files.length === 1 ? '' : 's'} changed
        </span>
        <ChevronRight
          size={13}
          aria-hidden
          className={cn(
            'shrink-0 text-ds-icon-neutral-subtle-default transition-transform',
            open && 'rotate-90'
          )}
        />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.ul
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="m-0 flex list-none flex-col overflow-hidden p-0 pl-1"
          >
            {files.map((f) => (
              <li key={f.path}>
                <button
                  type="button"
                  onClick={() => onOpen?.(f.path)}
                  title={f.path}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left outline-none transition-colors hover:bg-ds-bg-neutral-muted-default"
                >
                  <FileText
                    size={13}
                    aria-hidden
                    className="shrink-0 text-ds-icon-neutral-subtle-default"
                  />
                  <span className="min-w-0 flex-1 truncate text-label-sm text-ds-text-neutral-default-default hover:underline">
                    {baseName(f.path)}
                  </span>
                  {f.diff && (f.diff.added > 0 || f.diff.removed > 0) ? (
                    <span className="shrink-0 whitespace-nowrap font-mono text-label-xs tabular-nums">
                      {f.diff.added > 0 ? (
                        <span style={{ color: '#22c55e' }}>
                          +{f.diff.added}
                        </span>
                      ) : null}
                      {f.diff.removed > 0 ? (
                        <span className="ml-1" style={{ color: '#ef4444' }}>
                          −{f.diff.removed}
                        </span>
                      ) : null}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </motion.ul>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
