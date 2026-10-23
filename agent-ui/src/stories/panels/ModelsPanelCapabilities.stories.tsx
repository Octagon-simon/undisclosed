// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';
import { userEvent, waitFor, within } from 'storybook/test';

// Side-effect import: the panel uses `useTranslation`.
import '@/i18n';

import AgentModels from '@/components/CodeAgentWorkspace/AgentModels';
import { setConnectionConfig } from '@/store/connectionStore';

/**
 * Design-review story for the models screen rendered inside the agent panel
 * (`AgentEmbedPanel` -> `body === 'models'` -> `AgentModels`).
 *
 * This is the panel-native screen, not the desktop `SettingModels` page. The
 * only stand-in is the brain: `/api/v1/providers/capabilities` is stubbed with
 * the same marker rules `brain/app/utils/model_capabilities.py` uses, because
 * Storybook has no brain to ask. In the app that request is real, so the tags
 * shown here are the tags the agent acts on.
 */

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });

// Mirrors the brain's conservative marker lists closely enough for review.
function capabilitiesFor(model: string): string[] {
  const id = model.toLowerCase();
  const tags: string[] = [];
  if (
    /(vision|-vl|gpt-4o|gpt-4\.1|gpt-5|claude|gemini|llava|pixtral)/.test(id)
  ) {
    tags.push('vision');
  }
  if (/(thinking|reasoner|-r1|v4-flash|sonnet-4|opus-4|claude-3-7)/.test(id)) {
    tags.push('thinking');
  }
  return tags;
}

const savedRows = [
  {
    id: 1,
    provider_name: 'deepseek',
    model_type: 'deepseek-v4-flash-vision-exp',
    prefer: true,
    capabilities: ['vision', 'thinking'],
  },
  {
    id: 2,
    provider_name: 'deepseek',
    model_type: 'deepseek-chat',
    capabilities: [],
  },
];

function stubBrain(rows: unknown[] = []) {
  const original = window.fetch;
  window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url;
    if (url.includes('/api/v1/providers/capabilities')) {
      const parsed = new URL(url, 'http://storybook.local');
      return json({
        capabilities: capabilitiesFor(
          parsed.searchParams.get('model_type') ?? ''
        ),
      });
    }
    if (url.includes('/api/v1/providers')) return json(rows);
    return original(input, init);
  }) as typeof window.fetch;
}

const meta = {
  title: 'Panels/Agent models capabilities',
  component: AgentModels,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      // Matches the agent panel's width so truncation and tag wrapping are
      // judged at the size they ship in, not on a wide canvas.
      <div className="flex min-h-screen items-center justify-center bg-ds-bg-neutral-muted-default p-6">
        <div className="flex h-[620px] w-[380px] flex-col overflow-hidden rounded-xl bg-ds-bg-neutral-subtle-default shadow-lg">
          <Story />
        </div>
      </div>
    ),
  ],
  beforeEach: () => {
    // Outside dev builds `http.ts` refuses to build a request URL without
    // VITE_BASE_URL/VITE_PROXY_URL, so give it a base the fetch stub intercepts.
    setConnectionConfig({ proxyEndpoint: 'http://storybook.local' });
    stubBrain();
  },
} satisfies Meta<typeof AgentModels>;

export default meta;
type Story = StoryObj<typeof meta>;

async function openDeepSeekForm(modelId: string): Promise<void> {
  const canvas = within(document.body);
  await userEvent.click(
    await canvas.findByRole('button', { name: /add model/i })
  );
  await userEvent.selectOptions(
    await canvas.findByLabelText('Provider'),
    'deepseek'
  );
  await userEvent.type(canvas.getByLabelText('Model name'), modelId, {
    delay: 1,
  });

  // Let the 300ms debounce fire and the stubbed brain answer.
  await waitFor(
    () => {
      const row = document.querySelector('[aria-live="polite"]');
      if (!row || /Checking/.test(row.textContent ?? '')) {
        throw new Error('capabilities not resolved yet');
      }
    },
    { timeout: 4000 }
  );
}

/** Vision + thinking model: both tags under the model field. */
export const AddVisionModel: Story = {
  play: () => openDeepSeekForm('deepseek-v4-flash-vision-exp'),
};

/** Same form pinned to dark, so both themes can be reviewed side by side. */
export const AddVisionModelDark: Story = {
  globals: { theme: 'Dark' },
  play: () => openDeepSeekForm('deepseek-v4-flash-vision-exp'),
};

/** Text-only model: the preview says where screenshots go instead. */
export const AddTextOnlyModel: Story = {
  play: () => openDeepSeekForm('deepseek-chat'),
};

/** Saved rows: the same tags, read from the annotated `/providers` list. */
export const SavedModels: Story = {
  beforeEach: () => stubBrain(savedRows),
};
