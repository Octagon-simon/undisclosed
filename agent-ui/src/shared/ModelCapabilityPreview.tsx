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
 * Capability tags for a model that has not been saved yet.
 *
 * The tags come from `GET /api/v1/providers/capabilities`, which derives them
 * with the same brain functions the tools use, so the panel cannot promise a
 * capability the agent will not act on.
 */

import { proxyFetchGet } from '@/api/http';
import { cn } from '@/lib/utils';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ModelCapabilityTags } from './ModelCapabilityTags';

const DEBOUNCE_MS = 300;

interface Preview {
  model: string;
  capabilities: string[];
  failed: boolean;
}

export interface ModelCapabilityPreviewProps {
  /** Provider id as stored in providers.json, e.g. `deepseek`. */
  providerName: string;
  modelType: string;
  className?: string;
}

export function ModelCapabilityPreview({
  providerName,
  modelType,
  className,
}: ModelCapabilityPreviewProps) {
  const { t } = useTranslation();
  const model = modelType.trim();
  const [preview, setPreview] = useState<Preview | null>(null);

  useEffect(() => {
    if (!model) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const response = await proxyFetchGet('/api/v1/providers/capabilities', {
          provider_name: providerName,
          model_type: model,
        });
        if (cancelled) return;
        setPreview({
          model,
          capabilities: Array.isArray(response?.capabilities)
            ? response.capabilities
            : [],
          failed: false,
        });
      } catch {
        if (!cancelled) {
          setPreview({ model, capabilities: [], failed: true });
        }
      }
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [model, providerName]);

  if (!model) return null;

  // A result for a previous model must not be shown while the next one is in
  // flight: a stale answer would tag the new model with the old capabilities.
  const current = preview?.model === model ? preview : null;
  const muted = 'text-label-xs text-ds-text-neutral-muted-default';

  return (
    <div
      className={cn(
        // Full width so the row starts at the field edge and wraps inside it.
        'flex w-full flex-wrap items-center justify-start gap-x-2 gap-y-1 pt-1',
        muted,
        className
      )}
      aria-live="polite"
    >
      <span>
        {t('setting.capabilities-label', { defaultValue: 'Capabilities' })}
      </span>
      {current?.failed ? (
        <span className="opacity-70">
          {t('setting.capabilities-unavailable', {
            defaultValue: "Couldn't check capabilities",
          })}
        </span>
      ) : current === null ? (
        <span className="opacity-70">
          {t('setting.capabilities-checking', { defaultValue: 'Checking…' })}
        </span>
      ) : current.capabilities.length > 0 ? (
        <>
          <ModelCapabilityTags capabilities={current.capabilities} size="sm" />
          <span className="opacity-70">
            {t('setting.capabilities-detected', {
              defaultValue: 'matched from the model name',
            })}
          </span>
        </>
      ) : (
        <>
          <span className="rounded-md bg-ds-bg-neutral-subtle-default px-1.5 py-1 text-label-xs font-medium leading-none text-ds-text-neutral-subtle-default">
            {t('setting.capabilities-text-only', {
              defaultValue: 'Text only',
            })}
          </span>
          <span className="opacity-70">
            {t('setting.capabilities-text-only-hint', {
              defaultValue: 'screenshots go through your vision model',
            })}
          </span>
        </>
      )}
    </div>
  );
}
