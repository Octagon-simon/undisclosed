// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
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

import { getAuthStore, useAuthStore } from '@/store/authStore';
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { resources } from './locales';

export enum LocaleEnum {
  SimplifiedChinese = 'zh-Hans',
  TraditionalChinese = 'zh-Hant',
  English = 'en-US',
  German = 'de',
  Korean = 'ko',
  Japanese = 'ja',
  French = 'fr',
  Russian = 'ru',
  Italian = 'it',
  Arabic = 'ar',
  Spanish = 'es',
}

const availableLanguages = Object.values(LocaleEnum);

/**
 * Resolve a persisted/system value (case-insensitively) to a supported locale,
 * or null if none applies. `'system'` (the auth-store default) is treated as
 * "no explicit choice" and falls through to system detection.
 */
function resolveLocale(candidate?: string | null): LocaleEnum | null {
  const lower = candidate?.toLowerCase();
  if (!lower || lower === 'system') return null;
  return (
    availableLanguages.find((lang) => lang.toLowerCase() === lower) ?? null
  );
}

function detectInitialLanguage(): string {
  const saved = resolveLocale(getAuthStore().language);
  if (saved) return saved;
  const systemLanguage = navigator.language.toLowerCase();
  const matched = availableLanguages.find((lang) =>
    systemLanguage.startsWith(lang.toLowerCase())
  );
  return matched ?? LocaleEnum.English;
}

i18n.use(initReactI18next).init({
  resources,
  fallbackLng: LocaleEnum.English,
  lng: detectInitialLanguage(),
  interpolation: {
    escapeValue: false,
  },
});

// The auth-store persists the user's language, but its rehydration from
// localStorage can finish AFTER this module first read it (module-load order is
// not guaranteed). Without this, a persisted non-English language silently
// reverted to English/System on every launch — the panel stayed English even
// though Settings still showed the chosen language. Re-apply the persisted
// choice once hydration completes (and if it already has, apply immediately).
function applyPersistedLanguage() {
  const persisted = resolveLocale(getAuthStore().language);
  if (persisted && i18n.language !== persisted) {
    void i18n.changeLanguage(persisted);
  }
}
const authPersist = (
  useAuthStore as unknown as {
    persist?: {
      hasHydrated?: () => boolean;
      onFinishHydration?: (cb: () => void) => void;
    };
  }
).persist;
if (authPersist?.onFinishHydration) {
  authPersist.onFinishHydration(applyPersistedLanguage);
}
if (authPersist?.hasHydrated?.()) {
  applyPersistedLanguage();
}

export const switchLanguage = (lang: LocaleEnum) => {
  console.log('switchLanguage', lang);
  i18n.changeLanguage(lang);
  getAuthStore().setLanguage(lang);
};

export default i18n;
