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
 * Compact, panel-native MCP connectors manager for the embedded agent. Lists the
 * user's installed MCP servers and lets them add a custom one (local command or
 * remote URL) by pasting a standard `mcpServers` JSON config. Deliberately does
 * NOT reuse the full desktop Connectors page (whose hero title / wide layout /
 * viewport modal don't fit the narrow panel and bloated the bundle).
 */

import {
  mcpAuthStatus,
  mcpAuthenticate,
  mcpInstall,
  mcpList,
  mcpRemove,
} from '@/api/brain';
import { proxyFetchGet, proxyFetchPost } from '@/api/http';
import {
  Check,
  ChevronDown,
  ChevronRight,
  KeyRound,
  Loader2,
  Plug,
  Plus,
  Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

interface McpRow {
  /** Server name (the key in mcpServers) — also the remove/id key. */
  name: string;
  /** True for a remote (url) server, false for a local command server. */
  remote: boolean;
  /** True for an OAuth (mcp-remote command) server — needs a browser sign-in. */
  oauth: boolean;
}

interface BuiltInIntegration {
  /** Display name / key from /config/info (e.g. "Figma"). */
  key: string;
  /** Env vars this integration needs (e.g. ["FIGMA_ACCESS_TOKEN"]). */
  envVars: string[];
}

// Fixed callback port for OAuth (mcp-remote) sign-in, so the redirect URI the
// user registers with their provider is stable and predictable.
const OAUTH_CALLBACK_PORT = '33418';
// mcp-remote registers its callback as http://localhost:<port>/oauth/callback
// (localhost, NOT 127.0.0.1) — the redirect URI must match exactly.
const OAUTH_REDIRECT_URI = `http://localhost:${OAUTH_CALLBACK_PORT}/oauth/callback`;

// Shows both supported shapes: a local command server and a remote URL server.
const EXAMPLE_CONFIG = `{
  "mcpServers": {
    "local-server": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-everything"]
    },
    "remote-server": {
      "type": "streamable_http",
      "url": "https://your-server.example.com/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}`;

export default function AgentConnectors() {
  const [rows, setRows] = useState<McpRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [mode, setMode] = useState<'guided' | 'json'>('guided');
  const [config, setConfig] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [authId, setAuthId] = useState<string | null>(null);
  // Connectors authenticated this session — the button reflects the done state.
  const [authed, setAuthed] = useState<Set<string>>(new Set());

  // Guided "add remote MCP" form: URL + transport, we generate the config.
  const [gName, setGName] = useState('');
  const [gUrl, setGUrl] = useState('');
  const [gTransport, setGTransport] = useState<
    'streamable_http' | 'sse' | 'oauth'
  >('streamable_http');
  const [gToken, setGToken] = useState('');
  // OAuth apps that don't allow dynamic client registration (e.g. Asana) need a
  // pre-registered client. Optional — leave blank for servers that self-register.
  const [gClientId, setGClientId] = useState('');
  const [gClientSecret, setGClientSecret] = useState('');

  // Built-in integrations that take env-var tokens (Figma, GitHub, Search, …),
  // driven by the Brain's /config/info map. Users set their own keys here;
  // they're written to ~/.undisclosed/.env, which the agent reads live.
  const [integrations, setIntegrations] = useState<BuiltInIntegration[]>([]);
  // key -> is a value currently set (booleans only; secrets never leave Brain).
  const [envStatus, setEnvStatus] = useState<Record<string, boolean>>({});
  const [openIntegration, setOpenIntegration] = useState<string | null>(null);
  // Unsaved field edits, keyed by env var name.
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const loadIntegrations = useCallback(async () => {
    try {
      const [info, status] = await Promise.all([
        proxyFetchGet('/api/v1/config/info'),
        proxyFetchGet('/api/v1/config/env'),
      ]);
      const list: BuiltInIntegration[] = Object.entries(
        (info || {}) as Record<string, { env_vars?: unknown }>
      )
        .map(([key, v]) => ({
          key,
          envVars: Array.isArray(v?.env_vars)
            ? (v.env_vars as string[])
            : [],
        }))
        .filter((i) => i.envVars.length > 0)
        .sort((a, b) => a.key.localeCompare(b.key));
      setIntegrations(list);
      setEnvStatus((status || {}) as Record<string, boolean>);
    } catch {
      /* non-fatal — the MCP list still works without the token catalog */
    }
  }, []);

  const saveIntegration = useCallback(
    async (intg: BuiltInIntegration) => {
      // Only send fields the user actually typed — a blank field means "leave
      // as-is", never "clear" (clearing is an explicit action below).
      const values: Record<string, string> = {};
      for (const k of intg.envVars) {
        const v = (draft[k] ?? '').trim();
        if (v) values[k] = v;
      }
      if (Object.keys(values).length === 0) {
        toast.error('Enter a value first.');
        return;
      }
      setSavingKey(intg.key);
      try {
        await proxyFetchPost('/api/v1/config/env', { values });
        toast.success(`${intg.key} saved. The agent can use it now.`);
        setDraft((d) => {
          const next = { ...d };
          for (const k of intg.envVars) delete next[k];
          return next;
        });
        setOpenIntegration(null);
        await loadIntegrations();
      } catch (e) {
        toast.error((e as Error)?.message || 'Failed to save key.');
      } finally {
        setSavingKey(null);
      }
    },
    [draft, loadIntegrations]
  );

  const clearKey = useCallback(
    async (intg: BuiltInIntegration, key: string) => {
      setSavingKey(intg.key);
      try {
        await proxyFetchPost('/api/v1/config/env', { values: { [key]: '' } });
        toast.success(`${key} removed.`);
        await loadIntegrations();
      } catch (e) {
        toast.error((e as Error)?.message || 'Failed to remove key.');
      } finally {
        setSavingKey(null);
      }
    },
    [loadIntegrations]
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Source of truth is the Brain's mcp.json (/mcp/list) — the same config
      // the agent reads — so the list always matches what's actually installed.
      const res = await mcpList();
      const servers = (res?.mcpServers ?? {}) as Record<
        string,
        Record<string, unknown>
      >;
      const list: McpRow[] = Object.entries(servers).map(([name, cfg]) => {
        const args = Array.isArray((cfg as { args?: unknown })?.args)
          ? ((cfg as { args?: unknown[] }).args as unknown[])
          : [];
        return {
          name,
          remote: typeof cfg?.url === 'string' && cfg.url.length > 0,
          // OAuth servers are mcp-remote command bridges (npx … mcp-remote …).
          oauth:
            !!(cfg as { command?: unknown })?.command &&
            args.some((a) => String(a).includes('mcp-remote')),
        };
      });
      setRows(list);
      // Restore which connectors are already authenticated (persisted), so the
      // button shows "Authenticated" across reloads.
      try {
        const status = await mcpAuthStatus();
        setAuthed(new Set(status.authenticated));
      } catch {
        /* non-fatal */
      }
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadIntegrations();
  }, [load, loadIntegrations]);

  const resetForms = useCallback(() => {
    setShowForm(false);
    setConfig('');
    setGName('');
    setGUrl('');
    setGToken('');
    setGClientId('');
    setGClientSecret('');
    setGTransport('streamable_http');
  }, []);

  const installGuided = useCallback(async () => {
    const name = gName.trim();
    const url = gUrl.trim();
    if (!name) {
      toast.error('Give the connector a name.');
      return;
    }
    if (!url) {
      toast.error('Enter the server URL.');
      return;
    }
    // OAuth remote servers go through the `mcp-remote` bridge, which runs the
    // browser OAuth flow and caches the token in ~/.mcp-auth (so it persists).
    // Plain Streamable HTTP / SSE connect directly, with an optional bearer
    // token sent as an Authorization header.
    let mcp: Record<string, unknown>;
    if (gTransport === 'oauth') {
      // Pin the callback port so the registered redirect URI is stable, and pass
      // a pre-registered client (client_id/secret) when given — required for
      // providers like Asana that don't support dynamic client registration.
      const args = ['-y', 'mcp-remote', url, OAUTH_CALLBACK_PORT];
      if (gClientId.trim() && gClientSecret.trim()) {
        args.push(
          '--static-oauth-client-info',
          JSON.stringify({
            client_id: gClientId.trim(),
            client_secret: gClientSecret.trim(),
          })
        );
      }
      mcp = { command: 'npx', args };
    } else {
      mcp = { type: gTransport, url };
      if (gToken.trim()) {
        mcp.headers = { Authorization: `Bearer ${gToken.trim()}` };
      }
    }
    setAdding(true);
    try {
      await mcpInstall(name, mcp);
      toast.success(
        gTransport === 'oauth'
          ? 'Connector added — a browser will open to authorize on first use.'
          : 'Connector added.'
      );
      resetForms();
      await load();
    } catch (e) {
      toast.error((e as Error)?.message || 'Failed to add connector.');
    } finally {
      setAdding(false);
    }
  }, [
    gName,
    gUrl,
    gTransport,
    gToken,
    gClientId,
    gClientSecret,
    load,
    resetForms,
  ]);

  const install = useCallback(async () => {
    const text = config.trim();
    if (!text) return;
    let parsed: { mcpServers?: Record<string, Record<string, unknown>> };
    try {
      parsed = JSON.parse(text);
    } catch {
      // Be forgiving of trailing commas (common in hand-pasted / JSON5-style
      // configs) — strip any comma before a closing } or ] and retry.
      try {
        parsed = JSON.parse(text.replace(/,(\s*[}\]])/g, '$1'));
      } catch {
        toast.error('That is not valid JSON.');
        return;
      }
    }
    if (!parsed.mcpServers || typeof parsed.mcpServers !== 'object') {
      toast.error('Config must contain an "mcpServers" object.');
      return;
    }
    setAdding(true);
    try {
      // Cloud sync — best-effort. This route lives on the cloud proxy (the
      // local Brain has no /mcp/import/local), and it can reject shapes the
      // Brain accepts (e.g. remote url servers). The authoritative step is
      // mcpInstall below, which writes ~/.eigent/mcp.json — the file the agent
      // actually reads. So never let this block the install.
      try {
        await proxyFetchPost('/api/v1/mcp/import/local', parsed);
      } catch {
        /* ignore cloud sync failure */
      }
      for (const [name, mcp] of Object.entries(parsed.mcpServers)) {
        await mcpInstall(name, mcp as Record<string, unknown>);
      }
      toast.success('Connector added.');
      setConfig('');
      setShowForm(false);
      await load();
    } catch (e) {
      toast.error((e as Error)?.message || 'Failed to add connector.');
    } finally {
      setAdding(false);
    }
  }, [config, load]);

  const authenticate = useCallback(async (row: McpRow) => {
    setAuthId(row.name);
    const t = toast.loading(
      `Opening your browser to sign in to ${row.name}… complete the sign-in there.`
    );
    try {
      const res = await mcpAuthenticate(row.name);
      toast.dismiss(t);
      if (res?.success) {
        setAuthed((s) => new Set(s).add(row.name));
        toast.success(`${row.name} authenticated. The agent can use it now.`);
      } else {
        toast.error(res?.message || 'Sign-in did not complete.');
      }
    } catch (e) {
      toast.dismiss(t);
      toast.error((e as Error)?.message || 'Failed to start sign-in.');
    } finally {
      setAuthId(null);
    }
  }, []);

  const remove = useCallback(
    async (row: McpRow) => {
      setBusyId(row.name);
      try {
        await mcpRemove(row.name);
        await load();
      } catch (e) {
        toast.error((e as Error)?.message || 'Failed to remove connector.');
      } finally {
        setBusyId(null);
      }
    },
    [load]
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto px-3 py-3">
      {integrations.length > 0 ? (
        <div className="mb-4">
          <div className="mb-1 flex items-center gap-1.5">
            <KeyRound
              size={13}
              aria-hidden
              className="shrink-0 text-ds-icon-neutral-subtle-default"
            />
            <span className="text-body-sm font-bold text-ds-text-neutral-default-default">
              API keys
            </span>
          </div>
          <div className="mb-2 text-label-xs text-ds-text-neutral-subtle-default">
            Set your own tokens for built-in tools. Stored locally; the agent
            picks them up on its next task.
          </div>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {integrations.map((intg) => {
              const isOpen = openIntegration === intg.key;
              const connected = intg.envVars.every((k) => envStatus[k]);
              const partial =
                !connected && intg.envVars.some((k) => envStatus[k]);
              const busy = savingKey === intg.key;
              return (
                <li
                  key={intg.key}
                  className="rounded-lg transition-colors hover:bg-ds-bg-neutral-muted-default"
                >
                  <button
                    type="button"
                    onClick={() =>
                      setOpenIntegration(isOpen ? null : intg.key)
                    }
                    className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left outline-none"
                  >
                    {isOpen ? (
                      <ChevronDown
                        size={14}
                        aria-hidden
                        className="shrink-0 text-ds-icon-neutral-subtle-default"
                      />
                    ) : (
                      <ChevronRight
                        size={14}
                        aria-hidden
                        className="shrink-0 text-ds-icon-neutral-subtle-default"
                      />
                    )}
                    <span className="min-w-0 flex-1 truncate text-label-sm text-ds-text-neutral-default-default">
                      {intg.key}
                    </span>
                    <span
                      className={
                        'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ' +
                        (connected
                          ? 'bg-ds-bg-success-subtle-default text-ds-text-success-strong-default'
                          : partial
                            ? 'text-ds-text-warning-strong-default'
                            : 'text-ds-text-neutral-subtle-default')
                      }
                    >
                      {connected
                        ? 'set'
                        : partial
                          ? 'partial'
                          : 'not set'}
                    </span>
                  </button>
                  {isOpen ? (
                    <div className="flex flex-col gap-2 px-2.5 pb-2.5 pt-0.5">
                      {intg.envVars.map((k) => (
                        <label key={k} className="flex flex-col gap-1">
                          <span className="flex items-center justify-between gap-2 text-label-xs text-ds-text-neutral-subtle-default">
                            <span className="truncate font-mono">{k}</span>
                            {envStatus[k] ? (
                              <button
                                type="button"
                                onClick={() => clearKey(intg, k)}
                                disabled={busy}
                                className="flex shrink-0 items-center gap-1 rounded px-1 py-0.5 text-[10px] text-ds-text-neutral-subtle-default outline-none transition-colors hover:text-ds-icon-error-default-default disabled:opacity-50"
                              >
                                <Trash2 size={11} aria-hidden />
                                remove
                              </button>
                            ) : null}
                          </span>
                          <input
                            value={draft[k] ?? ''}
                            onChange={(e) =>
                              setDraft((d) => ({ ...d, [k]: e.target.value }))
                            }
                            placeholder={
                              envStatus[k] ? '•••••••• (set)' : 'paste value'
                            }
                            spellCheck={false}
                            type="password"
                            autoComplete="off"
                            className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-input px-2 py-1.5 font-mono text-label-xs text-ds-text-neutral-default-default outline-none"
                          />
                        </label>
                      ))}
                      <div className="flex items-center justify-end">
                        <button
                          type="button"
                          onClick={() => saveIntegration(intg)}
                          disabled={busy}
                          className="flex items-center gap-1.5 rounded-md bg-ds-bg-brand-default-default px-3 py-1.5 text-label-xs font-medium text-ds-text-brand-inverse-default outline-none transition-colors hover:bg-ds-bg-brand-default-hover disabled:opacity-50"
                        >
                          {busy ? (
                            <Loader2
                              size={12}
                              className="animate-spin"
                              aria-hidden
                            />
                          ) : (
                            <Check size={12} aria-hidden />
                          )}
                          Save
                        </button>
                      </div>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      <div className="mb-2 flex items-center justify-between">
        <span className="text-body-sm font-bold text-ds-text-neutral-default-default">
          MCP connectors
        </span>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1 rounded-md bg-ds-bg-neutral-muted-default px-2 py-1 text-label-xs text-ds-text-neutral-default-default outline-none transition-colors hover:bg-ds-bg-neutral-subtle-hover"
        >
          <Plus size={13} aria-hidden />
          Add
        </button>
      </div>

      {showForm ? (
        <div className="mb-3 flex flex-col gap-2 rounded-xl bg-ds-bg-neutral-muted-default p-3">
          {/* Guided vs. raw-JSON */}
          <div className="flex gap-0.5 rounded-lg bg-ds-bg-neutral-subtle-default p-0.5">
            {(['guided', 'json'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={
                  'flex-1 rounded-md px-2 py-1 text-label-xs font-medium outline-none transition-colors ' +
                  (mode === m
                    ? 'bg-ds-bg-neutral-default-default text-ds-text-neutral-default-default'
                    : 'text-ds-text-neutral-subtle-default hover:bg-ds-bg-neutral-subtle-hover')
                }
              >
                {m === 'guided' ? 'Remote server' : 'Paste JSON'}
              </button>
            ))}
          </div>

          {mode === 'guided' ? (
            <>
              <label className="flex flex-col gap-1">
                <span className="text-label-xs text-ds-text-neutral-subtle-default">
                  Name
                </span>
                <input
                  value={gName}
                  onChange={(e) => setGName(e.target.value)}
                  placeholder="asana"
                  spellCheck={false}
                  className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-input px-2 py-1.5 text-body-sm text-ds-text-neutral-default-default outline-none"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-label-xs text-ds-text-neutral-subtle-default">
                  Server URL
                </span>
                <input
                  value={gUrl}
                  onChange={(e) => setGUrl(e.target.value)}
                  placeholder="https://mcp.asana.com/v2/mcp"
                  spellCheck={false}
                  className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-input px-2 py-1.5 font-mono text-label-xs text-ds-text-neutral-default-default outline-none"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-label-xs text-ds-text-neutral-subtle-default">
                  Transport / auth
                </span>
                <select
                  value={gTransport}
                  onChange={(e) =>
                    setGTransport(e.target.value as typeof gTransport)
                  }
                  className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-input px-2 py-1.5 text-body-sm text-ds-text-neutral-default-default outline-none"
                >
                  <option value="streamable_http">Streamable HTTP</option>
                  <option value="sse">SSE (Server-Sent Events)</option>
                  <option value="oauth">OAuth (browser sign-in)</option>
                </select>
              </label>
              {gTransport === 'oauth' ? (
                <>
                  <div className="flex flex-col gap-1 rounded-md bg-ds-bg-neutral-subtle-default px-2 py-1.5 text-label-xs text-ds-text-neutral-subtle-default">
                    <span>
                      A browser opens to sign in; the token is saved so you
                      won&apos;t sign in again. Some providers (e.g. Asana)
                      require a pre-registered app — if so:
                    </span>
                    <span>
                      1. Create an app in the provider&apos;s developer console.
                    </span>
                    <span>
                      2. Register this redirect URI:
                      <span className="ml-1 select-all break-all font-mono text-ds-text-neutral-default-default">
                        {OAUTH_REDIRECT_URI}
                      </span>
                    </span>
                    <span>3. Paste the Client ID + Secret below.</span>
                  </div>
                  <label className="flex flex-col gap-1">
                    <span className="text-label-xs text-ds-text-neutral-subtle-default">
                      Client ID{' '}
                      <span className="text-ds-text-neutral-muted-default">
                        (only if the provider requires it)
                      </span>
                    </span>
                    <input
                      value={gClientId}
                      onChange={(e) => setGClientId(e.target.value)}
                      spellCheck={false}
                      autoComplete="off"
                      className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-input px-2 py-1.5 font-mono text-label-xs text-ds-text-neutral-default-default outline-none"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-label-xs text-ds-text-neutral-subtle-default">
                      Client Secret
                    </span>
                    <input
                      value={gClientSecret}
                      onChange={(e) => setGClientSecret(e.target.value)}
                      spellCheck={false}
                      autoComplete="off"
                      type="password"
                      className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-input px-2 py-1.5 font-mono text-label-xs text-ds-text-neutral-default-default outline-none"
                    />
                  </label>
                </>
              ) : (
                <label className="flex flex-col gap-1">
                  <span className="text-label-xs text-ds-text-neutral-subtle-default">
                    Auth token{' '}
                    <span className="text-ds-text-neutral-muted-default">
                      (optional — sent as a Bearer header)
                    </span>
                  </span>
                  <input
                    value={gToken}
                    onChange={(e) => setGToken(e.target.value)}
                    placeholder="paste a token if the server needs one"
                    spellCheck={false}
                    type="password"
                    autoComplete="off"
                    className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-input px-2 py-1.5 font-mono text-label-xs text-ds-text-neutral-default-default outline-none"
                  />
                </label>
              )}
            </>
          ) : (
            <>
              <div className="text-label-xs text-ds-text-neutral-subtle-default">
                Paste a standard <span className="font-mono">mcpServers</span>{' '}
                config — a local <span className="font-mono">command</span>, or a
                remote <span className="font-mono">url</span>. Only install
                servers you trust.
              </div>
              <textarea
                value={config}
                onChange={(e) => setConfig(e.target.value)}
                placeholder={EXAMPLE_CONFIG}
                spellCheck={false}
                className="min-h-[128px] w-full resize-y rounded-lg border border-solid border-ds-border-neutral-default-default bg-ds-bg-input px-3 py-2 font-mono text-label-xs text-ds-text-neutral-default-default outline-none placeholder:text-ds-text-neutral-subtle-default"
              />
            </>
          )}

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={resetForms}
              className="rounded-md px-2.5 py-1.5 text-label-xs text-ds-text-neutral-subtle-default outline-none transition-colors hover:bg-ds-bg-neutral-subtle-hover"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={mode === 'guided' ? installGuided : install}
              disabled={
                adding ||
                (mode === 'guided'
                  ? !gName.trim() || !gUrl.trim()
                  : !config.trim())
              }
              className="flex items-center gap-1.5 rounded-md bg-ds-bg-brand-default-default px-3 py-1.5 text-label-xs font-medium text-ds-text-brand-inverse-default outline-none transition-colors hover:bg-ds-bg-brand-default-hover disabled:opacity-50"
            >
              {adding ? (
                <Loader2 size={12} className="animate-spin" aria-hidden />
              ) : null}
              Install
            </button>
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2
            className="h-5 w-5 animate-spin text-ds-icon-neutral-subtle-default"
            aria-hidden
          />
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
          <Plug
            className="h-6 w-6 text-ds-icon-neutral-subtle-default"
            aria-hidden
          />
          <div className="text-label-sm text-ds-text-neutral-default-default">
            No connectors yet
          </div>
          <div className="max-w-[240px] text-label-xs text-ds-text-neutral-subtle-default">
            Add an MCP server to give the agent extra tools and integrations.
          </div>
        </div>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {rows.map((row) => (
            <li
              key={row.name}
              className="flex items-center gap-2 rounded-lg px-2.5 py-2 transition-colors hover:bg-ds-bg-neutral-muted-default"
            >
              <Plug
                size={14}
                aria-hidden
                className="shrink-0 text-ds-icon-neutral-subtle-default"
              />
              <span className="min-w-0 flex-1 truncate text-label-sm text-ds-text-neutral-default-default">
                {row.name}
              </span>
              <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ds-text-neutral-subtle-default">
                {row.oauth ? 'oauth' : row.remote ? 'remote' : 'local'}
              </span>
              {row.oauth ? (
                <button
                  type="button"
                  onClick={() => authenticate(row)}
                  disabled={authId === row.name}
                  title={
                    authed.has(row.name)
                      ? 'Authenticated — click to re-authenticate if it ever expires'
                      : 'Sign in (OAuth) so the agent can use this connector'
                  }
                  className={
                    'flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[10px] font-semibold outline-none transition-colors disabled:opacity-50 ' +
                    (authed.has(row.name)
                      ? 'bg-ds-bg-success-subtle-default text-ds-text-success-strong-default hover:opacity-90'
                      : 'bg-ds-bg-neutral-muted-default text-ds-text-neutral-default-default hover:bg-ds-bg-neutral-default-default')
                  }
                >
                  {authId === row.name ? (
                    <Loader2 size={12} className="animate-spin" aria-hidden />
                  ) : authed.has(row.name) ? (
                    <Check size={12} aria-hidden />
                  ) : (
                    <KeyRound size={12} aria-hidden />
                  )}
                  {authed.has(row.name) ? 'Authenticated' : 'Authenticate'}
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => remove(row)}
                disabled={busyId === row.name}
                aria-label="Remove connector"
                className="shrink-0 rounded-md p-1 text-ds-icon-neutral-subtle-default outline-none transition-colors hover:bg-ds-bg-neutral-subtle-hover hover:text-ds-icon-error-default-default disabled:opacity-50"
              >
                {busyId === row.name ? (
                  <Loader2 size={13} className="animate-spin" aria-hidden />
                ) : (
                  <Trash2 size={13} aria-hidden />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
