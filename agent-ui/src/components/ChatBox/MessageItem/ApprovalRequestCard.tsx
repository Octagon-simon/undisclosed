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
 * Governance approval prompt: rendered whenever the given task has a
 * pending `activeApproval` (set from the SSE `approval_request` event —
 * see `chatStore.ts`).
 *
 * Rendered at the `ProjectSection` level (a sibling of the query-group list),
 * right next to `FloatingAction` ("Stop Task"), and positioned with the same
 * `position: sticky` approach. This is deliberate: earlier attempts to render
 * it inline inside `UserQueryGroup` (buried in a framer-motion `motion.div`
 * whose inline transform clips/contains its descendants) or via a
 * `document.body`/overlay-slot portal never became visible on screen. The
 * Stop button, a plain sticky element in the scroll flow at project level, is
 * the one control that reliably shows during a running task — so the approval
 * prompt mirrors it exactly.
 *
 * Takes `chatStore`/`taskId` as props, mirroring `TaskWorkLogAccordion`,
 * rather than resolving "the active chat store" independently via
 * `useChatStoreAdapter`. That independent resolution was the bug: a Project
 * can have more than one `VanillaChatStore` instance (one per turn/append),
 * and `useChatStoreAdapter`'s notion of "active" does not always match the
 * specific instance the SSE handler was writing to.
 *
 * Resolving is a POST to `/chat/{id}/approval`; the SSE `approval_resolved`
 * event (not this component) is what actually clears `activeApproval` and
 * posts the outcome message, since the decision may come from elsewhere
 * (a beckon hook, the 120s auto-deny timeout) and every client watching
 * this task needs to converge on the same state.
 */

import { fetchPost } from '@/api/http';
import { Button } from '@/components/ui/button';
import type { ActiveApproval, VanillaChatStore } from '@/store/chatStore';
import { useProjectStore } from '@/store/projectStore';
import { Loader2, ShieldAlert } from 'lucide-react';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { toast } from 'sonner';

type Decision = 'approve' | 'deny';

/**
 * The backend sends `detail` as a raw tool-call string, e.g.
 *   shell_exec(id='docker_version', command='docker --version', block=True, timeout=20)
 * The user only cares about what will actually run — the `command` (or the
 * closest meaningful argument) — not the function signature and bookkeeping
 * kwargs. Pull that out; fall back to the raw detail if we can't parse it.
 */
const MEANINGFUL_ARG_KEYS = [
  'command',
  'cmd',
  'code',
  'script',
  'query',
  'sql',
  'url',
  'path',
  'file_path',
  'content',
  'text',
  'input',
];

function friendlyApprovalDetail(detail: string): string {
  const raw = (detail || '').trim();
  if (!raw) return '';
  for (const key of MEANINGFUL_ARG_KEYS) {
    // key='...' or key="..." (non-greedy to the matching quote)
    const match = raw.match(
      new RegExp(`${key}\\s*=\\s*(['"])([\\s\\S]*?)\\1`)
    );
    if (match && match[2].trim()) return match[2];
  }
  return raw;
}

export interface ApprovalRequestCardProps {
  chatStore: VanillaChatStore;
  taskId: string | null;
}

function useActiveApproval(
  chatStore: VanillaChatStore,
  taskId: string | null
): ActiveApproval | null {
  return useSyncExternalStore(
    (callback) => chatStore.subscribe(callback),
    () =>
      taskId
        ? (chatStore.getState().tasks[taskId]?.activeApproval ?? null)
        : null
  );
}

export function ApprovalRequestCard({
  chatStore,
  taskId,
}: ApprovalRequestCardProps) {
  const approval = useActiveApproval(chatStore, taskId);
  const activeProjectId = useProjectStore((state) => state.activeProjectId);
  const [submitting, setSubmitting] = useState<Decision | null>(null);

  // This component instance persists across successive approvals for the same
  // task (it renders null between them rather than unmounting). `submitting` is
  // only cleared on error, since a successful decision normally clears the
  // approval and the buttons go away. Reset it whenever the pending approval
  // changes so a fresh prompt doesn't inherit the previous one's disabled/
  // spinner state.
  const approvalId = approval?.approval_id;
  useEffect(() => {
    setSubmitting(null);
  }, [approvalId]);

  if (!approval) return null;

  const handleDecision = async (decision: Decision) => {
    if (submitting) return;
    setSubmitting(decision);
    try {
      await fetchPost(`/chat/${activeProjectId}/approval`, {
        approval_id: approval.approval_id,
        decision,
        decided_by: 'user',
      });
    } catch (error) {
      console.error('Failed to submit approval decision:', error);
      toast.error('Failed to send your decision. Please try again.');
      setSubmitting(null);
    }
  };

  // Mirror `FloatingAction` (the "Stop Task" control): a sticky element in the
  // scroll flow, rendered at project level, pinned just above the bottom input.
  // It sits slightly higher than the Stop pill (bottom-44 vs bottom-32) so the
  // two don't overlap when both are visible during a running, gated task.
  return (
    <div className="pointer-events-none sticky bottom-44 left-0 right-0 top-2 z-30 mt-4 flex w-full justify-center px-2">
      <div
        role="alertdialog"
        aria-label={`Approval needed: ${approval.tool_name}`}
        className="pointer-events-auto flex w-full max-w-[560px] flex-col gap-2 rounded-2xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-subtle-default px-4 py-3 shadow-lg backdrop-blur-md"
      >
        <div className="flex items-center gap-2">
          <ShieldAlert
            size={16}
            aria-hidden
            className="shrink-0 text-ds-text-warning-strong-default"
          />
          <span className="text-body-sm font-bold text-ds-text-neutral-default-default">
            Approval needed: {approval.tool_name}
          </span>
          {approval.agent_name ? (
            <span className="text-label-xs text-ds-text-neutral-subtle-default">
              · {approval.agent_name}
            </span>
          ) : null}
        </div>
        {approval.detail ? (
          <div className="overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-ds-bg-neutral-muted-default px-3.5 py-2 font-mono text-label-xs text-ds-text-neutral-default-default">
            {friendlyApprovalDetail(approval.detail)}
          </div>
        ) : null}
        <div className="flex items-center gap-2 pt-1">
          <Button
            type="button"
            variant="primary"
            tone="success"
            size="xs"
            buttonContent="text"
            disabled={submitting !== null}
            onClick={() => handleDecision('approve')}
            className="gap-1.5"
          >
            {submitting === 'approve' ? (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            ) : null}
            Approve
          </Button>
          <Button
            type="button"
            variant="primary"
            tone="error"
            size="xs"
            buttonContent="text"
            disabled={submitting !== null}
            onClick={() => handleDecision('deny')}
            className="gap-1.5"
          >
            {submitting === 'deny' ? (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            ) : null}
            Deny
          </Button>
        </div>
      </div>
    </div>
  );
}
