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
import { Check, Folder, Loader2, RotateCcw, ShieldAlert } from 'lucide-react';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { toast } from 'sonner';

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
    const match = raw.match(new RegExp(`${key}\\s*=\\s*(['"])([\\s\\S]*?)\\1`));
    if (match && match[2].trim()) return match[2];
  }
  return raw;
}

export type ApprovalTier = 'read_only' | 'workspace_write' | 'destructive';
export type ApprovalDecision = 'approve' | 'deny';
export type ApprovalScope = 'reads' | 'writes' | 'tests' | 'installs' | 'git';

const SCOPE_OPTIONS: {
  id: ApprovalScope;
  label: string;
  hint: string;
}[] = [
  {
    id: 'reads',
    label: 'File reads',
    hint: 'Read file contents and repository state',
  },
  { id: 'writes', label: 'File writes', hint: 'Create or modify files' },
  {
    id: 'tests',
    label: 'Builds & tests',
    hint: 'Run tests, linters, and type-checks',
  },
  {
    id: 'installs',
    label: 'Dependency installs',
    hint: 'Install or update dependencies',
  },
  {
    id: 'git',
    label: 'Git add & commit',
    hint: 'Stage and commit changes, but never push or reset',
  },
];

// Backend scope ids (see ApprovalScope in app/model/enums.py) mapped to the
// short ids this view uses.
const BACKEND_SCOPE_TO_CARD: Record<string, ApprovalScope> = {
  file_reads: 'reads',
  file_writes: 'writes',
  builds_tests: 'tests',
  dependency_installs: 'installs',
  git_add_commit: 'git',
};

const CARD_SCOPE_TO_BACKEND: Record<ApprovalScope, string> = {
  reads: 'file_reads',
  writes: 'file_writes',
  tests: 'builds_tests',
  installs: 'dependency_installs',
  git: 'git_add_commit',
};

const TIER_LABELS: Record<ApprovalTier, string> = {
  read_only: 'Read only',
  workspace_write: 'Writes files',
  destructive: 'Destructive',
};

const TIER_SURFACES: Record<ApprovalTier, string> = {
  read_only:
    'bg-ds-bg-neutral-subtle-default text-ds-text-neutral-muted-default',
  workspace_write:
    'bg-ds-bg-warning-subtle-default text-ds-text-warning-strong-default',
  destructive:
    'bg-ds-bg-error-subtle-default text-ds-text-error-strong-default',
};

export interface ApprovalRequestCardViewProps {
  toolName: string;
  command: string;
  tier?: ApprovalTier;
  workingDirectory?: string | null;
  description?: string | null;
  submitting?: ApprovalDecision | null;
  expired?: boolean;
  /** Scopes to suppress for the rest of the task. Omit to hide the row. */
  selectedScopes?: ApprovalScope[];
  onToggleScope?: (scope: ApprovalScope) => void;
  expiresIn?: string | null;
  onApprove?: () => void;
  onDeny?: () => void;
  onRetry?: () => void;
  className?: string;
}

/**
 * Presentational approval prompt. Store wiring and POSTing the decision live in
 * `ApprovalRequestCard`; this view is shared with Storybook so the design can be
 * reviewed without a running task.
 */
