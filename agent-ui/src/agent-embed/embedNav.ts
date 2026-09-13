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
 * Tiny cross-component nav for the embedded agent panel. Shared components (the
 * composer's connector/skill pickers) live deep in ChatBox and can't reach the
 * panel's body state. In the desktop app they `navigate()` to a management page;
 * in the embed there is no such route, so they ALSO signal here and the panel
 * switches its body. In the desktop app nothing listens, so this is a harmless
 * no-op there.
 */

import { create } from 'zustand';

export type EmbedScreen =
  | 'conversation'
  | 'history'
  | 'stats'
  | 'skills'
  | 'connectors'
  | 'memory'
  | 'models'
  | 'settings'
  | 'browser';

interface EmbedNavState {
  /** A one-shot screen request from a shared component; the panel consumes it. */
  requested: EmbedScreen | null;
  requestScreen: (screen: EmbedScreen) => void;
  clearRequest: () => void;
}

export const useEmbedNav = create<EmbedNavState>((set) => ({
  requested: null,
  requestScreen: (screen) => set({ requested: screen }),
  clearRequest: () => set({ requested: null }),
}));

/** Convenience for shared components: request a panel screen (embed only). */
export function requestEmbedScreen(screen: EmbedScreen): void {
  useEmbedNav.getState().requestScreen(screen);
}
