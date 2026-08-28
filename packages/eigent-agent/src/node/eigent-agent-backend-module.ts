// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { ContainerModule } from '@theia/core/shared/inversify';
import { BackendApplicationContribution } from '@theia/core/lib/node';
import express from '@theia/core/shared/express';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Serve the prebuilt Eigent agent bundle (agent-embed.umd.js + style.css, in
 * ../assets/agent-embed) at `/eigent-agent/*` so the frontend widget can load
 * it via <script>/<link>. The bundle is self-contained (React + CSS inlined);
 * this route just makes it reachable.
 *
 * Theia webpacks the backend into a single bundle, so `__dirname` no longer
 * points at this package — resolve the assets dir from several candidates
 * (cwd-relative first, which holds when running `theia start` from the app root).
 */
function resolveAssetsDir(): string {
  const rel = path.join('packages', 'eigent-agent', 'assets', 'agent-embed');
  const candidates = [
    path.resolve(process.cwd(), rel),
    path.join(__dirname, '..', '..', 'assets', 'agent-embed'),
    path.join(__dirname, 'assets', 'agent-embed'),
  ];
  return candidates.find((p) => fs.existsSync(p)) ?? candidates[0];
}

export default new ContainerModule((bind) => {
  bind(BackendApplicationContribution)
    .toDynamicValue(() => ({
      configure(app: express.Application): void {
        const dir = resolveAssetsDir();
        // eslint-disable-next-line no-console
        console.log(`[eigent-agent] serving bundle from ${dir} at /eigent-agent`);
        app.use('/eigent-agent', express.static(dir));
      },
    }))
    .inSingletonScope();
});
