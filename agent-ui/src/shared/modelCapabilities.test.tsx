// @vitest-environment jsdom
// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? _key,
  }),
}));

vi.mock('@/api/http', () => ({
  proxyFetchGet: vi.fn(async () => ({ capabilities: ['vision', 'thinking'] })),
}));

import { ModelCapabilityPreview } from './ModelCapabilityPreview';
import { ModelCapabilityTags } from './ModelCapabilityTags';

afterEach(cleanup);

describe('model capability styling', () => {
  // Both components previously passed a text size and a text color through
  // `cn`; tailwind-merge treated them as one group and dropped one class.
  it('keeps the size and the color class on a tag', () => {
    render(<ModelCapabilityTags capabilities={['vision']} size="sm" />);
    const tag = screen.getByLabelText(/Accepts images/);
    expect(tag.className).toContain('text-label-xs');
    expect(tag.className).toContain('text-ds-text-neutral-subtle-default');
  });

  it('renders the preview row at the label size', async () => {
    render(
      <ModelCapabilityPreview
        providerName="deepseek"
        modelType="deepseek-v4-flash-vision-exp"
      />
    );
    const hint = await screen.findByText('matched from the model name');
    const row = hint.parentElement as HTMLElement;
    expect(row.className).toContain('text-label-xs');
    expect(row.className).toContain('text-ds-text-neutral-muted-default');
  });
});
