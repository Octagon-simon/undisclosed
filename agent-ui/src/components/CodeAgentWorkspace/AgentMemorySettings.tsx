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
 * Memory settings for the embedded agent: toggle semantic (long-term) memory on/
 * off (persisted in authStore, sent to the Brain in toolkit_config) and clear
 * the stored facts. Reads the fact count from the Brain's /memory/status.
 */

import { memoryClear, memoryStatus } from '@/api/brain';
import { useAuthStore } from '@/store/authStore';
import { Brain, Loader2, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

export default function AgentMemorySettings() {
  const memoryEnabled = useAuthStore((s) => s.memoryEnabled);
  const setMemoryEnabled = useAuthStore((s) => s.setMemoryEnabled);
  const email = useAuthStore((s) => s.email);
  const userId = useAuthStore((s) => s.user_id);

  const [count, setCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await memoryStatus(email, userId);
      setCount(res.count);
    } catch {
      setCount(null);
    } finally {
      setLoading(false);
    }
  }, [email, userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const clear = useCallback(async () => {
    setClearing(true);
    try {
      const { removed } = await memoryClear(email, userId);
      toast.success(
        removed > 0
          ? `Cleared ${removed} remembered ${removed === 1 ? 'fact' : 'facts'}.`
          : 'Memory was already empty.'
      );
      await load();
    } catch (e) {
      toast.error((e as Error)?.message || 'Failed to clear memory.');
    } finally {
      setClearing(false);
    }
  }, [email, userId, load]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto px-3 py-3">
      <div className="mb-2 flex items-center gap-2">
        <Brain
          size={15}
          aria-hidden
          className="shrink-0 text-ds-icon-neutral-subtle-default"
        />
        <span className="text-body-sm font-bold text-ds-text-neutral-default-default">
          Memory
        </span>
      </div>

      {/* Enable toggle */}
      <div className="flex items-start justify-between gap-3 rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default px-3 py-3">
        <div className="min-w-0">
          <div className="text-label-sm font-medium text-ds-text-neutral-default-default">
            Remember across conversations
          </div>
          <div className="mt-0.5 text-label-xs leading-relaxed text-ds-text-neutral-subtle-default">
            Lets the agent recall facts you've shared (your name, preferences,
            decisions) in future chats. Applies to new tasks.
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={memoryEnabled}
          onClick={() => setMemoryEnabled(!memoryEnabled)}
          // Explicit colors: the ds brand-default token is UNMAPPED in the embed
          // theme (var resolves to nothing -> black), so pin on=green/off=grey.
          // Both read on light and dark.
          style={{
            backgroundColor: memoryEnabled ? '#22c55e' : '#6b7280',
          }}
          className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors"
        >
          <span
            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-all ${
              memoryEnabled ? 'left-[18px]' : 'left-0.5'
            }`}
          />
        </button>
      </div>

      {/* Stored facts + clear */}
      <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-solid border-ds-border-neutral-default-default px-3 py-3">
        <div className="min-w-0">
          <div className="text-label-sm font-medium text-ds-text-neutral-default-default">
            Stored facts
          </div>
          <div className="mt-0.5 text-label-xs text-ds-text-neutral-subtle-default">
            {loading ? (
              <span className="inline-flex items-center gap-1">
                <Loader2 size={11} className="animate-spin" aria-hidden />
                Loading…
              </span>
            ) : count == null ? (
              'Unavailable'
            ) : (
              `${count} remembered ${count === 1 ? 'fact' : 'facts'}`
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={clear}
          disabled={clearing || (count ?? 0) === 0}
          className="flex shrink-0 items-center gap-1.5 rounded-md border border-solid border-ds-border-neutral-default-default px-2.5 py-1.5 text-label-xs text-ds-text-neutral-default-default outline-none transition-colors hover:bg-ds-bg-neutral-muted-default disabled:opacity-50"
        >
          {clearing ? (
            <Loader2 size={12} className="animate-spin" aria-hidden />
          ) : (
            <Trash2 size={12} aria-hidden />
          )}
          Clear
        </button>
      </div>

      <div className="mt-3 text-label-xs leading-relaxed text-ds-text-neutral-subtle-default">
        Memory is stored locally on your machine and never leaves it.
      </div>
    </div>
  );
}
