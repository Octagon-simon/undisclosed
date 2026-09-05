// Copyright (c) 2026 Simon Ugorji

/**
 * Frontend debug logging. Off by default; enable in the browser console with:
 *
 *   localStorage.setItem('undisclosed_debug', '1')   // then reload
 *
 * or set `window.__UNDISCLOSED_DEBUG = true` at runtime. Mirrors the backend's
 * UNDISCLOSED_DEBUG dumps so a whole turn can be traced end to end.
 */
export function feDebugEnabled(): boolean {
  try {
    if (typeof window === 'undefined') return false;
    if ((window as unknown as { __UNDISCLOSED_DEBUG?: boolean }).__UNDISCLOSED_DEBUG)
      return true;
    return window.localStorage?.getItem('undisclosed_debug') === '1';
  } catch {
    return false;
  }
}

export function feDebug(label: string, ...args: unknown[]): void {
  if (!feDebugEnabled()) return;
  try {
    // eslint-disable-next-line no-console
    console.log(
      `%c[undisclosed:${label}]`,
      'color:#8b5cf6;font-weight:600',
      ...args
    );
  } catch {
    /* never break the app for a log */
  }
}
