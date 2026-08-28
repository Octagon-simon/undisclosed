// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

/**
 * Node-only shim for the probe harness. `@microsoft/fetch-event-source` is a
 * browser library and references `window`/`document`. The REAL target — the
 * Theia agent widget — is a browser and needs none of this; import it only from
 * the node probe (before any SSE import) so `node lib/probe.js` can run.
 */
const g = globalThis as unknown as {
  window?: unknown;
  document?: unknown;
};
if (typeof g.window === 'undefined') {
  g.window = globalThis;
}
if (typeof g.document === 'undefined') {
  g.document = {
    hidden: false,
    visibilityState: 'visible',
    addEventListener() {
      /* no-op */
    },
    removeEventListener() {
      /* no-op */
    },
  };
}
