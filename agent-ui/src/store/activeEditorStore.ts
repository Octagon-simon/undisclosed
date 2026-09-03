// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { create } from 'zustand';
import type { ActiveEditorInfo } from '@/host/types';

/**
 * Holds the file currently open in the host editor (Theia), pushed from the
 * host bridge (`AppHost.onActiveEditorChanged`). The send path reads it so the
 * agent gets live "what am I looking at" context with zero shell calls. Null
 * when no editor is open or the host doesn't track one (e.g. the web host).
 */
interface ActiveEditorState {
  activeEditor: ActiveEditorInfo | null;
  setActiveEditor: (info: ActiveEditorInfo | null) => void;
}

export const useActiveEditorStore = create<ActiveEditorState>((set) => ({
  activeEditor: null,
  setActiveEditor: (info) => set({ activeEditor: info }),
}));
