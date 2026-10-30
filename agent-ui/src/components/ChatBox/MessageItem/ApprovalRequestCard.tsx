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
 * Rendered in the composer overlay in `ChatBox/index.tsx`, above the input and
 * outside the transcript's scroll container. Earlier attempts to render it
 * inline inside `UserQueryGroup` (buried in a framer-motion `motion.div` whose
 * inline transform clips/contains its descendants) or via a
 * `document.body`/overlay-slot portal never became visible on screen. The
 * composer overlay is already the reliable, always-visible layer; the card
 * sits in it and the composer is disabled while the card is pending.
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
import { generateUniqueId } from '@/lib';
import { inferSessionModeFromTask } from '@/lib/sessionMode';
import { useAuthStore } from '@/store/authStore';
import {
  buildProjectContinuationContext,
  hasLiveSessionStream,
  resolveChatModelForProject,
  type ActiveApproval,
  type VanillaChatStore,
} from '@/store/chatStore';
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

function readQuoted(raw: string, start: number, quote: string): string {
  let out = '';
  for (let i = start; i < raw.length; i += 1) {
    const char = raw[i];
    if (char === '\\' && i + 1 < raw.length) {
      const next = raw[i + 1];
      // Only undo the escapes repr adds for the delimiters. A shell command
      // may legitimately contain `\n` or `\t`, so leave those alone.
      out += next === quote || next === '\\' ? next : char + next;
      i += 1;
      continue;
    }
    if (char === quote) return out;
    out += char;
  }
  return out;
}

function readBare(raw: string, start: number): string {
  const rest = raw.slice(start);
  const match = rest.match(/^([\s\S]*?)(?=,\s*[A-Za-z_]\w*\s*=|\s*\)\s*$)/);
  return (match ? match[1] : rest).trim();
}

function friendlyApprovalDetail(detail: string): string {
  const raw = (detail || '').trim();
  if (!raw) return '';
  for (const key of MEANINGFUL_ARG_KEYS) {
    // The value may be quoted (Python repr) and contain escaped delimiters.
    // The old non-greedy regex stopped at the first inner quote, which cut
    // commands like `node -e "const p=require('./x')"` mid-token.
    const match = raw.match(new RegExp(`(?:^|[\\s,(])${key}\\s*=\\s*`));
    if (!match) continue;
    const start = (match.index ?? 0) + match[0].length;
    const quote = raw[start];
    const value =
      quote === "'" || quote === '"'
        ? readQuoted(raw, start + 1, quote)
        : readBare(raw, start);
    if (value.trim()) return value;
  }
  return raw;
}

export type ApprovalTier = 'read_only' | 'workspace_write' | 'destructive';
export type ApprovalDecision = 'approve' | 'deny';
export type ApprovalScope =
  | 'reads'
  | 'writes'
  | 'tests'
  | 'installs'
  | 'git'
  | 'code';

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
  {
    id: 'code',
    label: 'Runs code',
    hint: 'Run scripts and inline snippets',
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
  code_execution: 'code',
};

const CARD_SCOPE_TO_BACKEND: Record<ApprovalScope, string> = {
  reads: 'file_reads',
  writes: 'file_writes',
  tests: 'builds_tests',
  installs: 'dependency_installs',
  git: 'git_add_commit',
  code: 'code_execution',
};

function toCardScopes(scopes: string[] | undefined): ApprovalScope[] {
  return (scopes ?? [])
    .map((scope) => BACKEND_SCOPE_TO_CARD[scope])
    .filter((scope): scope is ApprovalScope => Boolean(scope));
}

