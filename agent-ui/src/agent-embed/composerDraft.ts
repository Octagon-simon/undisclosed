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

/**
 * One-shot composer prefill. The welcome/empty state (rendered outside ChatBox)
 * can seed the composer text via this store; ChatBox consumes it into its local
 * `message` state and clears it. Harmless in the desktop app (nothing sets it).
 *
 * `selection` carries a code reference from the editor ("Send to Agent") so the
 * composer can show it as a pill until the message is sent.
 */

import { create } from 'zustand';

export interface ComposerSelection {
  /** Workspace-relative path. */
  path: string;
  /** 1-based first line, always <= endLine. */
  startLine: number;
  endLine: number;
}

interface ComposerDraftState {
  draft: string | null;
  setDraft: (text: string) => void;
  clearDraft: () => void;
  selection: ComposerSelection | null;
  setSelection: (selection: ComposerSelection | null) => void;
  clearSelection: () => void;
  focusRequestId: number;
  requestFocus: () => void;
}

export const useComposerDraft = create<ComposerDraftState>((set) => ({
  draft: null,
  setDraft: (text) => set({ draft: text }),
  clearDraft: () => set({ draft: null }),
  selection: null,
  setSelection: (selection) => set({ selection }),
  clearSelection: () => set({ selection: null }),
  focusRequestId: 0,
  requestFocus: () =>
    set((state) => ({ focusRequestId: state.focusRequestId + 1 })),
}));
