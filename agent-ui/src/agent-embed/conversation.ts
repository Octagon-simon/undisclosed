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
 * Conversation creation for the embedded agent panel.
 *
 * The bare `projectStore.createProject` is CLIENT-ONLY — it never persists a
 * project to the server, so a conversation created that way vanishes on reload
 * or folder switch (History pulls projects from the server, not local state).
 * When a real (non-legacy) Space is active — the common case, one Space per open
 * folder — we route through `createSyncedProjectInSpace`, which writes the
 * project server-side (`serverSynced: true`) so it survives a reload and shows
 * up in History. Only when there's no server-backed Space (a bare/blank embed)
 * do we fall back to the local-only project so the panel still works.
 */

import {
  createSyncedProjectInSpace,
  LegacySpaceProjectError,
} from '@/lib/spaceProject';
import { useProjectStore } from '@/store/projectStore';
import { useSpaceStore } from '@/store/spaceStore';

/**
 * Create a new conversation for the agent panel and make it active. Prefers a
 * server-persisted project so the conversation is retained across reloads;
 * falls back to a local-only project when there's no usable Space or the server
 * create fails. Returns the new project id.
 */
export async function createEmbedConversation(name: string): Promise<string> {
  const projectStore = useProjectStore.getState();
  const activeSpaceId = useSpaceStore.getState().activeSpaceId;

  if (activeSpaceId && !activeSpaceId.startsWith('legacy_')) {
    try {
      const { projectId } = await createSyncedProjectInSpace({
        projectStore,
        spaceId: activeSpaceId,
        name,
      });
      return projectId;
    } catch (err) {
      // Legacy Spaces are read-only; any other failure (offline, server error)
      // shouldn't strand the user — fall through to a local conversation.
      if (!(err instanceof LegacySpaceProjectError)) {
        console.warn(
          '[agent-embed] server-backed conversation create failed; using local:',
          err
        );
      }
    }
  }

  return projectStore.createProject(name);
}
