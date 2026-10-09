// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Live brain (backend :5001) health polling.
//
// Extracted from the `BrainStatus` pill (see ./index.tsx) so the panel telemetry
// sub-strip and any other brain-aware surface share ONE poller instead of each
// mounting its own `/health` interval. Polls the brain directly (it sets
// permissive CORS on localhost) and, when it's down, exposes a `restart()` that
// asks the Theia backend to respawn it — the renderer can't spawn processes.
// This dissolves the quit-app → restart-brain → relaunch-app dance.

import { useCallback, useEffect, useRef, useState } from 'react';

export type BrainState = 'checking' | 'live' | 'dead' | 'restarting';

// Health lives at /health (NOT under the /api proxy).
const BRAIN_HEALTH_URL = 'http://localhost:5001/health';
const POLL_MS = 4000;

// Must be an ABSOLUTE url: the packaged app runs the panel from a file:// page,
// so a relative '/undisclosed-agent/...' resolves to file:///… and 404s
// (ERR_FILE_NOT_FOUND). mount.tsx stashes the real backend origin on window.
function brainRestartUrl(): string {
  const origin = (
    window as unknown as { __UNDISCLOSED_BACKEND_ORIGIN__?: string }
  ).__UNDISCLOSED_BACKEND_ORIGIN__;
  const base = origin && /^https?:\/\//.test(origin) ? origin : '';
  return `${base}/undisclosed-agent/brain/restart`;
}

async function probe(url: string, timeoutMs = 2500): Promise<boolean> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal, cache: 'no-store' });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

export function useBrainStatus(): {
  state: BrainState;
  restart: () => Promise<void>;
} {
  const [state, setState] = useState<BrainState>('checking');
  const mounted = useRef(true);
  // Only re-bootstrap on a DEAD→LIVE recovery, not on a normal live launch
  // (mount already bootstrapped then). Set once we've observed a dead probe.
  const sawDead = useRef(false);

  const check = useCallback(async () => {
    const ok = await probe(BRAIN_HEALTH_URL);
    if (!mounted.current) return;
    if (!ok) {
      sawDead.current = true;
    } else if (sawDead.current) {
      // Brain recovered after being down: re-run workspace bootstrap so a null
      // activeSpaceId (from a load that failed while it was dead) recovers and
      // History/refresh work again without a full app relaunch.
      sawDead.current = false;
      const reboot = (
        window as unknown as { __UNDISCLOSED_REBOOTSTRAP__?: () => Promise<void> }
      ).__UNDISCLOSED_REBOOTSTRAP__;
      if (reboot) {
        void reboot().catch(() => {
          /* best-effort recovery */
        });
      }
    }
    // Don't stomp the transient "restarting" label with a stale dead-probe.
    setState((prev) =>
      prev === 'restarting' && !ok ? 'restarting' : ok ? 'live' : 'dead'
    );
  }, []);

  useEffect(() => {
    mounted.current = true;
    void check();
    const id = setInterval(() => void check(), POLL_MS);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, [check]);

  const restart = useCallback(async () => {
    setState('restarting');
    try {
      await fetch(brainRestartUrl(), { method: 'POST' });
    } catch {
      /* backend may not expose the route in this build — fall through to polling */
    }
    // Poll until it answers. The frozen brain binary has a SLOW cold start
    // (~20-40s: it imports camel/chromadb/etc. before binding /health), so a
    // short window made the pill flash "offline" while the brain was still
    // booting — then the background poll caught it and flipped to "live"
    // ("restarting → offline → live"). Keep showing "restarting" for the whole
    // window so the state reflects reality; the background check() also promotes
    // to "live" the moment it answers, so we never get stuck.
    const deadline = Date.now() + 90_000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 1500));
      if (!mounted.current) return;
      if (await probe(BRAIN_HEALTH_URL)) {
        if (mounted.current) setState('live');
        return;
      }
    }
    // Only after a genuinely long wait do we call it dead (real failure).
    if (mounted.current) setState('dead');
  }, []);

  return { state, restart };
}
