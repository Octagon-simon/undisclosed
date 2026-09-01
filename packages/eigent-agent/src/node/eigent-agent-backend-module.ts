// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { ContainerModule } from '@theia/core/shared/inversify';
import { BackendApplicationContribution } from '@theia/core/lib/node';
import express from '@theia/core/shared/express';
import * as fs from 'fs';
import * as http from 'http';
import * as path from 'path';

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

/** Cloud proxy target (the local Eigent proxy service). Overridable. */
const PROXY_TARGET = process.env.EIGENT_PROXY_TARGET || 'http://localhost:3001';

function resolveAssetsDir(): string {
  const rel = path.join('packages', 'eigent-agent', 'assets', 'agent-embed');
  const candidates = [
    path.resolve(process.cwd(), rel),
    path.join(__dirname, '..', '..', 'assets', 'agent-embed'),
    path.join(__dirname, 'assets', 'agent-embed'),
  ];
  return candidates.find((p) => fs.existsSync(p)) ?? candidates[0];
}

/**
 * Backend contributions for the Eigent agent widget:
 *  1. Serve the prebuilt agent bundle at `/eigent-agent/*`.
 *  2. Same-origin-proxy `/api/*` -> the Eigent cloud-proxy (`:3001`), so the
 *     browser makes no cross-origin (CORS) calls.
 *
 * The body is JSON-parsed then RE-STREAMED onto the proxied request: without
 * this, a POST whose body stream was already consumed hangs forever waiting on
 * an upstream body (GETs are unaffected).
 */
export default new ContainerModule((bind) => {
  bind(BackendApplicationContribution)
    .toDynamicValue(() => ({
      configure(app: express.Application): void {
        const dir = resolveAssetsDir();
        // eslint-disable-next-line no-console
        console.log(
          `[eigent-agent] bundle: ${dir} -> /eigent-agent ; proxy: /api -> ${PROXY_TARGET}`
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

        app.use('/eigent-agent', express.static(dir));
      },
    }))
    .inSingletonScope();
});
