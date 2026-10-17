// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { describe, expect, it } from 'vitest';
import { parseFlag } from './featureFlags';

describe('parseFlag', () => {
  it.each(['true', 'TRUE', ' 1 ', 'on', 'On'])('enables for %j', (value) => {
    expect(parseFlag(value)).toBe(true);
  });

  it.each(['off', 'false', '0', '', 'no', undefined, null, 1, true])(
    'stays disabled for %j',
    (value) => {
      expect(parseFlag(value)).toBe(false);
    }
  );
});
