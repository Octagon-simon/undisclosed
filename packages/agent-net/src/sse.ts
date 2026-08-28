// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import {
  EventStreamContentType,
  fetchEventSource,
} from '@microsoft/fetch-event-source';
import { AgentNetConfig, isRelative, normalizeBaseUrl } from './config';

export interface AgentStreamMessage {
  event?: string;
  data: string;
  id?: string;
}

export interface AgentStreamHandlers {
  onOpen?: (response: Response) => void | Promise<void>;
  onMessage: (msg: AgentStreamMessage) => void;
  onError?: (err: unknown) => void;
  onClose?: () => void;
}

export interface AgentStreamOptions {
  /** HTTP method for the stream request (Brain uses POST for /chat). */
  method?: 'GET' | 'POST';
  /** JSON body for POST streams. */
  body?: unknown;
  /** Abort to stop the stream. */
  signal?: AbortSignal;
}

/** A thrown open-error that stops fetch-event-source from retrying. */
export class FatalStreamError extends Error {}

/**
 * Open an SSE stream against the backend with injected base URL + auth. Same
 * `@microsoft/fetch-event-source` engine the app uses, but config-injected and
 * `openWhenHidden` (no `document` dependency) so it runs in a background widget
 * or headless. Returns the fetchEventSource promise (resolves when closed).
 */
export function openAgentStream(
  config: AgentNetConfig,
  path: string,
  handlers: AgentStreamHandlers,
  options: AgentStreamOptions = {}
): Promise<void> {
  const url = isRelative(path)
    ? `${normalizeBaseUrl(config.baseUrl)}${path.startsWith('/') ? '' : '/'}${path}`
    : path;

  return (async () => {
    const headers: Record<string, string> = { Accept: 'text/event-stream' };
    if (isRelative(path)) {
      const token = await config.getToken?.();
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const userId = config.getUserId?.();
      if (userId !== undefined && userId !== null) {
        headers['x-user-id'] = String(userId);
      }
    }
    const method = options.method ?? (options.body ? 'POST' : 'GET');
    if (options.body) headers['Content-Type'] = 'application/json';

    await fetchEventSource(url, {
      method,
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
      openWhenHidden: true,
      async onopen(response) {
        const ct = response.headers.get('content-type') || '';
        if (response.ok && ct.includes(EventStreamContentType)) {
          await handlers.onOpen?.(response);
          return;
        }
        // Non-stream / error response: fail fast, don't retry.
        const text = await response.text().catch(() => '');
        throw new FatalStreamError(
          `stream open failed: HTTP ${response.status} ${ct} ${text.slice(0, 200)}`
        );
      },
      onmessage(ev) {
        handlers.onMessage({ event: ev.event, data: ev.data, id: ev.id });
      },
      onerror(err) {
        handlers.onError?.(err);
        // Rethrow fatal errors to stop the retry loop; others → retry.
        if (err instanceof FatalStreamError) throw err;
      },
      onclose() {
        handlers.onClose?.();
      },
    });
  })();
}
