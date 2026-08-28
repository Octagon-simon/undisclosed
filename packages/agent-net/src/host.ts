// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

/**
 * `AppHost` — the *complete* host-capability surface the Eigent agent stack
 * reaches for today (audited from chatStore + ChatBox + http). In Electron these
 * are backed by `electronAPI` / IPC; in the Theia widget most are desktop-only
 * and no-op, a few map to Theia-native equivalents. Every method is OPTIONAL so
 * an adapter implements only what it can — callers must feature-detect.
 *
 * This is the ONLY seam that was Electron-coupled; isolating it here is what
 * makes the agent UI portable.
 */
export interface AppHost {
  // --- file access (attachments) ---
  /** Read a local file's bytes/base64 (Electron: ipc 'read-file'). */
  readFile?(path: string): Promise<unknown>;
  /** Native file/dir picker (Electron: electronAPI.selectFile). */
  selectFile?(options?: unknown): Promise<unknown>;
  /** Read a file as a data: URL (Electron: electronAPI.readFileAsDataUrl). */
  readFileAsDataUrl?(path: string): Promise<string>;

  // --- environment ---
  /** UI language (Electron: ipc 'get-system-language'; web: navigator.language). */
  getSystemLanguage?(): Promise<string>;
  /** Backend PATH for a user (Electron: ipc 'get-env-path'). */
  getEnvPath?(email: string): Promise<string>;
  /** Backend port (Electron: ipc 'get-backend-port'). In Theia the base URL is
   *  injected via AgentNetConfig instead, so this is usually omitted. */
  getBackendPort?(): Promise<number>;
  /** Restart the local backend (Electron only; no-op elsewhere). */
  restartBackend?(): Promise<void>;

  // --- desktop-only browser/CDP + webview (no-op in Theia) ---
  getBrowserPort?(): Promise<number>;
  getCdpBrowsers?(): Promise<unknown>;
  launchCdpBrowser?(...args: unknown[]): Promise<unknown>;
  hideAllWebview?(): Promise<void> | void;
  webviewDestroy?(id: string): Promise<void> | void;

  // --- misc integrations ---
  openSkillFolder?(...args: unknown[]): Promise<void> | void;
  codexSubscriptionStatus?(...args: unknown[]): Promise<unknown>;
}

/** No-op host: every capability absent. Safe default for the Theia widget until
 *  specific methods get Theia-native implementations. */
export const noopHost: AppHost = {};
