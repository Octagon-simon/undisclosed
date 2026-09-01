// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
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

export interface AppHost {
  electronAPI: any;
  ipcRenderer: any;
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
}
