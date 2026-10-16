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

import ShinyText from '@/components/ui/ShinyText/ShinyText';
import type { TFunction } from 'i18next';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

/** Rotating list of playful "working" lines (see `chat.json`). */
const ROTATING_KEY = 'chat.preparing-to-execute-tasks-rotating';
/** Original single line, used when the rotating list is unavailable. */
const FALLBACK_KEY = 'chat.preparing-to-execute-tasks';

/**
 * Pick one line to show while the start request is in flight. The list lives in
 * i18n (`chat.preparing-to-execute-tasks-rotating`); a locale that has not been
 * translated yet falls back to the English array, and a missing array falls back
 * to the original single string so this never renders empty.
 */
function pickPreparingMessage(t: TFunction): string {
  const rotating: unknown = t(ROTATING_KEY, { returnObjects: true });
  if (Array.isArray(rotating) && rotating.length > 0) {
    const message = rotating[Math.floor(Math.random() * rotating.length)];
    if (typeof message === 'string' && message.length > 0) {
      return message;
    }
  }
  return t(FALLBACK_KEY);
}

/** Shown after the user confirms the task plan while the start request is in flight (before the work log appears). */
export function PreparingToExecuteTasks() {
  const { t } = useTranslation();
  // Chosen once per mount: keeps the line stable across re-renders (no flicker)
  // and gives assistive tech a single announcement rather than a stream of them.
  const [message] = useState(() => pickPreparingMessage(t));

  return (
    <div
      className="py-2 min-w-0 flex w-full items-center"
      role="status"
      aria-live="polite"
    >
      <ShinyText text={message} className="text-body-sm" speed={2.5} />
    </div>
  );
}
