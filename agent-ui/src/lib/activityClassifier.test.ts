// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import type { ToolItem } from '@/components/ChatBox/MessageItem/workLogTimeline';
import {
  classifyToolItem,
  formatActivitySummary,
  type ActivityItem,
} from './activityClassifier';

function tool(
  method: string,
  status: 'running' | 'done',
  input = '{}'
): ToolItem {
  return {
    kind: 'tool',
    id: `t-${method}-${status}`,
    rowTitle: '',
    toolkitName: 'memory_toolkit',
    method,
    detail: '',
    input,
    output: '',
    status,
  };
}

describe('memory activity labels', () => {
  it('uses Writing/Written to memory for remember_fact', () => {
    expect(classifyToolItem(tool('remember_fact', 'running')).verb).toBe(
      'Writing to memory'
    );
    expect(classifyToolItem(tool('remember_fact', 'done')).verb).toBe(
      'Written to memory'
    );
  });

  it('uses Recalling/Recalled from memory for recall tools', () => {
    expect(classifyToolItem(tool('recall_facts', 'running')).verb).toBe(
      'Recalling from memory'
    );
    expect(classifyToolItem(tool('recall_conversation', 'done')).verb).toBe(
      'Recalled from memory'
    );
  });

  it('does not let narration override the memory label', () => {
    const input = JSON.stringify({
      message_title: 'Reading file',
      fact: 'the license rule',
    });
    expect(classifyToolItem(tool('remember_fact', 'running', input)).verb).toBe(
      'Writing to memory'
    );
  });

  it('summarizes memory activity as memory writes', () => {
    const items: ActivityItem[] = [
      classifyToolItem(tool('remember_fact', 'done')),
      classifyToolItem(tool('recall_facts', 'done')),
    ];
    expect(formatActivitySummary(items)).toBe('2 memory writes');
  });
});
