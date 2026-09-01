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
 * Live view + manual "take control" of the agent's browser, for the editor-first
 * (Theia) embed where there is no native Electron webview.
 *
 * It opens a WebSocket to the Brain's `/browser/stream` bridge, which attaches a
 * second CDP client to the agent's Chromium, streams `Page.startScreencast`
 * frames here, and forwards the input we send back as `Input.dispatch*`. Passive
 * by default (frames only); "Take control" pauses the agent (the existing
 * `/task/{id}/take-control` PUT) and starts forwarding mouse/keyboard so the user
 * can click, type, scroll and log in. Everything stays on localhost.
 */

import { fetchPut } from '@/api/http';
import { getConnectionConfig } from '@/store/connectionStore';
import { useProjectStore } from '@/store/projectStore';
import { Loader2, MousePointerClick, Wifi, WifiOff } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

/** Latest screencast frame geometry, used to map cursor → page coordinates. */
interface FrameMeta {
  deviceWidth: number;
  deviceHeight: number;
}

function brainWsUrl(): string | null {
  const base = getConnectionConfig().brainEndpoint;
  if (!base) return null;
  const ws = base.replace(/^http/i, (m) => (m.toLowerCase() === 'https' ? 'wss' : 'ws'));
  // The above only maps the scheme when it starts with http/https; ensure ws/wss.
  const normalized = /^wss?:/i.test(ws)
    ? ws
    : base.replace(/^https:/i, 'wss:').replace(/^http:/i, 'ws:');
  // Higher JPEG quality — it's all localhost, so bandwidth is free. The DPR is
  // sent per-frame-config via the `viewport` message (it can change per monitor).
  return normalized.replace(/\/+$/, '') + '/browser/stream?quality=85';
}

type Status = 'connecting' | 'live' | 'error' | 'closed';

