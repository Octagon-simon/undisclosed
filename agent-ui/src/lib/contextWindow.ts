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
 * Context-window gauge for a live conversation.
 *
 * The number we care about is NOT the cumulative billed `task.tokens` (sum of
 * every turn's prompt+completion, which grows super-linearly and would scream
 * "approaching 1M" on an ordinary chat). It is the size of the LATEST single
 * request — `task.lastRequestTokens` — because the next request's prompt is
 * roughly that size plus the new turn.
 *
 * The window itself is resolved from the provider model catalog the Models
 * screen already cached in localStorage (`context_length` from the
 * OpenAI-compatible `/v1/models` listing). When we can't resolve the active
 * model (catalog not loaded, or a local runtime that omits it) we fall back to
 * 1,000,000, matching the vendor-window default the feature was specced around.
 */

/** Fallback window when the active model's `context_length` is unknown. */
export const DEFAULT_CONTEXT_WINDOW = 1_000_000;

/** Fraction of the window at which we first nudge the user (500k on a 1M model). */
export const CONTEXT_WARN_RATIO = 0.5;

/** Fraction of the window at which the nudge escalates (800k on a 1M model). */
export const CONTEXT_CRITICAL_RATIO = 0.8;

export type ContextWindowLevel = 'ok' | 'warn' | 'critical';

export interface ContextWindowEvaluation {
  /** Tokens in the latest request (input + output). */
  used: number;
  /** Resolved context window for the active model. */
  window: number;
  /** `used / window`, clamped to >= 0. */
  ratio: number;
  level: ContextWindowLevel;
}

/** localStorage key prefix used by `lib/providerModels.ts` (`saveCachedModels`). */
const PROVIDER_MODELS_CACHE_PREFIX = 'eigent-provider-models-v1:';

/** Lowest plausible context length; guards against garbage in the catalog. */
const MIN_PLAUSIBLE_CONTEXT_LENGTH = 1_000;

const normalizeId = (value: unknown): string =>
  String(value ?? '')
    .trim()
    .toLowerCase();

/**
 * Catalog ids are often `provider/model` (e.g. `deepseek/deepseek-chat`) while
 * the runtime selection is the bare model (`deepseek-chat`). Match either
 * direction, and ignore a `:free`/`:tag` suffix.
 */
function modelIdsMatch(catalogId: string, targetId: string): boolean {
  const a = normalizeId(catalogId).replace(/:[^/]*$/, '');
  const b = normalizeId(targetId).replace(/:[^/]*$/, '');
  if (!a || !b) return false;
  if (a === b) return true;
  if (a.endsWith(`/${b}`)) return true;
  if (b.endsWith(`/${a}`)) return true;
  return false;
}

/**
 * Resolve the active model's context window from the cached provider catalog.
 * Scans every cached provider group (the cache is keyed per provider id, not
 * per model) so we don't need to know which provider the model came from.
 */
export function resolveContextWindow(modelId?: string | null): number {
  const target = normalizeId(modelId);
  if (!target) return DEFAULT_CONTEXT_WINDOW;

  try {
    if (typeof localStorage === 'undefined') return DEFAULT_CONTEXT_WINDOW;
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(PROVIDER_MODELS_CACHE_PREFIX)) continue;
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const groups = JSON.parse(raw);
      if (!Array.isArray(groups)) continue;
      for (const group of groups) {
        const models = Array.isArray(group?.models) ? group.models : [];
        for (const model of models) {
          const length = Number(model?.contextLength);
          if (
            Number.isFinite(length) &&
            length >= MIN_PLAUSIBLE_CONTEXT_LENGTH &&
            modelIdsMatch(model?.id, target)
          ) {
            return length;
          }
        }
      }
    }
  } catch {
    // Malformed cache entry — fall through to the default window.
  }

  return DEFAULT_CONTEXT_WINDOW;
}

/** Classify how full the window is for the latest request. */
export function evaluateContextWindow(
  usedTokens: number,
  windowTokens: number
): ContextWindowEvaluation {
  const window =
    Number.isFinite(windowTokens) && windowTokens > 0
      ? windowTokens
      : DEFAULT_CONTEXT_WINDOW;
  const used = Number.isFinite(usedTokens) && usedTokens > 0 ? usedTokens : 0;
  const ratio = used / window;
  const level: ContextWindowLevel =
    ratio >= CONTEXT_CRITICAL_RATIO
      ? 'critical'
      : ratio >= CONTEXT_WARN_RATIO
        ? 'warn'
        : 'ok';
  return { used, window, ratio, level };
}

/** Compact token label for banner copy: 512000 -> "512K", 1250000 -> "1.25M". */
export function formatTokenCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0';
  if (value >= 1_000_000) {
    const millions = value / 1_000_000;
    return `${Number(millions.toFixed(millions >= 10 ? 1 : 2))}M`;
  }
  if (value >= 1_000) {
    const thousands = value / 1_000;
    return `${Number(thousands.toFixed(thousands >= 100 ? 0 : 1))}K`;
  }
  return String(Math.round(value));
}
