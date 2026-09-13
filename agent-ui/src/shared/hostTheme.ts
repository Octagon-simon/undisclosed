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
 * The theme actually on screen, as a plain string.
 *
 * There are two independent things called "dark":
 *
 *  - The **editor / app theme** (embedded only): Theia's active color theme. The
 *    side panel is themed by `theme.css`, which remaps every `--ds-*` token to
 *    Theia's `--theia-*` vars. Nothing in the panel's own React/store path knows
 *    about it, which is why a dark editor with a light `appearance` still
 *    shipped light-mode logos (the OpenAI mark on a dark surface).
 *  - The **panel's own appearance** (`appearanceMode` in `authStore`, set from
 *    Settings → Appearance): `'light' | 'dark' | 'system'`.
 *
 * `useHost().getTheme` is the tiebreaker when there's more than one "dark" and
 * they disagree — the embed host (Theia) IS the surface the panel renders on.
 * Standalone/desktop mounts have no host theme, so they fall back to the store
 * exactly as before: `appearance` (the resolved mode ThemeProvider writes back)
 * with the OS `prefers-color-scheme` folded in for the `'system'` case.
 */

import { useHost } from '@/host/context';
import { useEffect, useState } from 'react';

/** Matches a theme's `getTheme().type === 'dark'` (the kind Theia exposes). */
export type HostThemeKind = 'light' | 'dark';

export function resolveEffectiveAppearance(
  appearance: string | undefined,
  appearanceMode: string | undefined,
  systemDark: boolean,
  hostThemeKind?: HostThemeKind | null
): string {
  // The host theme wins when it is known: the panel is being rendered INSIDE
  // something that has already decided the surface color, and mapping `--ds-*`
  // to its `--theia-*` vars means the panel follows it whatever we think.
  if (hostThemeKind) return hostThemeKind;
  if (appearanceMode === 'system') return systemDark ? 'dark' : 'light';
  return appearance ?? (systemDark ? 'dark' : 'light');
}

/** OS-level `prefers-color-scheme`, subscribed so an OS flip re-renders. */
export function useSystemDark(): boolean {
  const [systemDark, setSystemDark] = useState(() =>
    typeof window === 'undefined'
      ? false
      : window.matchMedia('(prefers-color-scheme: dark)').matches
  );

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => setSystemDark(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  return systemDark;
}

/** Host theme, subscribed so a live theme switch re-renders the consumer. */
export function useHostThemeKind(): HostThemeKind | null {
  const host = useHost();
  const [kind, setKind] = useState<HostThemeKind | null>(
    () => (host?.getTheme?.().type as HostThemeKind | undefined) ?? null
  );

  useEffect(() => {
    if (!host?.getTheme) return;
    let cancelled = false;
    const update = () => {
      const type = host.getTheme?.().type;
      if (!cancelled) {
        setKind(type === 'dark' ? 'dark' : type === 'light' ? 'light' : null);
      }
    };
    update();
    // Both hosts that ship a theme expose the subscribe form (the Theia embed
    // wires `onThemeChanged` to ThemeService.onDidColorThemeChange). Without it
    // there is nothing to listen to, so a live editor-theme switch is a no-op
    // and we keep the snapshot taken above.
    const sub = host.onThemeChanged?.(() => update());
    return () => {
      cancelled = true;
      if (typeof sub === 'function') sub();
    };
  }, [host]);

  return kind;
}

/**
 * Convenience hook: the effective appearance for logo inversion and any other
 * "are we on a dark surface?" decision. `appearanceMode` is the stored mode
 * (`'light' | 'dark' | 'system'`); `appearance` is the resolved mode.
 */
export function useEffectiveAppearance(
  appearance: string | undefined,
  appearanceMode: string | undefined
): string {
  const systemDark = useSystemDark();
  const hostThemeKind = useHostThemeKind();
  return resolveEffectiveAppearance(
    appearance,
    appearanceMode,
    systemDark,
    hostThemeKind
  );
}
