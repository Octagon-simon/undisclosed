// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { ContainerModule } from '@theia/core/shared/inversify';
import { BackendApplicationContribution } from '@theia/core/lib/node';
import { EarlyExpressMiddleware } from '@theia/core/lib/node/backend-application';
import express from '@theia/core/shared/express';
import { spawn } from 'child_process';
import * as fs from 'fs';
import * as http from 'http';
import * as os from 'os';
import * as path from 'path';
import { BrainLauncher } from './brain-launcher';

/**
 * JSON body ceiling for the agent's own endpoints (`/api`, `/undisclosed-agent`).
 *
 * This is not just belt-and-braces: `@theia/filesystem`'s FileDownloadEndpoint
 * installs an UNSCOPED `app.use(json())` (body-parser's default limit is 100kb)
 * during the backend's configure phase, which runs AFTER early middleware. So an
 * agent request body over 100kb (a large chat message, a big tool result) was
 * rejected with `413 Payload Too Large` before the route-level parser below ever
 * ran. The early middleware registered in `initialize()` parses these paths
 * first with this limit; body-parser then skips its own pass (`req._body` set).
 */
const JSON_BODY_LIMIT = '50mb';

/**
 * Resolve `scripts/brain.sh` from the repo (dev + standalone-brain setups).
 * Returns undefined if not found (e.g. a packaged app without the scripts dir).
 */
