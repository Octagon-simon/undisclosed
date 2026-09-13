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
 * Default model picker for the chat input bar.
 *
 * Data-driven: it renders the models that are ACTUALLY configured
 * (`GET /api/v1/providers`), grouped per provider, one entry per row. That is
 * what lets DeepSeek show both `deepseek-chat` and `deepseek-v4-flash` instead
 * of collapsing to a single "Deepseek" entry that always pinned the first row.
 *
 * Selecting a row pins that exact row: for a project it stores the row's
 * `provider_id` + `model_type` on the Project; otherwise it sets the row as the
 * server-side default (`POST /api/v1/provider/prefer`). Providers that are not
 * configured yet are still listed under "Add …" and route to the models screen.
 */

import { proxyFetchGet } from '@/api/http';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { requestEmbedScreen } from '@/agent-embed/embedNav';
import { createHost } from '@/host/createHost';
import {
  DEFAULT_MODEL_CONFIGURE_PATH,
  preferProviderRow,
} from '@/lib/applyDefaultModelSelection';
import { INIT_PROVODERS } from '@/lib/llm';
import {
  isLocalProviderId,
  providerPreset,
} from '@/lib/providerRegistry';
import { cn } from '@/lib/utils';
import {
  LOCAL_MODEL_OPTIONS,
} from '@/pages/Agents/localModels';
import {
  getModelImage,
  needsInvertModelImage,
} from '@/shared/modelProviderImages';
import { useAuthStore } from '@/store/authStore';
import { useCloudModelStore } from '@/store/cloudModelStore';
import { useProjectRuntimeStore } from '@/store/projectRuntimeStore';
import { useSpaceStore } from '@/store/spaceStore';

