// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { ContainerModule } from '@theia/core/shared/inversify';
import { BackendApplicationContribution } from '@theia/core/lib/node';
import express from '@theia/core/shared/express';
import * as fs from 'fs';
import * as http from 'http';
import * as path from 'path';
import { BrainLauncher } from './brain-launcher';

// http-proxy ships as a transitive dep (no @types); minimal typing.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const httpProxy = require('http-proxy') as {
  createProxyServer(opts?: Record<string, unknown>): {
    web(
      req: http.IncomingMessage,
      res: http.ServerResponse,
      opts: Record<string, unknown>,
      cb?: (err: Error) => void
    ): void;
    on(event: string, cb: (...args: unknown[]) => void): void;
  };
};

/**
 * `/api` proxy target. In STANDALONE eigent-theia (dev + the packaged desktop
 * app) the brain itself serves the `/api/v1/*` surface (providers, spaces,
 * history, chat-platform), so `/api` must go to the BRAIN — not the legacy
 * `:3001` cloud proxy, which doesn't exist here (hitting it gives "agent proxy
 * error" when e.g. adding a model). Default to the brain's port; override with
 * UNDISCLOSED_PROXY_TARGET for a real cloud proxy. (scripts/dev.sh already sets
 * this to :5001; the packaged app relies on this default.)
 */
const BRAIN_PORT = process.env.UNDISCLOSED_BRAIN_PORT || '5001';
const PROXY_TARGET =
  process.env.UNDISCLOSED_PROXY_TARGET || `http://localhost:${BRAIN_PORT}`;

function resolveAssetsDir(): string {
  const rel = path.join('packages', 'undisclosed-agent', 'assets', 'agent-embed');
  const nm = path.join(
    'node_modules',
    'undisclosed-agent',
    'assets',
    'agent-embed'
  );
  const resourcesPath = (
    process as NodeJS.Process & { resourcesPath?: string }
  ).resourcesPath;
  const candidates = [
    // dev (repo checkout)
    path.resolve(process.cwd(), rel),
    // packaged Electron app: the extension is webpacked into lib/backend, so
    // __dirname is <app>/Resources/app/lib/backend — assets live under the
    // sibling node_modules, and under <resourcesPath>/app/node_modules.
    path.join(__dirname, '..', '..', nm),
    resourcesPath
      ? path.join(resourcesPath, 'app', nm)
      : path.join(__dirname, '..', '..', '..', nm),
    // older layouts
    path.join(__dirname, '..', '..', 'assets', 'agent-embed'),
    path.join(__dirname, 'assets', 'agent-embed'),
  ];
  return candidates.find((p) => fs.existsSync(p)) ?? candidates[0];
}

/**
 * Backend contributions for the Undisclosed agent widget:
 *  1. Serve the prebuilt agent bundle at `/undisclosed-agent/*`.
 *  2. Same-origin-proxy `/api/*` -> the Undisclosed cloud-proxy (`:3001`), so the
 *     browser makes no cross-origin (CORS) calls.
 *
 * The body is JSON-parsed then RE-STREAMED onto the proxied request: without
 * this, a POST whose body stream was already consumed hangs forever waiting on
 * an upstream body (GETs are unaffected).
 */
export default new ContainerModule((bind) => {
  // Spawn the frozen Python brain in a packaged desktop app (no-op in dev).
  bind(BrainLauncher).toSelf().inSingletonScope();
  bind(BackendApplicationContribution).toService(BrainLauncher);

  bind(BackendApplicationContribution)
    .toDynamicValue(() => ({
      configure(app: express.Application): void {
        const dir = resolveAssetsDir();
        // eslint-disable-next-line no-console
        console.log(
          `[undisclosed-agent] bundle: ${dir} -> /undisclosed-agent ; proxy: /api -> ${PROXY_TARGET}`
        );

        const proxy = httpProxy.createProxyServer({ changeOrigin: true });

        // Re-stream a parsed JSON body so POST/PUT don't hang.
        proxy.on('proxyReq', (...args: unknown[]) => {
          const proxyReq = args[0] as http.ClientRequest;
          const req = args[1] as http.IncomingMessage & { body?: unknown };
          const body = req.body;
          if (
            body &&
            typeof body === 'object' &&
            Object.keys(body as object).length > 0
          ) {
            const data = JSON.stringify(body);
            proxyReq.setHeader('Content-Type', 'application/json');
            proxyReq.setHeader('Content-Length', Buffer.byteLength(data));
            proxyReq.write(data);
          }
        });
        proxy.on('error', (...args: unknown[]) => {
          const err = args[0] as Error;
          const res = args[2] as http.ServerResponse | undefined;
          if (res && !res.headersSent) {
            res.statusCode = 502;
            res.end(`agent proxy error: ${err.message}`);
          }
        });

        app.use(
          '/api',
          express.json({ limit: '50mb' }),
          (req: express.Request, res: express.Response) => {
            // express strips the '/api' mount prefix from req.url; restore it.
            (req as unknown as http.IncomingMessage).url = `/api${req.url}`;
            proxy.web(
              req as unknown as http.IncomingMessage,
              res as unknown as http.ServerResponse,
              { target: PROXY_TARGET }
            );
          }
        );

        app.use('/undisclosed-agent', express.static(dir));
      },
    }))
    .inSingletonScope();
});
