// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Live brain (backend :5001) status pill for the agent panel. Polls the brain's
// /health directly so the user is never "left in the dark" about whether the
// backend is up — and, when it's down, offers a one-click Restart that asks the
// Theia backend (which can spawn processes; the renderer can't) to resurrect it.
// This dissolves the quit-app → restart-brain → relaunch-app dance.

import { useCallback, useEffect, useRef, useState } from 'react';

type BrainState = 'checking' | 'live' | 'dead' | 'restarting';

// The brain is a fixed-port local sidecar (see docs/PACKAGING.md). Health lives
// at /health (NOT under the /api proxy). Direct fetch works in dev + packaged
// (the brain sets permissive CORS on localhost).
const BRAIN_HEALTH_URL = 'http://localhost:5001/health';
// Served by the Theia backend (undisclosed-agent backend module), same origin as
// the panel — reachable even while the brain is down.
const BRAIN_RESTART_URL = '/undisclosed-agent/brain/restart';
const POLL_MS = 4000;

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

export function BrainStatus() {
  const [state, setState] = useState<BrainState>('checking');
  const mounted = useRef(true);

  const check = useCallback(async () => {
    const ok = await probe(BRAIN_HEALTH_URL);
    if (!mounted.current) return;
    // Don't stomp the transient "restarting" label with a stale dead-probe.
    setState((prev) => (prev === 'restarting' && !ok ? 'restarting' : ok ? 'live' : 'dead'));
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
      await fetch(BRAIN_RESTART_URL, { method: 'POST' });
    } catch {
      /* backend may not expose the route in this build — fall through to polling */
    }
    // Poll until it comes back (up to ~30s), then resume normal polling.
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 1500));
      if (!mounted.current) return;
      if (await probe(BRAIN_HEALTH_URL)) {
        if (mounted.current) setState('live');
        return;
      }
    }
    if (mounted.current) setState('dead');
  }, []);

  const color =
    state === 'live'
      ? '#3fb950'
      : state === 'dead'
        ? '#f85149'
        : '#d29922'; // checking / restarting
  const label =
    state === 'live'
      ? 'Brain live'
      : state === 'dead'
        ? 'Brain offline'
        : state === 'restarting'
          ? 'Restarting…'
          : 'Checking…';

  return (
    <div
      title={
        state === 'dead'
          ? 'The agent backend on :5001 is not responding. Click Restart to resurrect it.'
          : `Agent backend (:5001): ${label}`
      }
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontSize: 11,
        lineHeight: 1,
        userSelect: 'none',
        opacity: 0.85,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: color,
          boxShadow: `0 0 0 2px ${color}22`,
          transition: 'background 0.2s',
          animation:
            state === 'checking' || state === 'restarting'
              ? 'undisclosed-pulse 1s ease-in-out infinite'
              : undefined,
        }}
      />
      <span style={{ color: 'var(--theia-foreground, currentColor)' }}>{label}</span>
      {state === 'dead' && (
        <button
          onClick={restart}
          style={{
            marginLeft: 4,
            padding: '1px 8px',
            fontSize: 11,
            borderRadius: 4,
            border: '1px solid #f8514966',
            background: 'transparent',
            color: '#f85149',
            cursor: 'pointer',
          }}
        >
          Restart
        </button>
      )}
      <style>{`@keyframes undisclosed-pulse{0%,100%{opacity:1}50%{opacity:0.35}}`}</style>
    </div>
  );
}