const TIER_LABELS: Record<ApprovalTier, string> = {
  read_only: 'Read only',
  workspace_write: 'May change files',
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
  /** Backend tag for the tier, per action (e.g. "Deletes files"). */
  tierLabel?: string | null;
  workingDirectory?: string | null;
  description?: string | null;
  submitting?: ApprovalDecision | null;
  expired?: boolean;
  /** Scopes to suppress for the rest of the task. Omit to hide the row. */
  selectedScopes?: ApprovalScope[];
  /** Scopes offered as chips. Omit to offer every scope. */
  availableScopes?: ApprovalScope[];
  onToggleScope?: (scope: ApprovalScope) => void;
  expiresIn?: string | null;
  onApprove?: () => void;
  onDeny?: () => void;
  onRetry?: () => void;
  /** Dismiss an expired prompt without resolving anything. */
  onDismiss?: () => void;
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
  tierLabel = null,
  workingDirectory,
  description,
  submitting = null,
  expired = false,
  selectedScopes,
  availableScopes,
  onToggleScope,
  expiresIn,
  onApprove,
  onDeny,
  onRetry,
  onDismiss,
  className,
}: ApprovalRequestCardViewProps) {
  const busy = submitting !== null;
  const [showFull, setShowFull] = useState(false);
  const isLongCommand = command.length > 280 || command.includes('\n');

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
              {tierLabel || TIER_LABELS[tier]}
            </span>
          </div>
          <p className="mt-1 text-label-xs leading-relaxed text-ds-text-neutral-muted-default">
            {description || 'Review this command before it runs.'}
          </p>
        </div>
      </div>

      <div className="mx-4 mt-3 overflow-hidden rounded-lg border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default">
        <div
          className={`${
            showFull ? 'max-h-[min(50vh,26rem)]' : 'max-h-40'
          } overflow-y-auto px-3 py-2`}
        >
          <pre className="m-0 flex gap-2 whitespace-pre-wrap break-all font-mono text-label-xs leading-relaxed text-ds-text-neutral-default-default">
            <span
              aria-hidden
              className="select-none text-ds-text-neutral-subtle-default"
            >
              $
            </span>
            <span className="min-w-0 select-text">{command}</span>
          </pre>
        </div>
        {isLongCommand ? (
          <button
            type="button"
            onClick={() => setShowFull((value) => !value)}
            className="w-full cursor-pointer border-0 border-t border-solid border-ds-border-neutral-default-default bg-transparent px-3 py-1 text-left text-label-xs text-ds-text-neutral-muted-default hover:text-ds-text-neutral-default-default"
          >
            {showFull ? 'Show less' : 'Show full command'}
          </button>
        ) : null}
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
            {SCOPE_OPTIONS.filter(
              (scope) => !availableScopes || availableScopes.includes(scope.id)
            ).map((scope) => {
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
            onClick={expired ? onDismiss : onDeny}
            className="gap-1.5"
          >
            {submitting === 'deny' && !expired ? (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            ) : null}
            {expired ? 'Dismiss' : 'Deny'}
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
  // spinner state. Expiry resets it too: a decision POST still in flight can
  // no longer land once the backend waiter is gone.
  const approvalId = approval?.approval_id;
  const allowedScopes = approval?.allowed_scopes;
  const pendingScopes = approval?.scopes;
  const expired = approval?.expired === true;
  // The row suppresses by what THIS call does, not by what is already
  // suppressed. Pre-ticking "File reads" on a delete card said nothing about
  // the delete and read as if reads were part of the action.
  useEffect(() => {
    setSubmitting(null);
    setSelectedScopes(toCardScopes(pendingScopes));
  }, [approvalId, pendingScopes, expired]);

  if (!approval) return null;

  const suppressed = new Set(toCardScopes(allowedScopes));
  const availableScopes = SCOPE_OPTIONS.map((scope) => scope.id).filter(
    (scope) => !suppressed.has(scope)
  );
  const showScopeRow =
    approval.tier !== 'destructive' &&
    (approval.scopes?.length ?? 0) > 0 &&
    availableScopes.length > 0;

  const handleDismiss = () => {
    if (taskId) chatStore.getState().setActiveApproval(taskId, null);
  };

  // The approval window elapsed and the tool never ran. The only way to
  // actually re-run it is to ask the agent for it again: a fresh call comes
  // back through the gate and prompts with a new approval id.
  const handleRetry = async () => {
    if (!activeProjectId || !taskId || submitting) return;
    setSubmitting('approve');
    const store = chatStore.getState();
    // The Brain mints a NEW task id for this turn. The store only adopts it
    // when `nextTaskId` was recorded before the POST: on the follow-up
    // `confirmed` event it calls appendInitChatStore(nextTaskId), so without
    // this the turn runs on the Brain while every event lands on a task id
    // this store never created (the "retry sits there, nothing happens" bug).
    const turnId = generateUniqueId();
    const nextTaskId = generateUniqueId();
    const currentTask = store.tasks[taskId];
    store.setNextTaskId(nextTaskId);
    if (currentTask?.executionId) {
      store.setNextExecutionId(taskId, currentTask.executionId);
    }
    store.setNextUserId(taskId, turnId);
    const command = friendlyApprovalDetail(approval.detail);
    const question =
      `My approval request for the "${approval.tool_name}" action ` +
      `(${command || 'no command shown'}) expired before I could ` +
      'answer. Please try that step again now.';
    try {
      // A session that lost its SSE consumer (brain restart, long idle drop)
      // would run the retry with nothing rendering it. Re-attach first, same
      // as ChatBox.handleSend; this card only offers Retry once the approval
      // has expired, so no in-flight turn can be superseded here.
      if (!hasLiveSessionStream(activeProjectId)) {
        try {
          await store.startTask(
            taskId,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            currentTask?.executionId,
            activeProjectId,
            inferSessionModeFromTask(currentTask) ?? undefined,
            { preserveTaskId: true, resume: true }
          );
        } catch (reAttachError) {
          console.error(
            'Failed to re-attach the session stream for the retry:',
            reAttachError
          );
        }
      }
      // Same payload shape as ChatBox.handleSend's follow-up: without the
      // model config and project context the Brain falls back to defaults and
      // the retried turn can run on a different model than the chat.
      const model = await resolveChatModelForProject(activeProjectId);
      await fetchPost(`/chat/${activeProjectId}`, {
        question,
        task_id: nextTaskId,
        attaches: [],
        keep_browser_warm: useAuthStore.getState().keepBrowserWarm,
        project_context: buildProjectContinuationContext(
          activeProjectId,
          nextTaskId
        ),
        target: undefined,
        ...(model
          ? {
              model_platform: model.model_platform,
              model_type: model.model_type,
              api_key: model.api_key,
              api_url: model.api_url,
              auth_source: model.auth_source,
              model_config_dict: model.model_config_dict,
              extra_params: model.extra_params,
            }
          : {}),
      });
      store.setActiveApproval(taskId, null);
      // Same reset as an idle follow-up: stale reasoning/acknowledgement from
      // the expired turn would otherwise prepend themselves to the new one.
      store.clearLiveReasoning(taskId);
      store.clearAcknowledgement(taskId);
      store.addMessages(taskId, {
        id: turnId,
        role: 'user',
        content: question,
        attaches: [],
      });
      store.setHasMessages(taskId, true);
      store.setIsPending(taskId, true);
    } catch (error) {
      console.error('Failed to ask the agent to retry:', error);
      // Drop the pointers: a later `confirmed` must not adopt a turn that
      // never got queued.
      store.setNextTaskId(null);
      store.setNextUserId(taskId, undefined);
      toast.error('Could not ask the agent to retry. Please try again.');
      setSubmitting(null);
    }
  };

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
              // Union, not replace: approving one call must not drop the
              // task's existing allowlist (reads are allowed by default).
              allow_scopes: Array.from(
                new Set([
                  ...(approval.allowed_scopes ?? []),
                  ...selectedScopes.map(
                    (scope) => CARD_SCOPE_TO_BACKEND[scope]
                  ),
                ])
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

  // Mounted in the composer overlay (ChatBox/index.tsx), directly above the
  // input. It must not live in the scroll flow: scrolling the transcript used
  // to move the prompt away, and sending from the composer underneath it reset
  // the chat. The composer is disabled while this card is up.
  return (
    <div className="pointer-events-none relative z-30 mb-3 flex w-full justify-center px-1">
      <ApprovalRequestCardView
        toolName={approval.tool_name}
        command={friendlyApprovalDetail(approval.detail)}
        tier={approval.tier}
        tierLabel={approval.tier_label}
        workingDirectory={approval.working_directory}
        description={approval.description}
        selectedScopes={showScopeRow ? selectedScopes : undefined}
        availableScopes={showScopeRow ? availableScopes : undefined}
        onToggleScope={(scope) =>
          setSelectedScopes((current) =>
            current.includes(scope)
              ? current.filter((item) => item !== scope)
              : [...current, scope]
          )
        }
        submitting={submitting}
        expired={expired}
        onApprove={() => handleDecision('approve')}
        onDeny={() => handleDecision('deny')}
        onRetry={handleRetry}
        onDismiss={handleDismiss}
      />
    </div>
  );
}
