// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import {
  baseName,
  buildSelectionPrompt,
  formatLineRange,
  selectionLabel,
} from './selectionPrompt';

describe('selectionPrompt', () => {
  it('sorts a reverse selection ascending', () => {
    expect(formatLineRange(154, 111)).toBe('L111-154');
  });

  it('collapses a one-line range', () => {
    expect(formatLineRange(111, 111)).toBe('L111');
  });

  it('uses the file name in the label', () => {
    expect(
      selectionLabel({
        path: 'workspace/app.py',
        startLine: 16,
        endLine: 11,
      })
    ).toBe('app.py L11-16');
  });

  it('sends a path + line reference, not the code block', () => {
    expect(
      buildSelectionPrompt({
        path: 'workspace/app.py',
        startLine: 11,
        endLine: 16,
      })
    ).toBe('From workspace/app.py (lines 11-16):\n\n');
  });

  it('uses singular "line" for one line', () => {
    expect(
      buildSelectionPrompt({
        path: 'src/App.tsx',
        startLine: 7,
        endLine: 7,
      })
    ).toBe('From src/App.tsx (line 7):\n\n');
  });

  it('handles Windows separators', () => {
    expect(baseName('C:\\repo\\src\\App.tsx')).toBe('App.tsx');
  });
});
