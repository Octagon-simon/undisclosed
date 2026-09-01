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
 * Notification box shown after a governance approval resolves. This is NOT a
 * feedback/agent message — it's an informational notice that an action was
 * approved or denied. Approved/allowed reads as neutral **info**; denied or
 * timed-out (i.e. the action was rejected) reads as **danger**.
 */

import { cn } from '@/lib/utils';
import { CircleCheck, ShieldX } from 'lucide-react';

export interface ApprovalOutcomeCardProps {
  content: string;
  decision?: string;
}

export function ApprovalOutcomeCard({
  content,
  decision,
}: ApprovalOutcomeCardProps) {
  // "denied" and "timeout" both mean the action did not run — surface as danger.
  const rejected = decision === 'denied' || decision === 'timeout';
  const Icon = rejected ? ShieldX : CircleCheck;

  return (
    <div
      role="status"
      className={cn(
        'my-2 flex items-center gap-2 rounded-xl border border-solid px-3 py-2 text-sm',
        rejected
          ? 'border-ds-border-error-default-default bg-ds-bg-error-subtle-default'
          : 'border-ds-border-information-default-default bg-ds-bg-information-subtle-default'
      )}
    >
      <Icon
        size={16}
        aria-hidden
        className={cn(
          'shrink-0',
          rejected
            ? 'text-ds-icon-error-default-default'
            : 'text-ds-icon-information-default-default'
        )}
      />
      <span
        className={cn(
          'text-body-xs',
          rejected
            ? 'text-ds-text-error-strong-default'
            : 'text-ds-text-information-strong-default'
        )}
      >
        {content}
      </span>
    </div>
  );
}
