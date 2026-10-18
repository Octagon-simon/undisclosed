// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

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
