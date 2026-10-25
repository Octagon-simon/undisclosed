// @vitest-environment jsdom
// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HostProvider } from '@/host';
import type { AppHost } from '@/host/types';
import { UserMessageRichContent } from './UserMessageRichContent';

afterEach(cleanup);

function host(overrides: Partial<AppHost> = {}): AppHost {
  return { electronAPI: null, ipcRenderer: null, ...overrides };
}

function renderWithHost(value: AppHost) {
  return render(
    <HostProvider host={value}>
      <UserMessageRichContent content="use {{frontend-design}}" />
    </HostProvider>
  );
}

const chip = () => screen.getByRole('button', { name: '#frontend-design' });

describe('UserMessageRichContent skill chip', () => {
  it('opens the skill through the host when there is no desktop bridge', () => {
    const openSkillFolder = vi.fn();
    renderWithHost(host({ openSkillFolder }));

    fireEvent.click(chip());

    expect(openSkillFolder).toHaveBeenCalledWith('frontend-design');
  });

  it('prefers the desktop bridge and does not call the host twice', () => {
    const desktop = vi.fn();
    const openSkillFolder = vi.fn();
    renderWithHost(
      host({ electronAPI: { openSkillFolder: desktop }, openSkillFolder })
    );

    fireEvent.click(chip());

    expect(desktop).toHaveBeenCalledWith('frontend-design');
    expect(openSkillFolder).not.toHaveBeenCalled();
  });

  it('does nothing when the host has no skill capability', () => {
    renderWithHost(host());
    expect(() => fireEvent.click(chip())).not.toThrow();
  });

  it('rejects a name that could escape the skills folder', () => {
    const openSkillFolder = vi.fn();
    render(
      <HostProvider host={host({ openSkillFolder })}>
        <UserMessageRichContent content="use {{../secrets}}" />
      </HostProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: '#../secrets' }));

    expect(openSkillFolder).not.toHaveBeenCalled();
  });
});
