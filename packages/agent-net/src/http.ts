// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { AgentNetConfig, isRelative, normalizeBaseUrl } from './config';

export interface HttpClient {
  get<T = unknown>(path: string, params?: Record<string, unknown>): Promise<T>;
  post<T = unknown>(path: string, body?: unknown): Promise<T>;
  put<T = unknown>(path: string, body?: unknown): Promise<T>;
  /** Escape hatch: full Response for streaming/binary/custom handling. */
  raw(path: string, init?: RequestInit): Promise<Response>;
}

export class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly url: string,
    readonly body: string
  ) {
    super(`HTTP ${status} for ${url}`);
    this.name = 'HttpError';
  }
}

async function resolveToken(config: AgentNetConfig): Promise<string | null> {
  const t = await config.getToken?.();
  return t ?? null;
}

/**
 * Build headers, mirroring the app's rule: attach `Authorization: Bearer` only
 * to Brain-relative paths (absolute URLs may be third-party and must not carry
 * the user's token). See `src/api/http.ts:shouldAttachAuthHeader`.
 */
async function buildHeaders(
  config: AgentNetConfig,
  path: string,
  extra: Record<string, string> = {},
  json = true
): Promise<Record<string, string>> {
  const headers: Record<string, string> = { ...extra };
  if (json) headers['Content-Type'] = 'application/json';
  if (isRelative(path)) {
    const token = await resolveToken(config);
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const userId = config.getUserId?.();
    if (userId !== undefined && userId !== null) {
      headers['x-user-id'] = String(userId);
    }
    const sessionId = config.getSessionId?.();
    if (sessionId) headers['x-session-id'] = sessionId;
  }
  return headers;
}

function fullUrl(config: AgentNetConfig, path: string): string {
  if (!isRelative(path)) return path;
  return `${normalizeBaseUrl(config.baseUrl)}${path.startsWith('/') ? '' : '/'}${path}`;
}

function withQuery(url: string, params?: Record<string, unknown>): string {
  if (!params) return url;
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) usp.append(k, String(v));
  }
  const qs = usp.toString();
  return qs ? `${url}${url.includes('?') ? '&' : '?'}${qs}` : url;
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  if (!res.ok) throw new HttpError(res.status, res.url, text);
  if (!text) return undefined as unknown as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    return text as unknown as T;
  }
}

/** Create a transport bound to an injected config. No global stores, no IPC. */
export function createHttpClient(config: AgentNetConfig): HttpClient {
  return {
    async raw(path, init = {}) {
      const headers = await buildHeaders(
        config,
        path,
        (init.headers as Record<string, string>) ?? {},
        false
      );
      return fetch(fullUrl(config, path), { ...init, headers });
    },
    async get<T>(path: string, params?: Record<string, unknown>) {
      const headers = await buildHeaders(config, path, {}, false);
      const res = await fetch(withQuery(fullUrl(config, path), params), {
        method: 'GET',
        headers,
      });
      return parse<T>(res);
    },
    async post<T>(path: string, body?: unknown) {
      const headers = await buildHeaders(config, path);
      const res = await fetch(fullUrl(config, path), {
        method: 'POST',
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return parse<T>(res);
    },
    async put<T>(path: string, body?: unknown) {
      const headers = await buildHeaders(config, path);
      const res = await fetch(fullUrl(config, path), {
        method: 'PUT',
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return parse<T>(res);
    },
  };
}
