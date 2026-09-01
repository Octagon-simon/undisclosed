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
 * Resolve an attachment reference to a URL the browser/embed can render.
 *
 * Uploaded attaches are stored as `upload://<stored_name>` refs (see
 * uploadFileToBrain); the Brain serves their bytes from
 * `/api/v1/files/upload-content?file_id=...&session_id=...`. An `<img src>`
 * bypasses the proxy header wrapper, so the session id (from the connection
 * config) is passed as a query param instead of the X-Session-ID header.
 *
 * Desktop (Electron) keeps using electronAPI.readFileAsDataUrl for absolute
 * local paths; this helper covers the web/embed path.
 */

import { getConnectionConfig } from '@/store/connectionStore';

const IMAGE_EXTENSIONS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'bmp',
  'svg',
  'avif',
  'ico',
]);

/**
 * Uploaded files are stored as `<sanitized_name>_<ms-timestamp>` (see
 * upload_file), so the real extension sits BEFORE a trailing `_<digits>`.
 * Strip that suffix before reading the extension / display name.
 */
function stripUploadTimestamp(name: string): string {
  return name.replace(/_\d{10,}$/, '');
}

/** True when the file name/path looks like a renderable image by extension. */
export function isImageAttachment(nameOrPath?: string | null): boolean {
  if (!nameOrPath) return false;
  const clean = stripUploadTimestamp(
    nameOrPath.split('?')[0].split('#')[0]
  );
  const ext = clean.split('.').pop()?.toLowerCase() ?? '';
  return IMAGE_EXTENSIONS.has(ext);
}

/**
 * Best-effort display name for an `upload://<stored_name>` ref (or bare path),
 * dropping the scheme and the trailing upload timestamp.
 */
export function deriveAttachFileName(ref?: string | null): string {
  if (!ref) return 'file';
  const base = ref.replace(/^upload:\/\//, '').split('/').pop() ?? ref;
  return stripUploadTimestamp(base) || base;
}

function brainBase(): string {
  // The upload-content endpoint lives on the Brain, so use brainEndpoint (the
  // same base getBaseURL() resolves for every other Brain call). Using the
  // proxy endpoint — or nothing — makes the <img> URL relative, so it hits the
  // Theia host instead of the Brain and the image 404s (only alt text shows).
  const cfg = getConnectionConfig();
  const base = cfg.brainEndpoint || cfg.proxyEndpoint || '';
  return base.replace(/\/+$/, '');
}

/**
 * Build a URL that serves an uploaded attachment's bytes, or null when the ref
 * can't be served this way (not an upload:// ref, or no session id yet).
 * `sessionIdOverride` lets a reloaded conversation pass the session id the file
 * was uploaded under (uploads live under WORKSPACE_ROOT/<session_id>/uploads).
 */
export function resolveUploadContentUrl(
  filePath?: string | null,
  sessionIdOverride?: string | null
): string | null {
  if (!filePath || !filePath.startsWith('upload://')) return null;
  const sessionId = sessionIdOverride || getConnectionConfig().sessionId;
  if (!sessionId) return null;
  const base = brainBase();
  // The Brain serves files at /files/* with NO /api/v1 prefix (same as the
  // working buildRemoteFileInfoPath -> `${brainEndpoint}/files/stream`). The
  // <img> hits the Brain directly, not the /api/v1 proxy.
  return (
    `${base}/files/upload-content` +
    `?file_id=${encodeURIComponent(filePath)}` +
    `&session_id=${encodeURIComponent(sessionId)}`
  );
}

/**
 * Convenience: URL for an image attachment worth rendering as a thumbnail, or
 * null. Only returns a URL for image-typed upload refs.
 */
export function resolveAttachmentImageUrl(
  attach: { filePath?: string; fileName?: string } | null | undefined,
  sessionIdOverride?: string | null
): string | null {
  if (!attach) return null;
  if (!isImageAttachment(attach.fileName || attach.filePath)) return null;
  return resolveUploadContentUrl(attach.filePath, sessionIdOverride);
}
