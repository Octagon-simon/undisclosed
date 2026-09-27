// ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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
// ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========

// Client-side source of truth for per-message thumbs. Holds the full map so the
// per-answer thumbs (AgentMessageCard) and the aggregate tally (AgentUsageStats)
// stay in sync and update live. Writes are optimistic + persisted to the local
// brain; a failed write reverts and surfaces a toast.

import {
  fetchFeedbackMap,
  postFeedback,
  type FeedbackMap,
  type FeedbackRating,
} from '@/lib/feedback';
import { toast } from 'sonner';
import { create } from 'zustand';

export interface FeedbackStats {
  up: number;
  down: number;
  total: number;
  /** 0..1, or null when nothing is rated yet. */
  satisfaction: number | null;
  /** Newest-first ratings for the "recent" strip. */
  recent: FeedbackRating[];
}

interface FeedbackState {
  map: FeedbackMap;
  /** 'idle' until the first hydrate resolves (so we only fetch once). */
  status: 'idle' | 'loading' | 'ready';
  hydrate: () => Promise<void>;
  /** Current rating for a message, or null. */
  ratingFor: (messageId: string) => FeedbackRating | null;
  /**
   * Set/toggle a message's rating. Passing the value it already has clears it
   * (thumb toggles off). Optimistic; reverts on a failed POST.
   */
  setRating: (
    messageId: string,
    rating: FeedbackRating,
    chatId?: string
  ) => Promise<void>;
  stats: () => FeedbackStats;
}

export const useFeedbackStore = create<FeedbackState>((set, get) => ({
  map: {},
  status: 'idle',

  hydrate: async () => {
    if (get().status !== 'idle') return;
    set({ status: 'loading' });
    try {
      const map = await fetchFeedbackMap();
      set({ map, status: 'ready' });
    } catch {
      // Leave the map empty but mark ready so we don't spin; a later vote still
      // works and repopulates it.
      set({ status: 'ready' });
    }
  },

  ratingFor: (messageId) => get().map[messageId]?.rating ?? null,

  setRating: async (messageId, rating, chatId) => {
    const prev = get().map;
    const current = prev[messageId]?.rating ?? null;
    // Clicking the active thumb again clears it.
    const next: FeedbackRating | null = current === rating ? null : rating;

    const optimistic: FeedbackMap = { ...prev };
    if (next === null) {
      delete optimistic[messageId];
    } else {
      optimistic[messageId] = {
        rating: next,
        updatedAt: new Date().toISOString(),
      };
    }
    set({ map: optimistic });

    try {
      await postFeedback(messageId, next, chatId);
    } catch {
      set({ map: prev }); // revert
      toast.error('Could not save feedback');
    }
  },

  stats: () => {
    const entries = Object.values(get().map);
    let up = 0;
    let down = 0;
    for (const e of entries) {
      if (e.rating === 'up') up++;
      else if (e.rating === 'down') down++;
    }
    const total = up + down;
    const recent = Object.values(get().map)
      .slice()
      .sort((a, b) =>
        (b.updatedAt ?? '').localeCompare(a.updatedAt ?? '')
      )
      .map((e) => e.rating)
      .slice(0, 12);
    return {
      up,
      down,
      total,
      satisfaction: total > 0 ? up / total : null,
      recent,
    };
  },
}));
