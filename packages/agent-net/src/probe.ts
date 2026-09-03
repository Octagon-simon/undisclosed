// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

/**
 * Standalone proof that @eigent/agent-net drives the Eigent backend with NO
 * Electron, NO authStore, NO IPC — everything injected. Run against a live
 * backend:
 *
 *   UNDISCLOSED_BASE_URL=http://localhost:5001 \
 *   UNDISCLOSED_TOKEN=<your token> \
 *   UNDISCLOSED_USER_ID=<id> \
 *   [UNDISCLOSED_SSE_PATH=/chat UNDISCLOSED_SSE_BODY='{"...":"..."}'] \
 *   node lib/probe.js
 *
 * Steps: (1) unauth transport check, (2) an authed GET if a token is given,
 * (3) an SSE turn if a stream path is given.
 */

import './node-shim'; // node-only; must load before the SSE import
import { AgentNetConfig } from './config';
import { createHttpClient } from './http';
import { openAgentStream } from './sse';

const BASE_URL = process.env.UNDISCLOSED_BASE_URL || 'http://localhost:5001';
const TOKEN = process.env.UNDISCLOSED_TOKEN || '';
const USER_ID = process.env.UNDISCLOSED_USER_ID || '';
const SSE_PATH = process.env.UNDISCLOSED_SSE_PATH || '';
const SSE_BODY = process.env.UNDISCLOSED_SSE_BODY || '';

const config: AgentNetConfig = {
  baseUrl: BASE_URL,
  getToken: () => TOKEN || null,
  getUserId: () => USER_ID || null,
};

const line = (s: string) => console.log(s);

async function main(): Promise<void> {
  line(`\n=== @eigent/agent-net probe ===`);
  line(`base URL: ${BASE_URL}`);
  const http = createHttpClient(config);

  // 1) Transport check (unauthenticated) — proves fetch client works standalone.
  try {
    const res = await http.raw('/');
    line(`[1] transport  GET /            -> HTTP ${res.status}  ${res.ok ? 'PASS ✅' : 'reachable'}`);
  } catch (err) {
    line(`[1] transport  GET /            -> FAIL ❌  ${(err as Error).message}`);
    line(`    (is the backend running at ${BASE_URL}?)`);
    return;
  }

  // 2) Authenticated GET — proves injected Bearer works end-to-end.
  if (TOKEN) {
    try {
      const providers = await http.get<unknown>('/api/v1/providers');
      const n = Array.isArray(providers)
        ? providers.length
        : Object.keys(providers as object).length;
      line(`[2] auth       GET /api/v1/providers -> PASS ✅ (${n} keys/items)`);
    } catch (err) {
      line(`[2] auth       GET /api/v1/providers -> FAIL ❌  ${(err as Error).message}`);
    }
  } else {
    line(`[2] auth       (skipped — set UNDISCLOSED_TOKEN to test the injected Bearer)`);
  }

  // 3) SSE turn — proves the streaming path works standalone.
  if (SSE_PATH) {
    line(`[3] stream     opening SSE ${SSE_PATH} …`);
    const ctrl = new AbortController();
    let count = 0;
    const done = new Promise<void>((resolve) => {
      const stop = () => {
        ctrl.abort();
        resolve();
      };
      const timer = setTimeout(stop, 15000);
      openAgentStream(
        config,
        SSE_PATH,
        {
          onOpen: () => line(`    stream open ✅`),
          onMessage: (m) => {
            count += 1;
            if (count <= 5) {
              line(`    event#${count} ${m.event ?? 'message'}: ${m.data.slice(0, 120)}`);
            }
            if (count >= 5) {
              clearTimeout(timer);
              line(`    received ${count}+ events — SSE turn PASS ✅`);
              stop();
            }
          },
          onError: (e) => line(`    stream error: ${(e as Error).message}`),
          onClose: () => line(`    stream closed (events=${count})`),
        },
        {
          body: SSE_BODY ? JSON.parse(SSE_BODY) : undefined,
          signal: ctrl.signal,
        }
      ).catch((e) => line(`    stream fatal: ${(e as Error).message}`));
    });
    await done;
  } else {
    line(`[3] stream     (skipped — set UNDISCLOSED_SSE_PATH e.g. /chat + UNDISCLOSED_SSE_BODY)`);
  }

  line(`=== done ===\n`);
}

void main();
