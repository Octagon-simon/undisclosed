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
 * Agent overview / usage screen for the embedded panel. Aggregates the user's
 * LLM activity from the chat-history grouped endpoint — total tokens, number of
 * conversations and runs, completion — plus a per-conversation breakdown. A
 * lightweight "how much am I using" surface (the Antigravity-style overview).
 */

import { proxyFetchGet } from '@/api/http';
import { useQuery } from '@tanstack/react-query';
import { Activity, Layers, Loader2, MessagesSquare, Zap } from 'lucide-react';

interface GroupedProject {
  project_id: string;
  project_name?: string;
  last_prompt?: string;
  total_tokens?: number;
  task_count?: number;
  total_completed_tasks?: number;
  /** Present when the request asks for tasks; tasks[0] is the opening turn. */
  tasks?: Array<{ question?: string | null }>;
}

/**
 * A meaningful label for a conversation. The server names untitled conversations
 * "Project <id>" (unhelpful). Fall back to the conversation's OPENING prompt
 * (tasks[0].question) — the same thing the history sidebar titles it by — so a
 * row here matches what the user sees there. Last prompt is a final fallback.
 */
function conversationLabel(p: GroupedProject): string {
  const name = (p.project_name ?? '').trim();
  const isPlaceholder =
    !name || /^project\s+[\d-]+$/i.test(name) || /^new project$/i.test(name);
  if (!isPlaceholder) return name;
  const firstPrompt = (p.tasks?.[0]?.question ?? '').trim();
  const lastPrompt = (p.last_prompt ?? '').trim();
  return firstPrompt || lastPrompt || 'Untitled conversation';
}
interface GroupedResponse {
  projects?: GroupedProject[];
  total_projects?: number;
  total_tasks?: number;
  total_tokens?: number;
}

function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(n);
}

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Zap;
  label: string;
  value: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default px-3 py-3">
      <div className="flex items-center gap-1.5 text-ds-text-neutral-subtle-default">
        <Icon size={14} aria-hidden className="shrink-0" />
        <span className="text-label-xs">{label}</span>
      </div>
      <span className="text-heading-h5 font-bold tabular-nums text-ds-text-neutral-default-default">
        {value}
      </span>
    </div>
  );
}

export default function AgentUsageStats() {
  const { data, isLoading, isError, refetch, isFetching } =
    useQuery<GroupedResponse>({
      queryKey: ['agent-usage-grouped'],
      queryFn: () =>
        proxyFetchGet('/api/v1/chat/histories/grouped', {
          page: 1,
          size: 200,
          // Need tasks[0].question to title auto-named conversations by their
          // opening prompt (matching the history sidebar).
          include_tasks: true,
        }),
      staleTime: 30_000,
    });

  const projects = (data?.projects ?? [])
    .slice()
    .sort((a, b) => (b.total_tokens ?? 0) - (a.total_tokens ?? 0));
  const totalTokens =
    data?.total_tokens ??
    projects.reduce((s, p) => s + (p.total_tokens ?? 0), 0);
  const totalRuns =
    data?.total_tasks ?? projects.reduce((s, p) => s + (p.task_count ?? 0), 0);
  const totalProjects = data?.total_projects ?? projects.length;
  const completed = projects.reduce(
    (s, p) => s + (p.total_completed_tasks ?? 0),
    0
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto px-3 py-3">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-body-sm font-bold text-ds-text-neutral-default-default">
          Usage overview
        </h2>
        <button
          type="button"
          onClick={() => refetch()}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-label-xs text-[var(--theia-descriptionForeground,var(--theia-foreground))] outline-none transition-colors hover:bg-[var(--theia-list-hoverBackground)]"
        >
          {isFetching ? (
            <Loader2 size={12} className="animate-spin" aria-hidden />
          ) : null}
          Refresh
        </button>
      </div>

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2
            className="h-5 w-5 animate-spin text-ds-icon-neutral-subtle-default"
            aria-hidden
          />
        </div>
      ) : isError ? (
        <div className="flex flex-1 items-center justify-center p-6 text-center text-label-xs text-ds-text-neutral-subtle-default">
          Couldn&apos;t load usage. Try refreshing.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <StatCard
              icon={Zap}
              label="Tokens used"
              value={formatCompact(totalTokens)}
            />
            <StatCard
              icon={Activity}
              label="Runs"
              value={formatCompact(totalRuns)}
            />
            <StatCard
              icon={MessagesSquare}
              label="Conversations"
              value={formatCompact(totalProjects)}
            />
            <StatCard
              icon={Layers}
              label="Completed"
              value={formatCompact(completed)}
            />
          </div>

          <div className="mt-4">
            <div className="mb-1.5 text-label-xs font-medium uppercase tracking-wide text-ds-text-neutral-subtle-default">
              By conversation
            </div>
            {projects.length === 0 ? (
              <div className="rounded-lg border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default px-3 py-4 text-center text-label-xs text-ds-text-neutral-subtle-default">
                No activity yet.
              </div>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-1 p-0">
                {projects.slice(0, 40).map((p) => (
                  <li
                    key={p.project_id}
                    className="flex items-center gap-2 rounded-lg px-2.5 py-2 transition-colors hover:bg-ds-bg-neutral-muted-default"
                  >
                    <span className="min-w-0 flex-1 truncate text-label-sm text-ds-text-neutral-default-default">
                      {conversationLabel(p)}
                    </span>
                    <span className="shrink-0 text-label-xs tabular-nums text-ds-text-neutral-subtle-default">
                      {formatCompact(p.total_tokens ?? 0)} tok
                    </span>
                    <span className="shrink-0 rounded-full bg-ds-bg-neutral-subtle-default px-1.5 py-0.5 text-label-xs tabular-nums text-ds-text-neutral-subtle-default">
                      {p.task_count ?? 0} run{(p.task_count ?? 0) === 1 ? '' : 's'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
