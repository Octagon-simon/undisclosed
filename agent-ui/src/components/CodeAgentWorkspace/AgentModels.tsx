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
 * Compact, panel-native model CONFIGURATION (BYOK) for the embedded agent. The
 * composer only has model SELECTION; this lets the user add/edit their own cloud
 * provider + API key so they can run their own model. Deliberately a slim
 * rewrite of the desktop Models page (SettingModels), not a reuse — that page's
 * wide, multi-tab layout doesn't fit the narrow panel.
 *
 * Reuses the exact backend contract: GET /api/v1/providers, POST/PUT
 * /api/v1/provider, POST /api/v1/provider/prefer, DELETE /api/v1/provider/{id},
 * and the Brain's /model/validate for an optional key check. Setting a default
 * is reflected by the composer picker (it reads the same /providers).
 *
 * v1 = cloud BYOK. Local runtimes (Ollama/LM Studio) are a follow-up.
 */

import {
  fetchPostWithTimeout,
  proxyFetchDelete,
  proxyFetchGet,
  proxyFetchPost,
  proxyFetchPut,
} from '@/api/http';
import { toProviderValidStatus } from '@/lib/providerStatus';
import {
  Check,
  Eye,
  EyeOff,
  Loader2,
  Pencil,
  Plus,
  Star,
  Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

/** A configurable provider. `id` is the backend `provider_name` (==
 *  model_platform). `needsUrl` requires a base URL; `local` runtimes need no API
 *  key and prefill their default localhost endpoint. */
type Preset = {
  id: string;
  label: string;
  modelHint: string;
  needsUrl?: boolean;
  local?: boolean;
  defaultEndpoint?: string;
};

const CLOUD_PROVIDERS: Preset[] = [
  { id: 'openai', label: 'OpenAI', modelHint: 'gpt-4o' },
  { id: 'anthropic', label: 'Anthropic', modelHint: 'claude-sonnet-5' },
  { id: 'gemini', label: 'Google Gemini', modelHint: 'gemini-3-pro-preview' },
  { id: 'deepseek', label: 'DeepSeek', modelHint: 'deepseek-chat' },
  { id: 'qwen', label: 'Qwen', modelHint: 'qwen-max' },
  { id: 'openrouter', label: 'OpenRouter', modelHint: 'openai/gpt-4o' },
  {
    id: 'openai-compatible',
    label: 'OpenAI-compatible',
    modelHint: 'model-name',
    needsUrl: true,
  },
];

// Local runtimes (OpenAI-compatible servers on localhost). Endpoints mirror
// src/pages/Agents/localModels.ts; inlined to keep the embed self-contained.
const LOCAL_PROVIDERS: Preset[] = [
  {
    id: 'ollama',
    label: 'Ollama',
    modelHint: 'llama3.1',
    local: true,
    needsUrl: true,
    defaultEndpoint: 'http://localhost:11434/v1',
  },
  {
    id: 'lmstudio',
    label: 'LM Studio',
    modelHint: 'model-name',
    local: true,
    needsUrl: true,
    defaultEndpoint: 'http://localhost:1234/v1',
  },
  {
    id: 'vllm',
    label: 'vLLM',
    modelHint: 'model-name',
    local: true,
    needsUrl: true,
    defaultEndpoint: 'http://localhost:8000/v1',
  },
  {
    id: 'sglang',
    label: 'SGLang',
    modelHint: 'model-name',
    local: true,
    needsUrl: true,
    defaultEndpoint: 'http://localhost:30000/v1',
  },
  {
    id: 'llama.cpp',
    label: 'LLaMA.cpp',
    modelHint: 'model-name',
    local: true,
    needsUrl: true,
    defaultEndpoint: 'http://localhost:8080/v1',
  },
];

const PROVIDERS: Preset[] = [...CLOUD_PROVIDERS, ...LOCAL_PROVIDERS];

interface ProviderRow {
  id: string | number;
  provider_name: string;
  model_type?: string;
  endpoint_url?: string;
  api_key?: string;
  prefer?: boolean;
}

const labelFor = (name: string) =>
  PROVIDERS.find((p) => p.id === name)?.label || name;

const emptyForm = {
  provider_name: 'openai',
  api_key: '',
  model_type: '',
  endpoint_url: '',
};

export default function AgentModels() {
  const [rows, setRows] = useState<ProviderRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | number | null>(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | number | null>(null);

  const preset = PROVIDERS.find((p) => p.id === form.provider_name);
  const isLocal = !!preset?.local;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await proxyFetchGet('/api/v1/providers');
      const list = Array.isArray(res) ? res : res?.items || [];
      setRows(list);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openAdd = () => {
    setEditingId(null);
    setForm({ ...emptyForm });
    setShowKey(false);
    setShowForm(true);
  };

  const openEdit = (row: ProviderRow) => {
    setEditingId(row.id);
    setForm({
      provider_name: row.provider_name,
      api_key: row.api_key || '',
      model_type: row.model_type || '',
      endpoint_url: row.endpoint_url || '',
    });
    setShowKey(false);
    setShowForm(true);
  };

  const save = async () => {
    if (!form.model_type.trim()) {
      toast.error('Enter a model name.');
      return;
    }
    if (!editingId && !isLocal && !form.api_key.trim()) {
      toast.error('Enter your API key.');
      return;
    }
    if (preset?.needsUrl && !form.endpoint_url.trim()) {
      toast.error('This provider needs a base URL.');
      return;
    }
    setSaving(true);
    try {
      // Optional, best-effort key check (Eigent needs tool-calling support).
      // Don't hard-block on transport errors — only on a clear invalid verdict.
      try {
        const v = await fetchPostWithTimeout('/model/validate', {
          model_platform: form.provider_name,
          model_type: form.model_type,
          api_key: isLocal ? null : form.api_key || null,
          url: form.endpoint_url || undefined,
          model_config_dict: {},
          extra_params: {},
        });
        if (v && v.is_valid === false) {
          toast.error('That key/model failed validation. Check and retry.');
          setSaving(false);
          return;
        }
        if (v && v.is_tool_calls === false) {
          toast.warning(
            'This model may not support tool-calling, which Eigent needs.'
          );
        }
      } catch {
        /* validation endpoint unreachable — proceed to save anyway */
      }

      const data = {
        provider_name: form.provider_name,
        api_key: isLocal ? 'not-required' : form.api_key,
        endpoint_url: form.endpoint_url || undefined,
        is_valid: toProviderValidStatus(true),
        model_type: form.model_type,
        encrypted_config: {
          model_platform: form.provider_name,
          model_type: form.model_type,
        },
      };
      if (editingId) {
        await proxyFetchPut(`/api/v1/provider/${editingId}`, data);
      } else {
        await proxyFetchPost('/api/v1/provider', data);
      }
      toast.success(editingId ? 'Provider updated.' : 'Provider added.');
      setShowForm(false);
      await load();
    } catch (e: any) {
      toast.error(e?.message || 'Failed to save the provider.');
    } finally {
      setSaving(false);
    }
  };

  const setDefault = async (row: ProviderRow) => {
    setBusyId(row.id);
    try {
      await proxyFetchPost('/api/v1/provider/prefer', { provider_id: row.id });
      setRows((rs) => rs.map((r) => ({ ...r, prefer: r.id === row.id })));
      toast.success(`${labelFor(row.provider_name)} is now the default model.`);
    } catch (e: any) {
      toast.error(e?.message || 'Failed to set default.');
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (row: ProviderRow) => {
    setBusyId(row.id);
    try {
      await proxyFetchDelete(`/api/v1/provider/${row.id}`);
      setRows((rs) => rs.filter((r) => r.id !== row.id));
      toast.success('Provider removed.');
    } catch (e: any) {
      toast.error(e?.message || 'Failed to remove the provider.');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col px-3 pb-3">
      <div className="flex items-center justify-between py-2">
        <div className="text-body-sm font-semibold text-ds-text-neutral-default-default">
          Models
        </div>
        {!showForm && (
          <button
            type="button"
            onClick={openAdd}
            className="flex items-center gap-1 rounded-md bg-ds-bg-neutral-muted-default px-2 py-1 text-label-xs font-semibold text-ds-text-neutral-default-default outline-none transition-colors hover:bg-ds-bg-neutral-default-default"
          >
            <Plus size={13} aria-hidden />
            Add model
          </button>
        )}
      </div>

      {showForm ? (
        <div className="flex flex-col gap-2.5 rounded-xl bg-ds-bg-neutral-muted-default p-3">
          <label className="flex flex-col gap-1">
            <span className="text-label-xs text-ds-text-neutral-subtle-default">
              Provider
            </span>
            <select
              value={form.provider_name}
              onChange={(e) => {
                const id = e.target.value;
                const p = PROVIDERS.find((x) => x.id === id);
                setForm((f) => ({
                  ...f,
                  provider_name: id,
                  // Prefill a local runtime's default endpoint when the URL is empty.
                  endpoint_url:
                    p?.local && p.defaultEndpoint && !f.endpoint_url
                      ? p.defaultEndpoint
                      : f.endpoint_url,
                }));
              }}
              className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-2 py-1.5 text-body-sm text-ds-text-neutral-default-default outline-none"
            >
              <optgroup label="Cloud">
                {CLOUD_PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Local runtimes">
                {LOCAL_PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>

          {isLocal ? (
            <div className="rounded-md bg-ds-bg-neutral-subtle-default px-2 py-1.5 text-label-xs text-ds-text-neutral-subtle-default">
              No API key needed — this runs against your local server.
            </div>
          ) : (
            <label className="flex flex-col gap-1">
              <span className="text-label-xs text-ds-text-neutral-subtle-default">
                API key
              </span>
              <div className="flex items-center gap-1">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={form.api_key}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={
                    editingId ? 'Leave unchanged, or paste a new key' : 'sk-…'
                  }
                  onChange={(e) =>
                    setForm((f) => ({ ...f, api_key: e.target.value }))
                  }
                  className="min-w-0 flex-1 rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-2 py-1.5 font-mono text-label-xs text-ds-text-neutral-default-default outline-none"
                />
                <button
                  type="button"
                  aria-label={showKey ? 'Hide API key' : 'Show API key'}
                  onClick={() => setShowKey((s) => !s)}
                  className="rounded-md p-1.5 text-ds-text-neutral-subtle-default outline-none hover:bg-ds-bg-neutral-default-default"
                >
                  {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </label>
          )}

          <label className="flex flex-col gap-1">
            <span className="text-label-xs text-ds-text-neutral-subtle-default">
              Model name
            </span>
            <input
              value={form.model_type}
              spellCheck={false}
              placeholder={preset?.modelHint}
              onChange={(e) =>
                setForm((f) => ({ ...f, model_type: e.target.value }))
              }
              className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-2 py-1.5 font-mono text-label-xs text-ds-text-neutral-default-default outline-none"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-label-xs text-ds-text-neutral-subtle-default">
              Base URL{' '}
              {preset?.needsUrl ? (
                <span className="text-ds-text-error-default-default">
                  (required)
                </span>
              ) : (
                <span>(optional)</span>
              )}
            </span>
            <input
              value={form.endpoint_url}
              spellCheck={false}
              placeholder="https://api.provider.com/v1"
              onChange={(e) =>
                setForm((f) => ({ ...f, endpoint_url: e.target.value }))
              }
              className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-2 py-1.5 font-mono text-label-xs text-ds-text-neutral-default-default outline-none"
            />
          </label>

          <div className="mt-1 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              disabled={saving}
              className="rounded-md px-2.5 py-1 text-label-xs text-ds-text-neutral-subtle-default outline-none hover:bg-ds-bg-neutral-default-default disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="flex items-center gap-1.5 rounded-md bg-ds-bg-information-default-default px-3 py-1 text-label-xs font-semibold text-ds-text-inverse-default-default outline-none transition-colors hover:opacity-90 disabled:opacity-50"
            >
              {saving && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
              {editingId ? 'Save changes' : 'Add model'}
            </button>
          </div>
        </div>
      ) : loading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-4 w-4 animate-spin text-ds-text-neutral-subtle-default" />
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-1 px-4 text-center">
          <div className="text-body-sm text-ds-text-neutral-default-default">
            No models configured
          </div>
          <div className="text-label-xs text-ds-text-neutral-subtle-default">
            Add a provider and API key to run your own model.
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto">
          {rows.map((row) => (
            <div
              key={row.id}
              className="flex items-center gap-2 rounded-xl bg-ds-bg-neutral-muted-default px-2.5 py-2"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-body-sm font-semibold text-ds-text-neutral-default-default">
                    {labelFor(row.provider_name)}
                  </span>
                  {row.prefer && (
                    <span className="flex items-center gap-0.5 rounded-full bg-ds-bg-success-subtle-default px-1.5 py-0.5 text-label-xs font-medium text-ds-text-success-strong-default">
                      <Check size={10} aria-hidden />
                      Default
                    </span>
                  )}
                </div>
                {row.model_type && (
                  <div className="truncate font-mono text-label-xs text-ds-text-neutral-subtle-default">
                    {row.model_type}
                  </div>
                )}
              </div>
              {busyId === row.id ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-ds-text-neutral-subtle-default" />
              ) : (
                <div className="flex items-center gap-0.5">
                  {!row.prefer && (
                    <button
                      type="button"
                      aria-label="Set as default"
                      title="Set as default"
                      onClick={() => setDefault(row)}
                      className="rounded-md p-1.5 text-ds-text-neutral-subtle-default outline-none hover:bg-ds-bg-neutral-default-default"
                    >
                      <Star size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    aria-label="Edit"
                    title="Edit"
                    onClick={() => openEdit(row)}
                    className="rounded-md p-1.5 text-ds-text-neutral-subtle-default outline-none hover:bg-ds-bg-neutral-default-default"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    type="button"
                    aria-label="Remove"
                    title="Remove"
                    onClick={() => remove(row)}
                    className="rounded-md p-1.5 text-ds-text-error-default-default outline-none hover:bg-ds-bg-neutral-default-default"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
