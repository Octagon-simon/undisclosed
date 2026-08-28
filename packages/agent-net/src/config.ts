// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

/**
 * Everything the agent transport needs, INJECTED — so the same code runs in
 * Electron (values from authStore + main process) and in the Theia widget
 * (values handed off via config/URL/login). No global stores, no IPC.
 */
export interface AgentNetConfig {
  /** Backend base URL, e.g. "http://localhost:5001" (trailing slash tolerated). */
  baseUrl: string;
  /** Current bearer token, or null when unauthenticated. Async allows refresh. */
  getToken?: () =>
    | string
    | null
    | undefined
    | Promise<string | null | undefined>;
  /** Current user id, sent as `x-user-id` when present (some routes read it). */
  getUserId?: () => string | number | null | undefined;
  /** Optional session id echoed back as `x-session-id` (sticky routing). */
  getSessionId?: () => string | null | undefined;
}

/** Normalize the base URL once (strip trailing slash). */
export function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, '');
}

/** True for Brain-relative paths (which carry auth); absolute URLs do not. */
export function isRelative(path: string): boolean {
  return !/^https?:\/\//i.test(path);
}
