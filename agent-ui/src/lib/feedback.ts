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

// Local per-message feedback (thumbs up/down). Posts to the local brain — never
// a cloud server — and reads the aggregate back for the Stats panel.

import { proxyFetchGet, proxyFetchPost } from '@/api/http';

export type FeedbackRating = 'up' | 'down';

/** One rating as returned by GET /feedback/map. */
export interface FeedbackEntry {
  rating: FeedbackRating;
  updatedAt?: string | null;
}

/** messageId → rating entry. */
export type FeedbackMap = Record<string, FeedbackEntry>;

/**
 * Upsert (rating set) or clear (rating null) a message's thumb. `chatId` is
 * optional metadata so a future per-conversation view can attribute it.
 */
export async function postFeedback(
  messageId: string,
  rating: FeedbackRating | null,
  chatId?: string
): Promise<void> {
  await proxyFetchPost('/api/v1/feedback', {
    message_id: messageId,
    rating,
    chat_id: chatId ?? null,
  });
}

/** All persisted ratings, keyed by message id. Tolerates the older/other
 *  shapes by coercing to { rating, updatedAt }. */
export async function fetchFeedbackMap(): Promise<FeedbackMap> {
  const raw = (await proxyFetchGet('/api/v1/feedback/map')) as Record<
    string,
    { rating?: string; updatedAt?: string | null } | string
  >;
  const out: FeedbackMap = {};
  for (const [id, v] of Object.entries(raw ?? {})) {
    const rating = typeof v === 'string' ? v : v?.rating;
    if (rating === 'up' || rating === 'down') {
      out[id] = {
        rating,
        updatedAt: typeof v === 'string' ? null : v?.updatedAt ?? null,
      };
    }
  }
  return out;
}