import {
  Check,
  ChevronDown,
  HardDrive,
  Key,
  Layers,
  Plus,
  Server,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

export interface ModelSelectProps {
  disabled?: boolean;
  /**
   * Project whose pinned model this dropdown reads and writes. When set,
   * selections update only that Project's captured model; the global
   * default model is left untouched.
   */
  projectId?: string | null;
  /**
   * When true, shows the current default model in the same shell as
   * `ProjectModeToggle` (readOnly) — no chevron, not interactive,
   * no filled background (session input bar).
   * Used for session chat input where the model is fixed for the session.
   */
  readOnly?: boolean;
}

/** A configured provider row as served by `GET /api/v1/providers`. */
interface ProviderRow {
  id: number;
  provider_name: string;
  model_type?: string;
  endpoint_url?: string;
  api_key?: string;
  prefer?: boolean;
  is_valid?: unknown;
  encrypted_config?: Record<string, unknown> | null;
}

type ProviderSelectionKind = 'custom' | 'local';

interface ProviderGroup {
  providerName: string;
  label: string;
  rows: ProviderRow[];
}

const modelTriggerShellClass = cn(
  'rounded-xl px-2 py-1 inline-flex min-w-0 max-w-[min(100%,320px)] shrink items-center gap-1.5',
  'bg-ds-bg-neutral-default-default text-ds-text-neutral-default-default'
);

const CATALOG_LABELS = new Map<string, string>(
  INIT_PROVODERS.map((p) => [p.id, p.name])
);

/** Preset label first, then the wider catalog, then the raw id. */
function catalogLabel(id: string): string {
  const preset = providerPreset(id);
  if (preset) return preset.label;
  return CATALOG_LABELS.get(id) ?? id;
}

function rowLabel(row: ProviderRow): string {
  const base = catalogLabel(row.provider_name);
  return row.model_type ? `${base} (${row.model_type})` : base;
}

/** Keep preset providers in their catalog order, unknown ids last. */
function presetIndex(id: string, presets: { id: string }[]): number {
  const index = presets.findIndex((p) => p.id === id);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

export function ModelSelect({
  disabled,
  projectId,
  readOnly = false,
}: ModelSelectProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const {
    modelType,
    cloud_model_type,
    codex_model_type,
    email,
    appearance,
    setModelType,
  } = useAuthStore();

  const cloudModels = useCloudModelStore((state) => state.models);
  const fetchCloudModels = useCloudModelStore(
    (state) => state.fetchCloudModels
  );
  const getCloudModelDisplayName = useCloudModelStore(
    (state) => state.getModelDisplayName
  );

  const setProjectModel = useProjectRuntimeStore(
    (state) => state.setProjectModel
  );
  const runtimePinnedSelection = useProjectRuntimeStore((state) =>
    projectId
      ? (state.projects[projectId]?.metadata?.modelSelection ?? null)
      : null
  );
  const spacePinnedSelection = useSpaceStore((state) => {
    if (!projectId) return null;
    const spaceId = state.projectIdIndex[projectId];
    if (!spaceId) return null;
    return (
      state.projectsBySpaceId[spaceId]?.[projectId]?.metadata?.modelSelection ??
      null
    );
  });
  const pinnedSelection = projectId
    ? (runtimePinnedSelection ?? spacePinnedSelection)
    : null;

  const [providers, setProviders] = useState<ProviderRow[]>([]);
  const [open, setOpen] = useState(false);
  const [codexStatus, setCodexStatus] = useState<{
    connected: boolean;
    status: string;
  }>({ connected: false, status: 'not_connected' });

  const loadProviders = useCallback(async () => {
    try {
      const res = await proxyFetchGet('/api/v1/providers');
      const list = Array.isArray(res) ? res : res?.items || [];
      setProviders(list as ProviderRow[]);
    } catch (error) {
      console.error('Error fetching providers:', error);
      setProviders([]);
    }
  }, []);

  useEffect(() => {
    if (import.meta.env.VITE_USE_LOCAL_PROXY === 'true') return;
    void fetchCloudModels();
  }, [fetchCloudModels]);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders, modelType]);

  const refreshCodexStatus = useCallback(async () => {
    if (!email) {
      setCodexStatus({ connected: false, status: 'not_connected' });
      return;
    }
    try {
      const status =
        await createHost().electronAPI?.codexSubscriptionStatus?.(email);
      setCodexStatus(status || { connected: false, status: 'not_connected' });
    } catch (error) {
      console.error('Failed to load Codex subscription status:', error);
      setCodexStatus({ connected: false, status: 'error' });
    }
  }, [email]);

  useEffect(() => {
    refreshCodexStatus();
  }, [refreshCodexStatus]);

  useEffect(() => {
    const ipcRenderer = createHost().ipcRenderer;
    if (!ipcRenderer?.on || !ipcRenderer?.off) return;
    const listener = () => {
      refreshCodexStatus();
    };
    ipcRenderer.on('subscription-auth:codex-status-changed', listener);
    return () => {
      ipcRenderer.off('subscription-auth:codex-status-changed', listener);
    };
  }, [refreshCodexStatus]);

  const codexProvider = useMemo(
    () => INIT_PROVODERS.find((p) => p.authMode === 'oauth_subscription'),
    []
  );

  /** Every configured row, grouped by provider_name. */
  const groups = useMemo<ProviderGroup[]>(() => {
    const byName = new Map<string, ProviderGroup>();
    for (const row of providers) {
      const name = row.provider_name;
      let group = byName.get(name);
      if (!group) {
        group = { providerName: name, label: catalogLabel(name), rows: [] };
        byName.set(name, group);
      }
      group.rows.push(row);
    }
    return [...byName.values()];
  }, [providers]);

  const configuredNames = useMemo(
    () => new Set(providers.map((p) => p.provider_name)),
    [providers]
  );

  const cloudGroups = useMemo(
    () =>
      groups
        .filter((g) => !isLocalProviderId(g.providerName))
        .sort((a, b) => {
          const order = (id: string) => {
            const cloudOrder = [
              'openai',
              'anthropic',
              'gemini',
              'deepseek',
              'tongyi-qianwen',
              'openrouter',
              'openai-compatible-model',
            ];
            const idx = cloudOrder.indexOf(id);
            return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
          };
          const diff = order(a.providerName) - order(b.providerName);
          return diff !== 0 ? diff : a.label.localeCompare(b.label);
        }),
    [groups]
  );

  const localGroups = useMemo(
    () =>
      groups
        .filter((g) => isLocalProviderId(g.providerName))
        .sort(
          (a, b) =>
            presetIndex(a.providerName, LOCAL_MODEL_OPTIONS) -
            presetIndex(b.providerName, LOCAL_MODEL_OPTIONS)
        ),
    [groups]
  );

  /** Catalog providers with nothing configured yet → route to models screen. */
  const unconfiguredCloud = useMemo(
    () =>
      INIT_PROVODERS.filter(
        (p) =>
          p.authMode !== 'oauth_subscription' &&
          !isLocalProviderId(p.id) &&
          !configuredNames.has(p.id)
      ),
    [configuredNames]
  );

  const unconfiguredLocal = useMemo(
    () =>
      LOCAL_MODEL_OPTIONS.filter((m) => !configuredNames.has(m.id)),
    [configuredNames]
  );

  const activeRow = useMemo(() => {
    if (pinnedSelection?.provider_id !== undefined) {
      return providers.find((p) => p.id === pinnedSelection.provider_id);
    }
    if (pinnedSelection) return undefined;
    return providers.find((p) => p.prefer);
  }, [pinnedSelection, providers]);

  const codexIsPreferred = pinnedSelection
    ? pinnedSelection.modelType === 'codex_subscription'
    : modelType === 'codex_subscription';

  const isDefaultRow = useCallback(
    (row: ProviderRow, kind: ProviderSelectionKind): boolean => {
      if (pinnedSelection) {
        return (
          pinnedSelection.modelType === kind &&
          pinnedSelection.provider_id === row.id
        );
      }
      return !!row.prefer;
    },
    [pinnedSelection]
  );

  const needsInvert = (modelId: string | null): boolean =>
    needsInvertModelImage(modelId, appearance);

  const handleCodexSetDefault = useCallback(() => {
    if (projectId) {
      const codexModelId = codex_model_type || 'gpt-5.5';
      setProjectModel(projectId, {
        modelType: 'codex_subscription',
        codex_model_type: codexModelId,
        model_platform: 'openai',
        model_type: codexModelId,
      });
      return;
    }
    setModelType('codex_subscription');
  }, [codex_model_type, projectId, setModelType, setProjectModel]);

  const handleSelectRow = useCallback(
    async (row: ProviderRow) => {
      const kind: ProviderSelectionKind = isLocalProviderId(row.provider_name)
        ? 'local'
        : 'custom';
      if (projectId) {
        setProjectModel(projectId, {
          modelType: kind,
          provider_id: row.id,
          model_platform: row.provider_name,
          model_type: row.model_type || undefined,
        });
        return;
      }
      const ok = await preferProviderRow(row.id, t);
      if (!ok) return;
      setModelType(kind);
      setProviders((prev) =>
        prev.map((p) => ({ ...p, prefer: p.id === row.id }))
      );
    },
    [projectId, setModelType, setProjectModel, t]
  );

  /** Model name only in the trigger (e.g. "DeepSeek (deepseek-v4-flash)"). */
  const triggerModelName = useMemo(() => {
    if (pinnedSelection) {
      if (pinnedSelection.modelType === 'codex_subscription') {
        const pinnedCodexModelType = pinnedSelection.codex_model_type || '';
        return `Codex Subscription${pinnedCodexModelType ? ` (${pinnedCodexModelType})` : ''}`;
      }
      if (pinnedSelection.modelType === 'cloud') {
        return getCloudModelDisplayName(
          pinnedSelection.cloud_model_type || cloud_model_type
        );
      }
      if (
        pinnedSelection.modelType === 'custom' ||
        pinnedSelection.modelType === 'local'
      ) {
        if (activeRow) {
          return rowLabel(activeRow);
        }
        // Providers still loading (or the pinned provider disappeared):
        // fall back to the identifiers captured with the pin.
        if (pinnedSelection.model_platform || pinnedSelection.model_type) {
          const platformLabel = pinnedSelection.model_platform || '';
          const mt = pinnedSelection.model_type || '';
          return platformLabel ? `${platformLabel}${mt ? ` (${mt})` : ''}` : mt;
        }
      }
    }

    if (modelType === 'codex_subscription') {
      return `Codex Subscription${codex_model_type ? ` (${codex_model_type})` : ''}`;
    }

    if (modelType === 'cloud') {
      return getCloudModelDisplayName(cloud_model_type);
    }

    if (activeRow) {
      return rowLabel(activeRow);
    }

    return t('setting.select-default-model');
  }, [
    activeRow,
    cloud_model_type,
    codex_model_type,
    getCloudModelDisplayName,
    modelType,
    pinnedSelection,
    t,
  ]);

  const activeSubTriggerRef = useRef<HTMLElement | null>(null);

  // Bottom-align the sub content with the trigger row purely imperatively:
  // shift the content up by (subHeight - triggerHeight) via marginTop.
  // No React state is touched, so this can never cause a re-render loop.
  const subContentCallbackRef = useCallback((el: HTMLDivElement | null) => {
    if (!el) return;
    const trigger = activeSubTriggerRef.current;
    if (!trigger) return;
    const subH = el.offsetHeight;
    const trigH = trigger.offsetHeight;
    if (subH <= 0 || trigH <= 0) return;
    el.style.marginTop = `${trigH - subH}px`;
  }, []);

  const renderProviderGroup = (
    group: ProviderGroup,
    kind: ProviderSelectionKind
  ) => (
    <div key={group.providerName}>
      <DropdownMenuLabel className="px-2 py-1 text-label-xs text-ds-text-neutral-subtle-default">
        {group.label}
      </DropdownMenuLabel>
      {group.rows.map((row) => {
        const isDefault = isDefaultRow(row, kind);
        const modelImage = getModelImage(row.provider_name);
        return (
          <DropdownMenuItem
            key={row.id}
            onSelect={() => {
              void handleSelectRow(row);
            }}
            className="flex items-center justify-between"
          >
            <div className="flex min-w-0 items-center gap-2">
              {modelImage ? (
                <img
                  src={modelImage}
                  alt={group.label}
                  className="h-4 w-4 shrink-0"
                  style={
                    needsInvert(row.provider_name)
                      ? { filter: 'invert(1)' }
                      : undefined
                  }
                />
              ) : (
                <Key className="h-3 w-3 shrink-0 text-ds-icon-neutral-muted-default" />
              )}
              <span className="truncate text-body-sm text-ds-text-neutral-default-default">
                {rowLabel(row)}
              </span>
            </div>
            {isDefault ? (
              <Check className="h-4 w-4 shrink-0 text-ds-text-success-default-default" />
            ) : (
              <div className="h-2 w-2 shrink-0 rounded-full bg-ds-text-neutral-subtle-default opacity-10" />
            )}
          </DropdownMenuItem>
        );
      })}
    </div>
  );

  const renderAddEntry = (label: string) => (
    <DropdownMenuItem
      key={`add-${label}`}
      onSelect={() => {
        // Embedded panel (Theia agent widget) has no app router, so the
        // navigate() below is a no-op there — request the Models screen so the
        // panel body actually switches. Desktop/app: no listener, navigate wins.
        requestEmbedScreen('models');
        navigate(DEFAULT_MODEL_CONFIGURE_PATH);
      }}
      className="flex items-center gap-2"
    >
      <Plus className="h-3.5 w-3.5 shrink-0 text-ds-icon-neutral-muted-default" />
      <span className="truncate text-body-sm text-ds-text-neutral-subtle-default">
        {t('setting.add-model', { defaultValue: 'Add' })} {label}
      </span>
    </DropdownMenuItem>
  );

  if (readOnly) {
    return (
      <div
        role="status"
        title={triggerModelName}
        aria-label={triggerModelName}
        className={cn(modelTriggerShellClass, 'pointer-events-none bg-transparent', {
          'opacity-50': disabled,
        })}
      >
        <span className="inline-flex min-h-[1.25rem] min-w-0 items-center gap-1.5 overflow-hidden">
          <span className="min-w-0 truncate !text-label-xs font-semibold">
            {triggerModelName}
          </span>
        </span>
      </div>
    );
  }

  return (
    <DropdownMenu
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          void loadProviders();
          void fetchCloudModels();
        }
      }}
    >
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          title={triggerModelName}
          aria-label={triggerModelName}
          aria-haspopup="menu"
          className={cn(
            modelTriggerShellClass,
            'min-w-0 cursor-pointer border-0 text-left',
            'duration-[160ms] ease-[cubic-bezier(0.23,1,0.32,1)] justify-between font-semibold transition-[background-color,box-shadow,opacity]',
            'hover:bg-ds-bg-neutral-subtle-default active:bg-ds-bg-neutral-subtle-default data-[state=open]:bg-ds-bg-neutral-subtle-default',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-border-neutral-strong-default focus-visible:ring-offset-2 focus-visible:ring-offset-ds-bg-neutral-default-default',
            'disabled:pointer-events-none disabled:opacity-50',
            // While open, only the trigger's content grows to the menu width;
            // the chevron stays pinned at the right edge.
            open && 'min-w-[180px]'
          )}
        >
          <span className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
            <span className="min-w-0 flex-1 truncate text-center !text-label-xs text-ds-text-neutral-default-default">
              {triggerModelName}
            </span>
          </span>
          <ChevronDown
            className="h-3.5 w-3.5 shrink-0 opacity-80"
            aria-hidden
            strokeWidth={2}
          />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        side="top"
        sideOffset={4}
        collisionPadding={12}
        avoidCollisions
        className="w-[180px]"
      >
        {/* No hosted "Cloud" offering: this build runs on BYOK + local models
            only. The cloud model section was removed intentionally. */}
        <DropdownMenuSub>
          <DropdownMenuSubTrigger
            className="flex w-full min-w-0 items-center justify-start gap-2 [&>svg:first-child]:!h-5 [&>svg:first-child]:!min-h-4 [&>svg:first-child]:!w-4 [&>svg:first-child]:!min-w-4"
            onPointerEnter={(e) => {
              activeSubTriggerRef.current = e.currentTarget;
            }}
          >
            <Layers
              className="shrink-0 text-ds-icon-neutral-default-default"
              aria-hidden
            />
            <span className="min-w-0 flex-1 text-left text-body-sm">
              {t('setting.custom-model')}
            </span>
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent
            ref={subContentCallbackRef}
            className="max-h-[440px] w-[220px] overflow-y-auto"
          >
            {codexProvider && (
              <DropdownMenuItem
                onSelect={() => {
                  if (codexStatus.connected) {
                    handleCodexSetDefault();
                  } else {
                    requestEmbedScreen('models');
                    navigate(DEFAULT_MODEL_CONFIGURE_PATH);
                  }
                }}
                className="flex items-center justify-between"
              >
                <div className="flex items-center gap-2">
                  <img
                    src={getModelImage(codexProvider.id) ?? ''}
                    alt={codexProvider.name}
                    className="h-4 w-4"
                  />
                  <span
                    className={`text-body-sm ${codexStatus.connected ? 'text-ds-text-neutral-default-default' : 'text-ds-text-neutral-subtle-default'}`}
                  >
                    {codexProvider.name}
                  </span>
                </div>
                {codexIsPreferred && (
                  <Check className="h-4 w-4 text-ds-text-success-default-default" />
                )}
              </DropdownMenuItem>
            )}

            {cloudGroups.map((group) => renderProviderGroup(group, 'custom'))}

            {cloudGroups.length > 0 &&
              (unconfiguredCloud.length > 0 || unconfiguredLocal.length > 0) && (
                <DropdownMenuSeparator />
              )}

            {unconfiguredCloud.map((p) => renderAddEntry(catalogLabel(p.id)))}
          </DropdownMenuSubContent>
        </DropdownMenuSub>

        <DropdownMenuSub>
          <DropdownMenuSubTrigger
            className="flex w-full min-w-0 items-center justify-start gap-2 [&>svg:first-child]:!h-4 [&>svg:first-child]:!min-h-4 [&>svg:first-child]:!w-4 [&>svg:first-child]:!min-w-4"
            onPointerEnter={(e) => {
              activeSubTriggerRef.current = e.currentTarget;
            }}
          >
            <HardDrive
              className="shrink-0 text-ds-icon-neutral-default-default"
              aria-hidden
            />
            <span className="min-w-0 flex-1 text-left text-body-sm">
              {t('setting.local-model')}
            </span>
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent ref={subContentCallbackRef} className="w-[200px]">
            {localGroups.map((group) => renderProviderGroup(group, 'local'))}
            {localGroups.length > 0 && unconfiguredLocal.length > 0 && (
              <DropdownMenuSeparator />
            )}
            {unconfiguredLocal.map((m) => renderAddEntry(m.name))}
            {localGroups.length === 0 && unconfiguredLocal.length === 0 && (
              <DropdownMenuItem disabled className="text-body-sm">
                {t('setting.no-local-models', {
                  defaultValue: 'No local models configured',
                })}
              </DropdownMenuItem>
            )}
          </DropdownMenuSubContent>
        </DropdownMenuSub>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
