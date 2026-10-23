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
 * Capability tags for a configured model row.
 *
 * The tags come from the brain (`GET /api/v1/providers` annotates each row with
 * `capabilities`), never from a hardcoded list here: the same functions decide
 * whether iris attaches images or routes them through the vision model, so the
 * badge cannot drift from what the app actually does.
 */

import { cn } from '@/lib/utils';
import { Brain, Eye } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export type ModelCapability = 'vision' | 'thinking';

const CAPABILITY_META: Record<
  ModelCapability,
  { icon: typeof Eye; labelKey: string; fallback: string; hintKey: string; hint: string }
> = {
  vision: {
    icon: Eye,
    labelKey: 'setting.capability-vision',
    fallback: 'Vision',
    hintKey: 'setting.capability-vision-hint',
    hint: 'Accepts images: screenshots are attached directly',
  },
  thinking: {
    icon: Brain,
    labelKey: 'setting.capability-thinking',
    fallback: 'Thinking',
    hintKey: 'setting.capability-thinking-hint',
    hint: 'Emits reasoning that streams in the thinking block',
  },
};

export function isModelCapability(value: string): value is ModelCapability {
  return value === 'vision' || value === 'thinking';
}

export interface ModelCapabilityTagsProps {
  capabilities?: readonly string[] | null;
  /**
   * `icon` for narrow menus (the label lives in the tooltip), `label` where
   * there is room to spell it out.
   */
  variant?: 'icon' | 'label';
  className?: string;
}

export function ModelCapabilityTags({
  capabilities,
  variant = 'label',
  className,
}: ModelCapabilityTagsProps) {
  const { t } = useTranslation();
  const tags = (capabilities ?? []).filter(isModelCapability);
  if (tags.length === 0) return null;

  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1', className)}>
      {tags.map((tag) => {
        const meta = CAPABILITY_META[tag];
        const Icon = meta.icon;
        const hint = t(meta.hintKey, { defaultValue: meta.hint });
        const label = t(meta.labelKey, { defaultValue: meta.fallback });
        return (
          <span
            key={tag}
            title={`${label}: ${hint}`}
            aria-label={hint}
            className={cn(
              'inline-flex items-center rounded-md bg-ds-bg-neutral-subtle-default text-[10px] font-medium leading-none text-ds-text-neutral-subtle-default',
              variant === 'icon' ? 'p-0.5' : 'gap-0.5 px-1 py-0.5'
            )}
          >
            <Icon className="h-2.5 w-2.5" aria-hidden />
            {variant === 'label' && label}
          </span>
        );
      })}
    </span>
  );
}
