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
 * Compact, panel-native settings for the embedded agent. v1 = language only (the
 * one desktop setting that matters in the editor-first embed — the rest are
 * desktop shell concerns). Reuses the app's existing i18n `switchLanguage`, which
 * changes the language AND persists it to authStore. Extensible: add future
 * panel-relevant preferences here.
 */

import { LocaleEnum, switchLanguage } from '@/i18n';
import { useTranslation } from 'react-i18next';

const LANGUAGES: { value: LocaleEnum; label: string }[] = [
  { value: LocaleEnum.English, label: 'English' },
  { value: LocaleEnum.SimplifiedChinese, label: '简体中文' },
  { value: LocaleEnum.TraditionalChinese, label: '繁體中文' },
  { value: LocaleEnum.German, label: 'Deutsch' },
  { value: LocaleEnum.French, label: 'Français' },
  { value: LocaleEnum.Spanish, label: 'Español' },
  { value: LocaleEnum.Italian, label: 'Italiano' },
  { value: LocaleEnum.Russian, label: 'Русский' },
  { value: LocaleEnum.Japanese, label: '日本語' },
  { value: LocaleEnum.Korean, label: '한국어' },
  { value: LocaleEnum.Arabic, label: 'العربية' },
];

export default function AgentSettings() {
  const { i18n } = useTranslation();
  const current = i18n.language;

  return (
    <div className="flex flex-col gap-4 px-3 py-2">
      <div className="text-body-sm font-semibold text-ds-text-neutral-default-default">
        Settings
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-label-xs text-ds-text-neutral-subtle-default">
          Language
        </span>
        <select
          value={current}
          onChange={(e) => switchLanguage(e.target.value as LocaleEnum)}
          className="rounded-md border border-solid border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-2 py-1.5 text-body-sm text-ds-text-neutral-default-default outline-none"
        >
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
        <span className="text-label-xs text-ds-text-neutral-subtle-default">
          Changes the agent panel's language immediately.
        </span>
      </label>
    </div>
  );
}