export default function BrowserTakeControl() {
  const activeProjectId = useProjectStore((s) => s.activeProjectId);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const metaRef = useRef<FrameMeta | null>(null);
  const controllingRef = useRef(false);

  const [status, setStatus] = useState<Status>('connecting');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [controlling, setControlling] = useState(false);
  const [pageUrl, setPageUrl] = useState<string>('');

  // Keep a ref in sync so the (stable) input listeners read the live value.
  useEffect(() => {
    controllingRef.current = controlling;
  }, [controlling]);

  const send = useCallback((msg: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }, []);

  // Draw an incoming JPEG frame onto the canvas at its natural size.
  const drawFrame = useCallback((dataB64: string) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const img = new Image();
    img.onload = () => {
      if (canvas.width !== img.naturalWidth) canvas.width = img.naturalWidth;
      if (canvas.height !== img.naturalHeight) canvas.height = img.naturalHeight;
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.drawImage(img, 0, 0);
    };
    img.src = `data:image/jpeg;base64,${dataB64}`;
  }, []);

  // Open the stream on mount; tear it down on unmount.
  useEffect(() => {
    const url = brainWsUrl();
    if (!url) {
      setStatus('error');
      setErrorMsg('No brain endpoint configured.');
      return;
    }
    let closedByUs = false;
    const ws = new WebSocket(url);
    wsRef.current = ws;
    setStatus('connecting');

    // Match the bridge's capture to the panel's exact size AND the display's
    // real pixel ratio, so a Retina panel gets a crisp 2x frame instead of an
    // upscaled 1x one. Re-sent whenever the panel resizes.
    const sendViewport = () => {
      const el = canvasRef.current?.parentElement;
      if (!el || !el.clientWidth) return;
      send({
        type: 'viewport',
        width: Math.round(el.clientWidth),
        height: Math.round(el.clientHeight),
        deviceScaleFactor: window.devicePixelRatio || 1,
      });
    };

    ws.onopen = () => sendViewport();

    // Keep the capture resolution in step with the panel as the user resizes
    // the dock (debounced so we don't thrash startScreencast).
    let resizeTimer: ReturnType<typeof setTimeout> | undefined;
    const ro = new ResizeObserver(() => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(sendViewport, 200);
    });
    const container = canvasRef.current?.parentElement;
    if (container) ro.observe(container);

    ws.onmessage = (event) => {
      let msg: any;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type === 'frame') {
        setStatus('live');
        const m = msg.metadata;
        if (m && typeof m.deviceWidth === 'number') {
          metaRef.current = {
            deviceWidth: m.deviceWidth,
            deviceHeight: m.deviceHeight,
          };
        }
        if (msg.data) drawFrame(msg.data);
      } else if (msg.type === 'ready') {
        setStatus('live');
        if (msg.url) setPageUrl(msg.url);
      } else if (msg.type === 'error') {
        setStatus('error');
        setErrorMsg(msg.message || 'Browser stream error.');
      }
    };

    ws.onerror = () => {
      if (!closedByUs) {
        setStatus('error');
        setErrorMsg((prev) => prev ?? 'Could not connect to the browser stream.');
      }
    };

    ws.onclose = () => {
      if (!closedByUs) setStatus((s) => (s === 'error' ? s : 'closed'));
    };

    return () => {
      closedByUs = true;
      ro.disconnect();
      clearTimeout(resizeTimer);
      try {
        ws.close();
      } catch {
        /* noop */
      }
      wsRef.current = null;
    };
  }, [send, drawFrame]);

  // Map a pointer event on the (CSS-scaled) canvas to page CSS pixels: the
  // fraction across the displayed canvas × the device dimensions the bridge
  // reported. Falls back to the frame's natural size.
  const toPageCoords = useCallback(
    (e: React.MouseEvent | React.WheelEvent): { x: number; y: number } => {
      const canvas = canvasRef.current;
      if (!canvas) return { x: 0, y: 0 };
      const rect = canvas.getBoundingClientRect();
      const fx = rect.width ? (e.clientX - rect.left) / rect.width : 0;
      const fy = rect.height ? (e.clientY - rect.top) / rect.height : 0;
      const meta = metaRef.current;
      const w = meta?.deviceWidth || canvas.width;
      const h = meta?.deviceHeight || canvas.height;
      return { x: Math.round(fx * w), y: Math.round(fy * h) };
    },
    []
  );

  const modsOf = (e: React.MouseEvent | React.WheelEvent | React.KeyboardEvent) => ({
    alt: e.altKey,
    ctrl: e.ctrlKey,
    meta: e.metaKey,
    shift: e.shiftKey,
  });

  const buttonName = (button: number): string =>
    button === 2 ? 'right' : button === 1 ? 'middle' : 'left';

  // --- input handlers (only forward while controlling) ---
  const onMouseMove = (e: React.MouseEvent) => {
    if (!controllingRef.current) return;
    const { x, y } = toPageCoords(e);
    send({ type: 'mousemove', x, y, buttons: e.buttons, modifiers: modsOf(e) });
  };
  const onMouseDown = (e: React.MouseEvent) => {
    if (!controllingRef.current) return;
    canvasRef.current?.focus();
    const { x, y } = toPageCoords(e);
    send({
      type: 'mousedown',
      x,
      y,
      button: buttonName(e.button),
      buttons: e.buttons,
      clickCount: e.detail || 1,
      modifiers: modsOf(e),
    });
  };
  const onMouseUp = (e: React.MouseEvent) => {
    if (!controllingRef.current) return;
    const { x, y } = toPageCoords(e);
    send({
      type: 'mouseup',
      x,
      y,
      button: buttonName(e.button),
      buttons: e.buttons,
      clickCount: e.detail || 1,
      modifiers: modsOf(e),
    });
  };
  const onWheel = (e: React.WheelEvent) => {
    if (!controllingRef.current) return;
    const { x, y } = toPageCoords(e);
    send({ type: 'wheel', x, y, deltaX: e.deltaX, deltaY: e.deltaY, modifiers: modsOf(e) });
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!controllingRef.current) return;
    e.preventDefault();
    send({ type: 'keydown', key: e.key, code: e.code, modifiers: modsOf(e) });
  };
  const onKeyUp = (e: React.KeyboardEvent) => {
    if (!controllingRef.current) return;
    e.preventDefault();
    send({ type: 'keyup', key: e.key, code: e.code, modifiers: modsOf(e) });
  };

  const toggleControl = useCallback(async () => {
    const next = !controlling;
    setControlling(next);
    if (next) canvasRef.current?.focus();
    // Pause the agent while the human drives; resume when releasing control.
    if (activeProjectId) {
      try {
        await fetchPut(`/task/${activeProjectId}/take-control`, {
          action: next ? 'pause' : 'resume',
        });
      } catch {
        /* best-effort: the stream still works even if the pause call fails */
      }
    }
  }, [controlling, activeProjectId]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Status / control bar */}
      <div className="flex shrink-0 items-center gap-2 px-3 py-2">
        <StatusPill status={status} />
        <span className="min-w-0 flex-1 truncate text-label-xs text-ds-text-neutral-subtle-default">
          {pageUrl || 'Agent browser'}
        </span>
        <button
          type="button"
          onClick={toggleControl}
          disabled={status !== 'live'}
          className={
            'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-label-xs font-semibold outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-50 ' +
            (controlling
              ? 'bg-ds-bg-warning-default-default text-ds-text-warning-strong-default'
              : 'bg-ds-bg-neutral-muted-default text-ds-text-neutral-default-default hover:bg-ds-bg-neutral-default-default')
          }
        >
          <MousePointerClick size={13} aria-hidden />
          {controlling ? 'Release control' : 'Take control'}
        </button>
      </div>

      {/* Live surface */}
      <div className="relative min-h-0 flex-1 overflow-hidden bg-black/90">
        <canvas
          ref={canvasRef}
          tabIndex={0}
          onMouseMove={onMouseMove}
          onMouseDown={onMouseDown}
          onMouseUp={onMouseUp}
          onContextMenu={(e) => e.preventDefault()}
          onWheel={onWheel}
          onKeyDown={onKeyDown}
          onKeyUp={onKeyUp}
          className={
            'absolute inset-0 h-full w-full object-contain outline-none ' +
            (controlling ? 'cursor-crosshair' : 'cursor-default')
          }
          style={{ objectFit: 'contain' }}
        />
        {status !== 'live' && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center">
            <div className="flex max-w-[320px] flex-col items-center gap-2">
              {status === 'connecting' ? (
                <>
                  <Loader2 className="h-5 w-5 animate-spin text-white/70" aria-hidden />
                  <div className="text-body-sm text-white/80">
                    Connecting to the agent's browser…
                  </div>
                </>
              ) : (
                <>
                  <WifiOff className="h-5 w-5 text-white/60" aria-hidden />
                  <div className="text-body-sm text-white/80">
                    {errorMsg ||
                      'The agent has no browser open yet. Ask it to visit a page, then reopen this view.'}
                  </div>
                </>
              )}
            </div>
          </div>
        )}
        {controlling && status === 'live' && (
          <div className="pointer-events-none absolute left-1/2 top-2 -translate-x-1/2 rounded-full bg-ds-bg-warning-default-default px-3 py-1 text-label-xs font-semibold text-ds-text-warning-strong-default shadow">
            You're controlling the browser — the agent is paused
          </div>
        )}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: Status }) {
  const live = status === 'live';
  return (
    <span
      className={
        'flex items-center gap-1 rounded-full px-2 py-0.5 text-label-xs font-medium ' +
        (live
          ? 'bg-ds-bg-success-subtle-default text-ds-text-success-strong-default'
          : 'bg-ds-bg-neutral-muted-default text-ds-text-neutral-subtle-default')
      }
    >
      {live ? <Wifi size={12} aria-hidden /> : <WifiOff size={12} aria-hidden />}
      {live ? 'Live' : status === 'connecting' ? 'Connecting' : 'Offline'}
    </span>
  );
}
