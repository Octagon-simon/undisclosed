// Copyright (c) 2026 Simon Ugorji

import type { Preview } from '@storybook/react-vite';
// Global styles: design tokens + Tailwind base/components/utilities.
import '../src/style/index.css';

const preview: Preview = {
  parameters: {
    controls: {
      matchers: { color: /(background|color)$/i, date: /Date$/i },
    },
    backgrounds: {
      default: 'app',
      values: [
        { name: 'app', value: '#0b0b0d' },
        { name: 'light', value: '#ffffff' },
      ],
    },
  },
};

export default preview;
