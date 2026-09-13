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
// Host abstraction: desktop (Electron) vs web. No explicit platform checks.
// See docs/design/04-client.md.

/**
 * What the host knows about the file the user is currently looking at in the
 * editor. Lets the agent sync context (which file is open) with zero shell
 * calls. All fields optional beyond `path` so hosts can supply what they have.
 */
export interface ActiveEditorInfo {
  /** Absolute path of the active editor's file. */
  path: string;
  /** Monaco/Theia language id (e.g. "typescript", "python"), if known. */
  languageId?: string;
  /** 1-based selection range, when there is a selection/cursor. */
  selection?: { startLine: number; endLine: number } | null;
}

/** What the host's ACTIVE color theme looks like to the panel. */
export interface HostThemeInfo {
  /** The theme's own id (Theia: 'dark', 'light', 'hc-black', 'hc-light', ...). */
  id?: string;
  /** Resolved mode. This is the part the panel actually needs. */
  type: 'light' | 'dark';
  /** Host-resolved name, for diagnostics only. */
  label?: string;
}

export interface AppHost {
  electronAPI: any;
  ipcRenderer: any;
  /**
   * Subscribe to active-editor changes so the agent always knows which file is
   * open without shelling out. Returns an unsubscribe function. Optional: hosts
   * without an editor (the default web host) omit it. The Theia embed wires this
   * to Monaco's EditorManager.
   */
  onActiveEditorChanged?(
    cb: (info: ActiveEditorInfo | null) => void
  ): () => void;
  /** Current active editor synchronously, if the host tracks one. */
  getActiveEditor?(): ActiveEditorInfo | null;
  /**
   * Open a file in the host's editor (e.g. Theia's OpenerService), used by the
   * activity trace's clickable filenames. Optional: hosts that can't open files
   * (the default web host) simply omit it. `path` may be absolute or relative
   * to the workspace root — the host resolves it.
   */
  openFile?(path: string): void | Promise<void>;
  /**
   * Read a local file and return it as a `data:` URL the browser can render,
   * or `null` if it can't be read. Used by the markdown renderer to display
   * agent-output images (referenced by relative/absolute path) in a host that
   * has no Electron `readFileAsDataUrl` — e.g. the Theia embed, which reads the
   * bytes via its own FileService. `path` may be absolute or relative to the
   * workspace root; the host resolves it. Optional: the default web host omits
   * it (images fall back to alt text).
   */
  readFileAsDataUrl?(path: string): Promise<string | null>;
  /**
   * The host's ACTIVE color theme. The embedded panel is themed by the host's
   * own CSS (`theme.css` maps `--ds-*` onto Theia's `--theia-*` vars), so the
   * host is the authoritative answer to "is this surface dark?" — the panel's
   * stored appearance can say light while the editor is dark, which is exactly
   * how a dark-filled logo (OpenAI/Anthropic) ended up black-on-dark. Optional:
   * standalone/desktop mounts have no host theme and use their own appearance.
   */
  getTheme?(): HostThemeInfo;
  /**
   * Subscribe to host theme switches so the panel can re-render (logo inversion,
   * etc.) the moment the user changes the editor theme. Returns an unsubscribe
   * function. Optional.
   */
  onThemeChanged?(cb: (theme: HostThemeInfo) => void): () => void;
}
