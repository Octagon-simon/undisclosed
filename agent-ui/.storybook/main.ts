// Copyright (c) 2026 Simon Ugorji

import type { StorybookConfig } from '@storybook/react-vite';
import path from 'path';

/**
 * Storybook config for agent-ui. The app's own `vite.config.ts` pulls in
 * `vite-plugin-electron` (it builds the Electron main/preload); Storybook is a
 * plain web app and must NOT run that, so `viteFinal` strips any electron
 * plugins and re-asserts the `@` -> src alias.
 */
const config: StorybookConfig = {
  stories: ['../src/**/*.stories.@(ts|tsx|js|jsx|mdx)'],
  addons: [
    '@storybook/addon-docs',
    '@storybook/addon-a11y',
    '@storybook/addon-themes',
  ],
  framework: { name: '@storybook/react-vite', options: {} },
  core: { disableTelemetry: true },
  async viteFinal(cfg) {
    // The `STORYBOOK` env (set by the npm scripts) makes vite.config.ts skip the
    // electron plugin, so here we only need to re-assert the `@` -> src alias.
    cfg.resolve = cfg.resolve || {};
    cfg.resolve.alias = {
      ...(cfg.resolve.alias || {}),
      '@': path.resolve(process.cwd(), 'src'),
    };
    return cfg;
  },
};

export default config;
