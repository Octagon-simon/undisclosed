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

/**
 * Brain REST API - MCP and Skills endpoints.
 * All calls go through Brain HTTP API (getBaseURL). No IPC fallback.
 */

import {
  fetchDelete,
  fetchGet,
  fetchPost,
  fetchPostForm,
  fetchPut,
} from './http';

export async function mcpList(): Promise<{
  mcpServers: Record<string, unknown>;
}> {
  const res = await fetchGet('/mcp/list');
  return res && typeof res.mcpServers === 'object' ? res : { mcpServers: {} };
}

export async function mcpInstall(
  name: string,
  mcp: Record<string, unknown>
): Promise<{ success: boolean }> {
  return fetchPost('/mcp/install', { name, mcp });
}

export async function mcpRemove(name: string): Promise<{ success: boolean }> {
  return fetchDelete(`/mcp/${encodeURIComponent(name)}`);
}

/**
 * Run the interactive OAuth sign-in for an `mcp-remote` connector: opens the
 * user's browser to authorize and resolves once the token is cached (or on
 * timeout). Long-running (up to ~3 min) — no client timeout is imposed.
 */
export async function mcpAuthenticate(
  name: string
): Promise<{ success: boolean; message?: string }> {
  return fetchPost('/mcp/authenticate', { name });
}

/** Names of connectors that have completed OAuth sign-in (persisted), so the
 *  UI can show "Authenticated" across reloads. */
export async function mcpAuthStatus(): Promise<{ authenticated: string[] }> {
  const res = await fetchGet('/mcp/auth-status');
  return {
    authenticated: Array.isArray(res?.authenticated) ? res.authenticated : [],
  };
}

export async function mcpUpdate(
  name: string,
  mcp: Record<string, unknown>
): Promise<{ success: boolean }> {
  return fetchPut(`/mcp/${encodeURIComponent(name)}`, mcp);
}

export async function skillsScan(): Promise<{
  success: boolean;
  skills: Array<{
    name: string;
    description: string;
    path: string;
    scope: string;
    skillDirName: string;
    isExample: boolean;
  }>;
}> {
  const res = await fetchGet('/skills');
  return res?.skills !== undefined ? res : { success: true, skills: [] };
}

export async function skillWrite(
  skillDirName: string,
  content: string
): Promise<{ success: boolean }> {
  return fetchPost(`/skills/${encodeURIComponent(skillDirName)}`, { content });
}

export async function skillImportZip(
  zipBuffer: ArrayBuffer,
  replacements?: string[]
): Promise<{
  success: boolean;
  error?: string;
  conflicts?: Array<{ folderName: string; skillName: string }>;
}> {
  const formData = new FormData();
  formData.append('file', new Blob([zipBuffer]), 'skill.zip');
  if (replacements?.length) {
    formData.append('replacements', replacements.join(','));
  }
  const res = await fetchPostForm('/skills/import', formData);
  return (res ?? { success: false, error: 'Import failed' }) as {
    success: boolean;
    error?: string;
    conflicts?: Array<{ folderName: string; skillName: string }>;
  };
}

export async function skillRead(
  skillDirName: string
): Promise<{ success: boolean; content: string }> {
  return fetchGet(`/skills/${encodeURIComponent(skillDirName)}`);
}

export async function skillDelete(
  skillDirName: string
): Promise<{ success: boolean }> {
  return fetchDelete(`/skills/${encodeURIComponent(skillDirName)}`);
}

export async function skillListFiles(
  skillDirName: string
): Promise<{ success: boolean; files: string[] }> {
  const res = await fetchGet(
    `/skills/${encodeURIComponent(skillDirName)}/files`
  );
  return res?.files !== undefined ? res : { success: true, files: [] };
}

export async function skillGetPathByName(
  skillName: string
): Promise<{ path: string } | null> {
  const res = await fetchGet(
    `/skills/path?name=${encodeURIComponent(skillName)}`
  );
  return res?.path ? { path: res.path } : null;
}

// --- Skill config (REST API, no Electron coupling) ---

export async function skillConfigLoad(
  userId: string,
  legacyUserId?: string | null
): Promise<{ success: boolean; config?: Record<string, unknown> }> {
  const legacyQuery = legacyUserId
    ? `&legacy_user_id=${encodeURIComponent(legacyUserId)}`
    : '';
  const res = await fetchGet(
    `/skills/config?user_id=${encodeURIComponent(userId)}${legacyQuery}`
  );
  return res?.config !== undefined ? res : { success: false };
}

export async function skillConfigInit(
  userId: string,
  legacyUserId?: string | null
): Promise<{ success: boolean; config?: Record<string, unknown> }> {
  const res = await fetchPost('/skills/config/init', {
    user_id: userId,
    ...(legacyUserId ? { legacy_user_id: legacyUserId } : {}),
  });
  return res?.config !== undefined ? res : { success: false };
}

export async function skillConfigUpdate(
  userId: string,
  skillName: string,
  config: {
    enabled?: boolean;
    scope?: { isGlobal?: boolean; selectedAgents?: string[] };
    addedAt?: number;
    isExample?: boolean;
  },
  legacyUserId?: string | null
): Promise<{ success: boolean }> {
  return fetchPut(`/skills/config/${encodeURIComponent(skillName)}`, {
    user_id: userId,
    ...(legacyUserId ? { legacy_user_id: legacyUserId } : {}),
    ...config,
  });
}

export async function skillConfigDelete(
  userId: string,
  skillName: string,
  legacyUserId?: string | null
): Promise<{ success: boolean }> {
  const legacyQuery = legacyUserId
    ? `&legacy_user_id=${encodeURIComponent(legacyUserId)}`
    : '';
  return fetchDelete(
    `/skills/config/${encodeURIComponent(skillName)}?user_id=${encodeURIComponent(userId)}${legacyQuery}`
  );
}

export async function skillConfigToggle(
  userId: string,
  skillName: string,
  enabled: boolean,
  legacyUserId?: string | null
): Promise<{ success: boolean; config?: Record<string, unknown> }> {
  const res = await fetchPost(
    `/skills/config/${encodeURIComponent(skillName)}/toggle`,
    {
      user_id: userId,
      enabled,
      ...(legacyUserId ? { legacy_user_id: legacyUserId } : {}),
    }
  );
  return res ?? { success: false };
}

/** Semantic-memory status: number of stored facts for this user. */
export async function memoryStatus(
  email?: string | null,
  userId?: string | number | null
): Promise<{ count: number }> {
  const params = new URLSearchParams();
  if (email) params.set('email', String(email));
  if (userId != null && userId !== '') params.set('user_id', String(userId));
  const qs = params.toString();
  const res = await fetchGet(`/memory/status${qs ? `?${qs}` : ''}`);
  return { count: Number(res?.count ?? 0) };
}

/** Clear this user's stored semantic-memory facts. Returns count removed. */
export async function memoryClear(
  email?: string | null,
  userId?: string | number | null
): Promise<{ removed: number }> {
  const params = new URLSearchParams();
  if (email) params.set('email', String(email));
  if (userId != null && userId !== '') params.set('user_id', String(userId));
  const qs = params.toString();
  const res = await fetchDelete(`/memory${qs ? `?${qs}` : ''}`);
  return { removed: Number(res?.removed ?? 0) };
}
