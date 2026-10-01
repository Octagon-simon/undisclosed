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
 * The window itself is resolved from the user's OWN provider model catalog the
 * Models screen cached in localStorage (`context_length` from each provider's
 * OpenAI-compatible `/v1/models` listing) — BYOK/local, no hosted assumptions.
 * When we can't resolve the active model (catalog not loaded, or a local runtime
 * that omits `context_length`) we fall back to a generous default so the gauge
 * simply doesn't nag.
 */

/** Generous fallback window when the active model's `context_length` is unknown. */
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
 * Fallback context windows for well-known model FAMILIES, used only when the
 * cached provider catalog can't resolve the model (most OpenAI-compatible
 * `/v1/models` endpoints — deepseek, anthropic, … — omit `context_length`).
 * Matched by substring against the model id first, then the provider id; first
 * match wins.
 *
 * Values are the CURRENT-FLAGSHIP windows for each family (verified Sep 2026,
 * sources in the commit) and deliberately biased LARGER — a family spans several
 * generations (e.g. gpt-4o 128k vs gpt-5.x ~1M), and under-warning on an older
 * model is far better UX than falsely nagging on a current one. deepseek V4
 * (Flash/Pro/chat) ships a documented 1M window; older deepseek-chat/reasoner
 * (V3.x) is 128k — so the V4 rule MUST precede the generic one (first match
 * wins). Unknown models keep the 1M default. One line each to tune.
 */
const KNOWN_FAMILY_WINDOWS: Array<[RegExp, number]> = [
  [/deepseek.*v4|deepseek-?v4|v4.*deepseek/, 1_000_000], // DeepSeek V4 Flash/Pro/chat — 1M (spec; some served endpoints cap ~160k, caught by the /v1/models cache when reported)
  [/deepseek/, 128_000], // deepseek-chat / reasoner (V3.x) — documented 128k
  [/gemini/, 1_000_000], // Gemini 3.1 Pro 1M (2M on some)
  [/claude|anthropic|sonnet|opus|haiku/, 1_000_000], // Sonnet 5 / Opus 4.8+ = 1M
  [/gpt-5|gpt-4|gpt4|o1|o3|o4|codex|openai/, 1_000_000], // GPT-5.x ~1M
  [/qwen|qwq|tongyi/, 1_000_000], // Qwen 3.5 ~1M
  [/grok/, 1_000_000], // Grok 4.x (500k–2M across versions)
  [/minimax/, 1_000_000],
  [/mistral|mixtral|codestral|magistral/, 256_000], // Mistral Large 3 = 256k
  [/kimi|moonshot/, 256_000], // Kimi K2.x 128k–256k
  [/llama|nemotron|nvidia/, 256_000], // Llama 3.x 128k / 4 Scout far larger
  [/glm|z\.?ai/, 200_000], // GLM-4.6 ~200k
];

function windowFromKnownFamily(
  modelId: string,
  providerId?: string | null
): number | null {
  const hay = `${modelId} ${normalizeId(providerId)}`.trim();
  if (!hay) return null;
  for (const [pattern, window] of KNOWN_FAMILY_WINDOWS) {
    if (pattern.test(hay)) return window;
  }
  return null;
}

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

/** Find a matching model's context length within one cache entry's groups. */
function windowFromGroups(groups: unknown, target: string): number | null {
  if (!Array.isArray(groups)) return null;
  for (const group of groups) {
    const models = Array.isArray((group as { models?: unknown })?.models)
      ? (group as { models: unknown[] }).models
      : [];
    for (const model of models) {
      const length = Number((model as { contextLength?: unknown })?.contextLength);
      if (
        Number.isFinite(length) &&
        length >= MIN_PLAUSIBLE_CONTEXT_LENGTH &&
        modelIdsMatch((model as { id?: unknown })?.id as string, target)
      ) {
        return length;
      }
    }
  }
  return null;
}

/**
 * Resolve a model's context window from the cached provider catalog
 * (`context_length` the Models screen fetched from each provider's
 * OpenAI-compatible `/v1/models`). This is BYOK/local-first: the window comes
 * from the user's OWN configured provider, not any hosted default.
 *
 * Pass the selection's `providerId` (the provider catalog id === the pinned
 * row's `model_platform`, e.g. `deepseek`) to resolve against THAT provider's
 * cached models directly — the cache is keyed per provider, so this avoids a
 * same-model-id collision across two providers with different windows. Without
 * it we scan every cached provider group. When the model can't be resolved
 * (Models screen never opened, or a local runtime that omits `context_length`)
 * we fall back to a generous default so the gauge simply doesn't nag.
 */
export function resolveContextWindow(
  modelId?: string | null,
  opts?: { providerId?: string | null }
): number {
  const target = normalizeId(modelId);
  if (!target) return DEFAULT_CONTEXT_WINDOW;

  try {
    if (typeof localStorage === 'undefined') return DEFAULT_CONTEXT_WINDOW;

    // 1. Exact provider scope when we know which provider the model is pinned to.
    const providerId = String(opts?.providerId ?? '').trim();
    if (providerId) {
      const raw = localStorage.getItem(PROVIDER_MODELS_CACHE_PREFIX + providerId);
      if (raw) {
        const hit = windowFromGroups(JSON.parse(raw), target);
        if (hit != null) return hit;
      }
    }

    // 2. Fall back to scanning every cached provider group.
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(PROVIDER_MODELS_CACHE_PREFIX)) continue;
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const hit = windowFromGroups(JSON.parse(raw), target);
      if (hit != null) return hit;
    }
  } catch {
    // Malformed cache entry — fall through below.
  }

  // 3. Cache couldn't resolve it (provider omits context_length, or the Models
  //    screen was never opened) — fall back to a known family window so the
  //    gauge still works for common BYOK models, then the generous default.
  const family = windowFromKnownFamily(target, opts?.providerId);
  if (family != null) return family;

  return DEFAULT_CONTEXT_WINDOW;
}

/** Rough chars-per-token for a mixed code+prose transcript. */
const CHARS_PER_TOKEN = 4;

/**
 * Estimate the live context size from the loaded conversation, for when the
 * authoritative `lastRequestTokens` (reported by the Brain's request_usage event)
 * isn't available — most importantly when a LONG conversation is REOPENED after a
 * reload / brain restart: `lastRequestTokens` isn't persisted, so it resets to 0
 * and the gauge would read empty even though the context is already large. This
 * approximates the next request's input from the task's messages + tool I/O so
 * the banner can warn immediately, before another big turn is spent. Superseded
 * by the exact `lastRequestTokens` as soon as the next turn runs.
 */
export function estimateContextTokens(task: unknown): number {
  const t = task as {
    messages?: Array<{ content?: unknown; reasoning?: unknown }>;
    taskAssigning?: Array<{ log?: Array<{ data?: { message?: unknown } }> }>;
  } | null;
  if (!t) return 0;
  let chars = 0;
  const add = (v: unknown) => {
    if (typeof v === 'string') chars += v.length;
  };
  for (const m of t.messages ?? []) {
    add(m?.content);
    add(m?.reasoning);
  }
  // Tool call inputs/outputs usually dominate the context — include them.
  for (const agent of t.taskAssigning ?? []) {
    for (const entry of agent?.log ?? []) {
      add(entry?.data?.message);
    }
  }
  return Math.ceil(chars / CHARS_PER_TOKEN);
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
