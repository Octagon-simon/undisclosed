// @vitest-environment jsdom
// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AgentMessageCard } from './AgentMessageCard';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/store/feedbackStore', () => {
  const store = { map: {}, setRating: vi.fn(), hydrate: vi.fn() };
  const useFeedbackStore = (selector: (state: typeof store) => unknown) =>
    selector(store);
  useFeedbackStore.getState = () => store;
  return { useFeedbackStore };
});

afterEach(cleanup);

const RATE_LIMIT = `❌ **Error**: Error code: 429 - {"error": {"message": "Rate limit reached for gpt-4o on tokens per min.", "code": "rate_limit_exceeded"}}`;
const CONTEXT = `❌ **Error**: Error code: 400 - {"error": {"message": "This model's maximum context length is 128000 tokens.", "code": "context_length_exceeded"}}`;

describe('AgentMessageCard error retry', () => {
  it('offers Try again on a transient error and resends the turn', () => {
    const onRetry = vi.fn();
    render(
      <AgentMessageCard
        id="m1"
        content={RATE_LIMIT}
        typewriter={false}
        onRetry={onRetry}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('hides Try again when resending cannot help', () => {
    render(
      <AgentMessageCard
        id="m2"
        content={CONTEXT}
        typewriter={false}
        onRetry={vi.fn()}
      />
    );

    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
  });

  it('shows no retry control when the caller passes no handler', () => {
    render(<AgentMessageCard id="m3" content={RATE_LIMIT} typewriter={false} />);

    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
  });
});
