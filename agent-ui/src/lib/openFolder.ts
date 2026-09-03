// ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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
// ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========

// The absolute path of the folder currently open in the host editor (Theia).
// The agent-embed mount receives it as `config.workspaceRoot`; we stash it here
// so the chat-start request can ALWAYS forward it as `space_root_path`,
// independent of the (sometimes wrong / rootless) active Space. This guarantees
// the agent operates in the open folder instead of the legacy per-task dir.

let openFolderRoot: string | undefined;

export function setOpenFolderRoot(root: string | undefined | null): void {
  const normalized =
    typeof root === 'string' && root.trim() ? root.replace(/\/+$/, '') : undefined;
  openFolderRoot = normalized;
}

export function getOpenFolderRoot(): string | undefined {
  return openFolderRoot;
}
