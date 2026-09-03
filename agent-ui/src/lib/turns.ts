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

// Lightweight turn persistence helper with a tiny retry queue.
// Posts messages to the backend turns API so runs hydrate after reload.

import { proxyFetchPost } from '@/api/http';

export type TurnRole = 'assistant' | 'user';

export type TurnMessage = {
  id: string;
  step?: string;
  content: string;
  reasoning?: string | null;
  attaches?: any[];
  fileList?: any[];
  agent_name?: string | null;
  createdAt?: string | null;
};

type QueueItem = {
  url: string;
  body: { role: TurnRole; message: TurnMessage };
  attempts: number;
};

const queue: QueueItem[] = [];
let flushing = false;

function backoffMs(attempts: number): number {
  const base = 400; // ms
  const cap = 8000; // ms
  return Math.min(cap, base * Math.pow(2, Math.max(0, attempts - 1)));
}

async function postOnce(item: QueueItem): Promise<void> {
  await proxyFetchPost(item.url, item.body);
}

async function flushOnce(): Promise<void> {
  if (flushing) return;
  flushing = true;
  try {
    for (let i = 0; i < queue.length; ) {
      const item = queue[i]!;
      try {
        await postOnce(item);
        // Remove on success without re-creating the array each time
        queue.splice(i, 1);
        continue; // do not increment i
      } catch (err) {
        item.attempts += 1;
        const delay = backoffMs(item.attempts);
        // Move to the end to give others a chance
        queue.splice(i, 1);
        queue.push(item);
        // Stagger retries
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  } finally {
    flushing = false;
  }
}

let scheduled = false;
function scheduleFlushSoon() {
  if (scheduled) return;
  scheduled = true;
  setTimeout(() => {
    scheduled = false;
    void flushOnce();
  }, 50);
}

export function enqueueTurnPost(
  chatId: string | undefined,
  queryId: string | undefined,
  role: TurnRole,
  message: TurnMessage
): void {
  if (!chatId || !queryId) return;
  if (!message || !message.id) return;

  const url = `/api/v1/chat/${encodeURIComponent(chatId)}/turns/${encodeURIComponent(
    queryId
  )}/messages`;
  // Coalesce by (url, message.id): a streamed assistant message may be
  // re-enqueued as it is updated (e.g. the END step gaining its fileList).
  // Replacing the still-queued item keeps last-write-wins and prevents the
  // queue from flooding with intermediate versions. The backend upserts by id.
  const existingIdx = queue.findIndex(
    (q) => q.url === url && q.body.message.id === message.id
  );
  if (existingIdx !== -1) {
    queue[existingIdx]!.body = { role, message };
  } else {
    queue.push({ url, body: { role, message }, attempts: 0 });
  }
  scheduleFlushSoon();
}

export function tryFlushTurnsQueueNow(): void {
  void flushOnce();
}
