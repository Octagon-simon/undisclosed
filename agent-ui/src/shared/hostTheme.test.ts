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

import { describe, expect, it } from 'vitest';
import { resolveEffectiveAppearance } from './hostTheme';

describe('resolveEffectiveAppearance', () => {
  it('lets a known host theme win over the stored appearance', () => {
    // The whole bug: a dark editor with a light stored appearance used to ship
    // dark-fill logos because nothing consulted the surface actually rendered.
    expect(resolveEffectiveAppearance('light', 'light', false, 'dark')).toBe(
      'dark'
    );
    expect(resolveEffectiveAppearance('dark', 'dark', true, 'light')).toBe(
      'light'
    );
  });

  it('folds the OS preference in for appearanceMode=system', () => {
    expect(resolveEffectiveAppearance('light', 'system', true, null)).toBe(
      'dark'
    );
    expect(resolveEffectiveAppearance('dark', 'system', false, null)).toBe(
      'light'
    );
  });

  it('falls back to the resolved appearance when there is no host theme', () => {
    expect(resolveEffectiveAppearance('dark', 'dark', false, null)).toBe('dark');
    expect(resolveEffectiveAppearance('light', 'light', true, null)).toBe(
      'light'
    );
  });

  it('treats a missing appearance as the OS preference', () => {
    expect(resolveEffectiveAppearance(undefined, undefined, true, null)).toBe(
      'dark'
    );
    expect(resolveEffectiveAppearance(undefined, undefined, false, null)).toBe(
      'light'
    );
  });
});
