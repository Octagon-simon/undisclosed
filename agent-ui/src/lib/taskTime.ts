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

import { ChatTaskStatus, type ChatTaskStatusType } from '@/types/constants';

/**
 * Elapsed wall-clock time (ms) a task has been actively working — the same
 * figure the work log's "Worked for Xs" pill shows. While the task is RUNNING it
 * is the live clock (`Date.now() - taskTime + elapsed`); once it finishes or
 * pauses it is the frozen `elapsed` accumulator. Pure, so it is safe to call
 * during render (the caller re-renders on the store's streaming updates).
 */
export function getTaskElapsedMs(
  task:
    | { status: ChatTaskStatusType; taskTime: number; elapsed: number }
    | null
    | undefined
): number {
  if (!task) return 0;
  if (task.status === ChatTaskStatus.RUNNING && task.taskTime !== 0) {
    return Math.max(0, Date.now() - task.taskTime + task.elapsed);
  }
  return Math.max(0, task.elapsed);
}
