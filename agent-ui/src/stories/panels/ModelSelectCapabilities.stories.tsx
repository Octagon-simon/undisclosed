// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';
import { MemoryRouter } from 'react-router-dom';

// Side-effect import: the picker uses `useTranslation`.
import '@/i18n';

import { ModelSelect } from '@/components/ChatBox/BottomBox/ModelSelect';
import { setConnectionConfig } from '@/store/connectionStore';

/**
 * Design-review story for the chat model picker with capability badges.
 *
 * The badges are not hardcoded here: `GET /api/v1/providers` annotates every
 * configured row with `capabilities`, derived in the brain from the same
 * checks the tools use (`model_supports_vision`, `model_supports_thinking`).
 * The story stubs that endpoint with rows shaped exactly like the real
 * response, so what you see is the real component rendering real data shape.
 *
 * Eye = vision, Brain = thinking. Both carry a tooltip with the full label.
 * The collapsed trigger shows the active row's icons too.
 *
 * Flip the toolbar sun/moon toggle to check both themes.
 */

const PROVIDERS = [
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
    model_type: 'deepseek-v4-flash',
    prefer: false,
    capabilities: ['thinking'],
  },
  {
    id: 3,
    provider_name: 'deepseek',
    model_type: 'deepseek-chat',
    prefer: false,
    capabilities: [],
  },
  {
    id: 4,
    provider_name: 'openai',
    model_type: 'gpt-4o',
    prefer: false,
    capabilities: ['vision'],
  },
  {
    id: 5,
    provider_name: 'anthropic',
    model_type: 'claude-sonnet-4-5',
    prefer: false,
    capabilities: ['vision', 'thinking'],
  },
  {
    id: 6,
    provider_name: 'ollama',
    model_type: 'llama-3.2-11b-vision',
    prefer: false,
    capabilities: ['vision'],
  },
];

function stubProviders() {
  const original = window.fetch;
  window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url;
    if (url.includes('/api/v1/providers')) {
      return new Response(JSON.stringify(PROVIDERS), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    return original(input, init);
  }) as typeof window.fetch;
}

const nextFrame = () =>
  new Promise((resolve) => requestAnimationFrame(() => resolve(null)));

const meta = {
  title: 'Panels/Model picker capabilities',
  component: ModelSelect,
  decorators: [
    (Story) => (
      // `ModelSelect` reads the router to jump to the Models page.
      <MemoryRouter>
        <div className="flex min-h-[420px] items-center justify-center bg-ds-bg-neutral-default-default p-10">
          <Story />
        </div>
      </MemoryRouter>
    ),
  ],
  beforeEach: () => {
    // Outside dev builds `http.ts` refuses to build a request URL without
    // VITE_BASE_URL/VITE_PROXY_URL, so give it a base the fetch stub intercepts.
    setConnectionConfig({ proxyEndpoint: 'http://storybook.local' });
    stubProviders();
  },
} satisfies Meta<typeof ModelSelect>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Closed trigger: active row = deepseek-v4-flash-vision-exp (both badges). */
export const Closed: Story = {};

async function openModelList(): Promise<void> {
  // Radix opens the menu on pointerdown, not click.
  const trigger = document.querySelector<HTMLButtonElement>(
    'button[aria-haspopup="menu"]'
  );
  if (!trigger) return;
  trigger.dispatchEvent(
    new PointerEvent('pointerdown', {
      bubbles: true,
      cancelable: true,
      button: 0,
      pointerType: 'mouse',
    })
  );

  await nextFrame();
  await nextFrame();

  // The menu is portaled to <body>, so query the document, not the canvas.
  const customModel = document.querySelector<HTMLElement>(
    '[role="menuitem"][aria-haspopup="menu"]'
  );
  if (!customModel) return;
  customModel.focus();
  // ArrowRight opens a submenu from the keyboard; this is Radix's own path.
  customModel.dispatchEvent(
    new KeyboardEvent('keydown', {
      key: 'ArrowRight',
      code: 'ArrowRight',
      bubbles: true,
      cancelable: true,
    })
  );

  await nextFrame();
  await nextFrame();
}

/** Menu open with the model list expanded, so every row's badges are visible. */
export const Open: Story = { play: openModelList };

/** Same as `Open`, pinned to dark so both themes can be reviewed side by side. */
export const Dark: Story = {
  // The addon keys themes by name ('Dark' -> data-theme='dark').
  globals: { theme: 'Dark' },
  play: openModelList,
};

/** Text-only providers only: no badge on the trigger or the rows. */
export const NoCapabilities: Story = {
  beforeEach: () => {
    setConnectionConfig({ proxyEndpoint: 'http://storybook.local' });
    const rows = PROVIDERS.map((row) => ({ ...row, capabilities: [] }));
    const original = window.fetch;
    window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.href
            : (input as Request).url;
      if (url.includes('/api/v1/providers')) {
        return new Response(JSON.stringify(rows), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      return original(input, init);
    }) as typeof window.fetch;
  },
};