export function ApprovalRequestCardView({
  toolName,
  command,
  tier = 'workspace_write',
  workingDirectory,
  description,
  submitting = null,
  expired = false,
  selectedScopes,
  onToggleScope,
  expiresIn,
  onApprove,
  onDeny,
  onRetry,
  className,
}: ApprovalRequestCardViewProps) {
  const busy = submitting !== null;

  return (
    <div
      role="alertdialog"
      aria-label={`Approval needed: ${toolName}`}
      className={[
        'pointer-events-auto w-full max-w-[560px] overflow-hidden rounded-xl border border-solid border-ds-border-neutral-strong-default bg-ds-bg-neutral-default-default shadow-lg',
        className ?? '',
      ].join(' ')}
    >
      <div className="flex items-start gap-3 px-4 pt-3.5">
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${TIER_SURFACES[tier]}`}
        >
          <ShieldAlert size={15} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-body-sm font-bold text-ds-text-neutral-default-default">
              Approval needed
            </span>
            <span
              className={`inline-flex items-center rounded-full border border-transparent px-2 py-0.5 text-label-xs font-medium ${TIER_SURFACES[tier]}`}
            >
              {TIER_LABELS[tier]}
            </span>
          </div>
          <p className="mt-1 text-label-xs leading-relaxed text-ds-text-neutral-muted-default">
            {description || 'Review this command before it runs.'}
          </p>
        </div>
      </div>

      <div className="mx-4 mt-3 overflow-hidden rounded-lg border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default">
        <div className="max-h-40 overflow-y-auto px-3 py-2">
          <pre className="m-0 flex gap-2 whitespace-pre-wrap break-all font-mono text-label-xs leading-relaxed text-ds-text-neutral-default-default">
            <span
              aria-hidden
              className="select-none text-ds-text-neutral-subtle-default"
            >
              $
            </span>
            <span className="min-w-0">{command}</span>
          </pre>
        </div>
      </div>

      {workingDirectory ? (
        <div className="mx-4 mt-2.5 flex items-center gap-1.5 text-label-xs text-ds-text-neutral-muted-default">
          <Folder size={12} className="shrink-0" aria-hidden />
          <span className="truncate font-mono">{workingDirectory}</span>
        </div>
      ) : null}

      {selectedScopes ? (
        <div className="mx-4 mt-3">
          <div className="text-label-xs text-ds-text-neutral-muted-default">
            Suppress prompts for the rest of this task:
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {SCOPE_OPTIONS.map((scope) => {
              const selected = selectedScopes.includes(scope.id);
              return (
                <button
                  key={scope.id}
                  type="button"
                  aria-pressed={selected}
                  disabled={busy || expired}
                  title={scope.hint}
                  onClick={() => onToggleScope?.(scope.id)}
                  className={[
                    'inline-flex cursor-pointer items-center gap-1 rounded-full border border-solid px-2 py-0.5 text-label-xs transition-colors disabled:pointer-events-none',
                    selected
                      ? 'border-transparent bg-ds-bg-success-subtle-default text-ds-text-success-strong-default'
                      : 'border-ds-border-neutral-default-default bg-ds-bg-neutral-default-default text-ds-text-neutral-muted-default hover:border-ds-border-neutral-strong-default',
                  ].join(' ')}
                >
                  {selected ? (
                    <Check size={11} className="shrink-0" aria-hidden />
                  ) : null}
                  {scope.label}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="mt-3 flex items-center justify-between gap-2 bg-ds-bg-neutral-subtle-default px-4 py-2.5">
        <span
          className={`min-w-0 truncate text-label-xs ${
            expired
              ? 'text-ds-text-warning-strong-default'
              : 'text-ds-text-neutral-muted-default'
          }`}
        >
          {expired
            ? 'Request expired.'
            : (expiresIn ?? 'Runs only if you approve.')}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            type="button"
            variant="outline"
            tone="neutral"
            size="xs"
            buttonContent="text"
            disabled={busy}
            onClick={onDeny}
            className="gap-1.5"
          >
            {submitting === 'deny' ? (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            ) : null}
            Deny
          </Button>
          {expired ? (
            <Button
              type="button"
              variant="primary"
              tone="neutral"
              size="xs"
              buttonContent="text"
              disabled={busy}
              onClick={onRetry}
              className="gap-1.5"
            >
              <RotateCcw className="h-3 w-3" aria-hidden />
              Retry
            </Button>
          ) : (
            <Button
              type="button"
              variant="primary"
              tone={tier === 'destructive' ? 'error' : 'success'}
              size="xs"
              buttonContent="text"
              disabled={busy}
              onClick={onApprove}
              className="gap-1.5"
            >
              {submitting === 'approve' ? (
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
              ) : null}
              Approve
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export interface ApprovalRequestCardProps {
  chatStore: VanillaChatStore;
  taskId: string | null;
}

function useActiveApproval(
  chatStore: VanillaChatStore,
  taskId: string | null,
): ActiveApproval | null {
  return useSyncExternalStore(
    (callback) => chatStore.subscribe(callback),
    () =>
      taskId
        ? (chatStore.getState().tasks[taskId]?.activeApproval ?? null)
        : null,
  );
}

export function ApprovalRequestCard({
  chatStore,
  taskId,
}: ApprovalRequestCardProps) {
  const approval = useActiveApproval(chatStore, taskId);
  const activeProjectId = useProjectStore((state) => state.activeProjectId);
  const [submitting, setSubmitting] = useState<ApprovalDecision | null>(null);
  const [selectedScopes, setSelectedScopes] = useState<ApprovalScope[]>([]);

  // This component instance persists across successive approvals for the same
  // task (it renders null between them rather than unmounting). `submitting` is
  // only cleared on error, since a successful decision normally clears the
  // approval and the buttons go away. Reset it whenever the pending approval
  // changes so a fresh prompt doesn't inherit the previous one's disabled/
  // spinner state.
  const approvalId = approval?.approval_id;
  const allowedScopes = approval?.allowed_scopes;
  useEffect(() => {
    setSubmitting(null);
    setSelectedScopes(
      (allowedScopes ?? [])
        .map((scope) => BACKEND_SCOPE_TO_CARD[scope])
        .filter((scope): scope is ApprovalScope => Boolean(scope))
    );
  }, [approvalId, allowedScopes]);

  if (!approval) return null;

  const showScopeRow =
    approval.tier !== 'destructive' && (approval.scopes?.length ?? 0) > 0;

  const handleDecision = async (decision: ApprovalDecision) => {
    if (submitting) return;
    setSubmitting(decision);
    try {
      await fetchPost(`/chat/${activeProjectId}/approval`, {
        approval_id: approval.approval_id,
        decision,
        decided_by: 'user',
        ...(showScopeRow
          ? {
              allow_scopes: selectedScopes.map(
                (scope) => CARD_SCOPE_TO_BACKEND[scope]
              ),
            }
          : {}),
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
      <ApprovalRequestCardView
        toolName={approval.tool_name}
        command={friendlyApprovalDetail(approval.detail)}
        tier={approval.tier}
        workingDirectory={approval.working_directory}
        description={approval.description}
        selectedScopes={showScopeRow ? selectedScopes : undefined}
        onToggleScope={(scope) =>
          setSelectedScopes((current) =>
            current.includes(scope)
              ? current.filter((item) => item !== scope)
              : [...current, scope]
          )
        }
        submitting={submitting}
        onApprove={() => handleDecision('approve')}
        onDeny={() => handleDecision('deny')}
      />
    </div>
  );
}
