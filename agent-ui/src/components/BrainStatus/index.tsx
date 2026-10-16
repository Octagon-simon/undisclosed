// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// BrainStatus — the live brain (backend :5001) indicator for the agent panel:
// a coloured dot + label, plus a one-click Restart when the brain is down.
//
// It is PRESENTATIONAL: the `/health` polling lives in ./useBrainStatus so the
// panel telemetry sub-strip and this pill share a single poller instead of two.
// Colors are semantic `ds-*` tokens only — no literal hex — so it re-themes with
// the app (light/dark + Theia).

import { StatusDot } from '@/components/ChatBox/MessageItem/PanelSection';
import type { BrainState } from './useBrainStatus';

export type { BrainState } from './useBrainStatus';

const LABELS: Record<BrainState, string> = {
  checking: 'Checking…',
  live: 'Brain live',
  dead: 'Brain offline',
  restarting: 'Restarting…',
};

// Green when live, red when down, amber while checking / restarting.
const DOT_TONE: Record<BrainState, string> = {
  live: 'bg-ds-bg-status-completed-default-default',
  dead: 'bg-ds-bg-error-default-default',
  checking: 'bg-ds-bg-warning-default-default',
  restarting: 'bg-ds-bg-warning-default-default',
};

export function BrainStatus({
  state,
  onRestart,
}: {
  state: BrainState;
  onRestart: () => void;
}) {
  const label = LABELS[state];

  return (
    <span
      title={
        state === 'dead'
          ? 'The agent backend on :5001 is not responding. Click Restart to resurrect it.'
          : `Agent backend (:5001): ${label}`
      }
      className="inline-flex items-center gap-1.5"
    >
      <StatusDot
        pulse={state === 'checking' || state === 'restarting'}
        className={DOT_TONE[state]}
      />
      <span>{label}</span>
      {state === 'dead' && (
        <button
          type="button"
          onClick={onRestart}
          className="ml-1 rounded border border-ds-border-status-error-default-default px-2 py-[1px] text-ds-text-status-error-strong-default outline-none transition-colors hover:bg-ds-bg-status-error-subtle-default"
        >
          Restart
        </button>
      )}
    </span>
  );
}