function findBrainScript(): string | undefined {
  const resourcesPath = (
    process as NodeJS.Process & { resourcesPath?: string }
  ).resourcesPath;
  const candidates = [
    path.resolve(process.cwd(), 'scripts', 'brain.sh'),
    path.resolve(process.cwd(), '..', 'scripts', 'brain.sh'),
    path.join(__dirname, '..', '..', '..', '..', 'scripts', 'brain.sh'),
    resourcesPath
      ? path.join(resourcesPath, 'scripts', 'brain.sh')
      : '',
  ].filter(Boolean);
  return candidates.find((p) => {
    try {
      return fs.existsSync(p);
    } catch {
      return false;
    }
  });
}

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
 * `/api` proxy target. In STANDALONE Undisclosed (dev + the packaged desktop
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

// The brain is a single-process, single-event-loop FastAPI app. During a heavy
// agent turn it can briefly refuse/reset a connection (while the loop is busy,
// or while the supervisor restarts a wedged one). A ONE-SHOT 502 in that window
// is what makes the editor look "flaky": the user's /api/v1/user/* calls fail,
// and they restart the brain by hand. So retry idempotent GETs on connect-type
// errors to ride out a sub-few-second hiccup.
//
// We deliberately do NOT set proxyTimeout: the chat stream is a long-lived SSE
// response served through this same proxy, and a global timeout would cut it
// off mid-turn.
const MAX_PROXY_RETRIES = Number(process.env.UNDISCLOSED_PROXY_RETRIES ?? 4);
const PROXY_RETRY_DELAY_MS = Number(
  process.env.UNDISCLOSED_PROXY_RETRY_DELAY_MS ?? 350
);
const TRANSIENT_PROXY_ERRORS = new Set([
  'ECONNREFUSED',
  'ECONNRESET',
  'EPIPE',
  'ETIMEDOUT',
  'EHOSTUNREACH',
  'ECONNABORTED',
  'ENOTFOUND',
]);

// A socket that went idle across a macOS sleep is dead, but NO FIN arrives for a
// suspended/lost peer, so nothing tells us. Node's default agent keeps sockets
// alive, so the FIRST proxied request after wake reuses that dead socket, the
// connect fails, and the editor shows the 502 the user sees (on the editor's own
// port, e.g. localhost:60268/api/v1/user/key). The brain lives on loopback,
// where a fresh connect is ~free, so this proxy keeps no idle sockets and always
// dials a live connection. Set UNDISCLOSED_PROXY_KEEPALIVE=1 only if
// UNDISCLOSED_PROXY_TARGET points at a genuinely remote host.
const PROXY_KEEPALIVE =
  (process.env.UNDISCLOSED_PROXY_KEEPALIVE ?? '0').trim() === '1';
const BRAIN_PROXY_AGENT = new http.Agent({
  keepAlive: PROXY_KEEPALIVE,
  maxSockets: 64,
});

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
  // NOTE: The VS Code git built-ins (vscode.git / vscode.git-base) are a
  // first-class part of the app now: Theia 1.76 removed `@theia/git`, so
  // `vscode.git` IS the Source Control provider. They are pinned in
  // `theiaPlugins` and must NOT be pruned. (The old frontend menu suppressor,
  // B4, was retired — it would blank Source Control.)

  // Spawn the frozen Python brain in a packaged desktop app (no-op in dev).
  bind(BrainLauncher).toSelf().inSingletonScope();
  bind(BackendApplicationContribution).toService(BrainLauncher);

  bind(BackendApplicationContribution)
    .toDynamicValue((ctx) => ({
      // EARLY middleware: parse the agent endpoints' JSON bodies with a large
      // limit BEFORE @theia/filesystem's FileDownloadEndpoint.configure() adds an
      // unscoped `express.json()` (100kb default) that would otherwise reject
      // them with 413. Handlers pushed here are applied at the very start of
      // `BackendApplication.configure()`, ahead of every contribution's
      // `configure()`. body-parser no-ops on later passes once `req._body` is
      // set, so FileDownloadEndpoint's unscoped parser is neutralised for these
      // paths. Non-target paths fall through untouched.
      initialize(): void {
        const early = ctx.container.get(EarlyExpressMiddleware);
        const largeJson = express.json({ limit: JSON_BODY_LIMIT });
        early.handlers.push((req, res, next) => {
          const url = req.url ?? '';
          if (url.startsWith('/api') || url.startsWith('/undisclosed-agent')) {
            largeJson(req, res, next);
          } else {
            next();
          }
        });
      },
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
          const err = args[0] as NodeJS.ErrnoException;
          const req = args[1] as
            | (http.IncomingMessage & { __proxyRetries?: number })
            | undefined;
          const res = args[2] as http.ServerResponse | undefined;
          const code = err?.code;
          const used = req?.__proxyRetries ?? 0;
          const canRetry =
            !!req &&
            req.method === 'GET' &&
            !!res &&
            !res.headersSent &&
            !!code &&
            TRANSIENT_PROXY_ERRORS.has(code) &&
            used < MAX_PROXY_RETRIES;
          if (canRetry) {
            req.__proxyRetries = used + 1;
            // eslint-disable-next-line no-console
            console.warn(
              `[undisclosed-agent] /api proxy ${code} — retry ` +
                `${req.__proxyRetries}/${MAX_PROXY_RETRIES} ${req.url}`
            );
            setTimeout(() => {
              if (!res!.headersSent) {
                proxy.web(req!, res!, {
                  target: PROXY_TARGET,
                  agent: BRAIN_PROXY_AGENT,
                });
              }
            }, PROXY_RETRY_DELAY_MS);
            return;
          }
          if (res && !res.headersSent) {
            res.statusCode = 502;
            res.end(`agent proxy error: ${err.message}`);
          }
        });

        app.use(
          '/api',
          express.json({ limit: JSON_BODY_LIMIT }),
          (req: express.Request, res: express.Response) => {
            // express strips the '/api' mount prefix from req.url; restore it.
            (req as unknown as http.IncomingMessage).url = `/api${req.url}`;
            proxy.web(
              req as unknown as http.IncomingMessage,
              res as unknown as http.ServerResponse,
              { target: PROXY_TARGET, agent: BRAIN_PROXY_AGENT }
            );
          }
        );

        // Run a whitelisted `git` subcommand in a working dir and return its
        // output. Used by the frontend git-extras (Undo Last Commit,
        // unstage/discard all, AI commit message) now that Theia 1.76 removed
        // the `@theia/git` service and Source Control is served by the built-in
        // `vscode.git` extension. The subcommand whitelist keeps this endpoint
        // from becoming a generic process runner.
        const GIT_SUBCOMMANDS = new Set([
          'diff',
          'reset',
          'checkout',
          'status',
          'rev-parse',
          'log',
        ]);
        app.post(
          '/undisclosed-agent/git/exec',
          express.json({ limit: '5mb' }),
          (req: express.Request, res: express.Response) => {
            const body = (req.body ?? {}) as { cwd?: unknown; args?: unknown };
            const rawArgs = Array.isArray(body.args) ? body.args : undefined;
            const args = rawArgs?.filter(
              (a): a is string => typeof a === 'string'
            );
            const cwd = typeof body.cwd === 'string' ? body.cwd : undefined;
            if (
              !cwd ||
              !args ||
              args.length === 0 ||
              args.length !== rawArgs?.length
            ) {
              res
                .status(400)
                .json({ error: 'expected { cwd: string, args: string[] }' });
              return;
            }
            if (!GIT_SUBCOMMANDS.has(args[0])) {
              res
                .status(400)
                .json({ error: `git subcommand not allowed: ${args[0]}` });
              return;
            }
            let child: ReturnType<typeof spawn>;
            try {
              child = spawn('git', args, { cwd });
            } catch (err) {
              res.status(500).json({ error: (err as Error).message });
              return;
            }
            let stdout = '';
            let stderr = '';
            child.stdout?.on('data', (d) => (stdout += d.toString()));
            child.stderr?.on('data', (d) => (stderr += d.toString()));
            child.on('error', (err) => {
              if (!res.headersSent) {
                res.status(500).json({ error: err.message });
              }
            });
            child.on('close', (code) => {
              if (!res.headersSent) {
                res.json({ stdout, stderr, exitCode: code });
              }
            });
          }
        );

        // Resurrect the brain from the agent panel (the renderer can't spawn a
        // process; the backend can). Runs `scripts/brain.sh restart` for the
        // dev / standalone-brain setup. This is what removes the quit-app →
        // restart-brain → relaunch-app dance.
        app.post(
          '/undisclosed-agent/brain/restart',
          async (_req: express.Request, res: express.Response) => {
            // 1) PACKAGED app: drive BrainLauncher, which can spawn the frozen
            //    brain (and take over the port after the user stops an external
            //    one). This is the case scripts/brain.sh can't cover.
            const launcher = BrainLauncher.current;
            // Only drive BrainLauncher when it can actually spawn a brain (a
            // packaged app with a frozen binary). In a DEV build it can't, so
            // fall through to scripts/brain.sh instead of returning its failure.
            if (
              launcher &&
              typeof launcher.canManage === 'function' &&
              launcher.canManage()
            ) {
              try {
                const r = await launcher.restart();
                res.status(r.ok ? 202 : 503).json(r);
                return;
              } catch (err) {
                // fall through to the script path
                // eslint-disable-next-line no-console
                console.error(
                  `[undisclosed-agent] BrainLauncher.restart failed: ${(err as Error).message}`
                );
              }
            }
            // 2) SELF-HOSTED (packaged app): the user runs their OWN brain from
            //    their OWN checkout, at a path we can't guess — and scripts/ is
            //    NOT bundled into the app (electron-builder ships only the frozen
            //    binary), so findBrainScript() finds nothing and a bundled
            //    brain.sh would point at <resources>/brain with no venv. Let the
            //    self-hoster tell us how to restart THEIR brain via
            //    UNDISCLOSED_BRAIN_RESTART_CMD (e.g.
            //    "/path/to/eigent-theia/scripts/brain.sh restart"), run in a login
            //    shell so their PATH / venv resolve. This is what makes the panel
            //    Restart button work without dropping to a terminal.
            const customCmd = (
              process.env.UNDISCLOSED_BRAIN_RESTART_CMD || ''
            ).trim();
            if (customCmd) {
              try {
                const child = spawn('bash', ['-lc', customCmd], {
                  cwd:
                    process.env.UNDISCLOSED_BRAIN_RESTART_CWD || os.homedir(),
                  detached: true,
                  stdio: 'ignore',
                });
                child.on('error', (err) =>
                  // eslint-disable-next-line no-console
                  console.error(
                    `[undisclosed-agent] brain restart cmd failed: ${err.message}`
                  )
                );
                child.unref();
                res
                  .status(202)
                  .json({ ok: true, detail: 'Running UNDISCLOSED_BRAIN_RESTART_CMD.' });
                return;
              } catch (err) {
                res
                  .status(500)
                  .json({ ok: false, detail: (err as Error).message });
                return;
              }
            }

            // 3) DEV / standalone-brain: run scripts/brain.sh restart.
            const script = findBrainScript();
            if (!script) {
              res.status(501).json({
                ok: false,
                detail:
                  'No frozen brain and scripts/brain.sh not found. If you '
                  + 'self-host the brain, set UNDISCLOSED_BRAIN_RESTART_CMD (e.g. '
                  + '"/path/to/scripts/brain.sh restart") in ~/.undisclosed/.env; '
                  + 'otherwise restart it manually (./scripts/brain.sh restart).',
              });
              return;
            }
            try {
              const child = spawn('bash', [script, 'restart'], {
                cwd: path.dirname(path.dirname(script)),
                detached: true,
                stdio: 'ignore',
              });
              child.on('error', (err) =>
                // eslint-disable-next-line no-console
                console.error(`[undisclosed-agent] brain restart failed: ${err.message}`)
              );
              child.unref();
              res.status(202).json({ ok: true, detail: 'Running brain.sh restart.' });
            } catch (err) {
              res
                .status(500)
                .json({ ok: false, detail: (err as Error).message });
            }
          }
        );

        app.use('/undisclosed-agent', express.static(dir));
      },
    }))
    .inSingletonScope();
});
