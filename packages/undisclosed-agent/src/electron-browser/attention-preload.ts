// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

// Preload half of the attention bridge. The generated frontend preload
// (src-gen/frontend/preload.js) calls preload() from here because this package
// declares `preload` in its theiaExtensions entry.
//
// Only the two fire-and-forget calls the panel needs are exposed. ipcRenderer
// itself never reaches the page.

import {
  ATTENTION_CLEAR_CHANNEL,
  ATTENTION_REQUEST_CHANNEL,
  AgentAttentionRequest,
} from '../electron-common/attention';

interface PreloadElectron {
  contextBridge: { exposeInMainWorld(key: string, api: unknown): void };
  ipcRenderer: { send(channel: string, ...args: unknown[]): void };
}

const { contextBridge, ipcRenderer } = require('electron') as PreloadElectron;

export const ATTENTION_BRIDGE_KEY = 'undisclosedAttention';

export function preload(): void {
  contextBridge.exposeInMainWorld(ATTENTION_BRIDGE_KEY, {
    request(request: AgentAttentionRequest): void {
      ipcRenderer.send(ATTENTION_REQUEST_CHANNEL, request);
    },
    clear(id: string): void {
      ipcRenderer.send(ATTENTION_CLEAR_CHANNEL, id);
    },
  });
}
