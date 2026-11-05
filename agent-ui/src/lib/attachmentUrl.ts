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
 * Uploaded attaches are stored as `upload://<session>/<stored_name>` refs (see
 * uploadFileToBrain); the Brain serves their bytes from
 * `/files/upload-content?file_id=...&session_id=...`. An `<img src>` bypasses
 * the proxy header wrapper, so the session id is passed as a query param
 * instead of the X-Session-ID header.
 *
 * The session MUST be the one the file was uploaded under, not whatever the
 * connection currently uses: the connection session changes on reload/new
 * chat, while uploads stay under the original session's directory. Older refs
 * have no session segment, hence the override / connection fallbacks.
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
 * Split an upload ref into its upload session (empty for legacy refs) and the
 * stored name, or null when the value is not an upload ref.
 */
export function parseUploadRef(
  ref?: string | null
): { sessionId: string; storedName: string } | null {
  if (!ref || !ref.startsWith('upload://')) return null;
  const payload = ref.slice('upload://'.length);
  const slash = payload.indexOf('/');
  if (slash > 0) {
    return {
      sessionId: payload.slice(0, slash),
      storedName: payload.slice(slash + 1),
    };
  }
  return { sessionId: '', storedName: payload };
}

/**
 * Build a URL that serves an uploaded attachment's bytes, or null when the ref
 * is not an `upload://` one. The session embedded in the ref wins;
 * `sessionIdOverride` covers legacy refs from a reloaded conversation, then the
 * live connection session is the last resort.
 */
export function resolveUploadContentUrl(
  filePath?: string | null,
  sessionIdOverride?: string | null
): string | null {
  const parsed = parseUploadRef(filePath);
  if (!parsed || !parsed.storedName || !filePath) return null;
  const sessionId =
    parsed.sessionId ||
    sessionIdOverride ||
    getConnectionConfig().sessionId;
  const base = brainBase();
  // The Brain serves files at /files/* with NO /api/v1 prefix (same as the
  // working buildRemoteFileInfoPath -> `${brainEndpoint}/files/stream`). The
  // <img> hits the Brain directly, not the /api/v1 proxy. The session is only
  // a hint: the endpoint falls back to the unique stored name, so a legacy ref
  // with no session still resolves instead of being dropped here.
  const sessionParam = sessionId
    ? `&session_id=${encodeURIComponent(sessionId)}`
    : '';
  return (
    `${base}/files/upload-content` +
    `?file_id=${encodeURIComponent(filePath)}` +
    sessionParam
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
