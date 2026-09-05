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
 * Collapsible "thinking" block for a reasoning model's thoughts (reasoning_
 * content), shown above the final answer. Collapsed by default — click to
 * expand. Only rendered when the END message carries reasoning.
 */

import { cn } from '@/lib/utils';
import { AnimatePresence, motion } from 'framer-motion';
import { Brain, ChevronRight } from 'lucide-react';
import { useState } from 'react';

export function ThinkingBlock({ reasoning }: { reasoning?: string }) {
  const [open, setOpen] = useState(false);
  const text = (reasoning ?? '').trim();
  if (!text) return null;

  return (
    <div className="mb-2 rounded-xl border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-neutral-muted-default py-2 px-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left !outline-none mb-2"
      >
        <Brain
          size={13}
          aria-hidden
          className="shrink-0 text-ds-icon-neutral-subtle-default"
        />
        <span className="flex-1 text-label-xs font-medium text-ds-text-neutral-subtle-default">
          Thought process
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
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="whitespace-pre-wrap border-t border-solid border-ds-border-neutral-subtle-default px-3 py-2 text-label-xs leading-relaxed text-ds-text-neutral-subtle-default">
              {text}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
