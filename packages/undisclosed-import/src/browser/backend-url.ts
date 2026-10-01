// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { Endpoint } from '@theia/core/lib/browser/endpoint';

/**
 * Build an ABSOLUTE URL to a Theia backend HTTP route.
 *
 * A bare relative path (`fetch('/undisclosed-import/vscode')`) works in the dev
 * browser but breaks in the packaged Electron app: the renderer loads from a
 * `file://` page, so the relative path resolves to `file:///undisclosed-import/…`
 * → `ERR_FILE_NOT_FOUND`. Theia's `Endpoint` resolves the real backend origin
 * (host:port) in every mode, so always route backend `fetch`es through here.
 *
 * (The agent widget's `serverUrl()` is the same one-liner; kept per-package to
 * avoid a cross-extension dependency for a single call — promote to a shared
 * package if a third consumer appears.)
 */
export function backendUrl(path: string): string {
  return new Endpoint({ path }).getRestUrl().toString();
}
