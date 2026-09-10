// Copyright (c) 2026 Simon Ugorji

import { withThemeByDataAttribute } from '@storybook/addon-themes';
import type { Preview } from '@storybook/react-vite';
// Global styles: design tokens + Tailwind base/components/utilities.
import '../src/style/index.css';

import {
  applyThemeContractV2,
  createDefaultThemeContractV2,
} from '../src/lib/themeTokens';
import type { Mode } from '../src/lib/themeTokens/types';

const MODE_ATTR = 'data-theme';

/**
 * Applies ONLY the design-token contract (--ds-* vars + color-scheme) for a
 * mode onto <html>, mirroring what the real ThemeProvider does so stories
 * render with the same variables the app uses.
 *
 * IMPORTANT: this does NOT write the `data-theme` attribute. The theme observer
 * below reacts to `data-theme` changes; if this wrote `data-theme` it would
 * re-fire the observer, which would call this again → setAttribute → … an
 * infinite loop that pegged the main thread and froze the whole preview (no
 * clicks registered). The addon owns `data-theme`; we only emit the tokens.
 */
function applyTokens(mode: Mode) {
  const root = document.documentElement;
  root.style.setProperty('color-scheme', mode);
  applyThemeContractV2(createDefaultThemeContractV2(mode), root);
}

// @storybook/addon-themes flips `data-theme` on <html> when you click the
// toolbar (sun/moon) toggle. It only sets the attribute, so we watch for that
// and re-run the token engine every time to emit the --ds-* variables.
const themeObserver = new MutationObserver(() => {
  const current = document.documentElement.getAttribute(MODE_ATTR) as
    | Mode
    | null;
  if (current === 'light' || current === 'dark') {
    applyTokens(current);
  }
});

function setupThemeObserver(): void {
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: [MODE_ATTR],
  });
}

// The addon's decorator adds `data-theme='light'|'dark'` to <html> on first
// render. Set the initial attribute ONCE (before the addon runs) for a correct
// first frame, then apply tokens; the observer drives everything after.
if (typeof document !== 'undefined') {
  document.documentElement.setAttribute(MODE_ATTR, 'light');
  applyTokens('light');
  setupThemeObserver();
}

const preview: Preview = {
  decorators: [
    withThemeByDataAttribute({
      themes: {
        Light: 'light',
        Dark: 'dark',
      },
      defaultTheme: 'Light',
    }),
  ],
  parameters: {
    controls: {
      matchers: { color: /(background|color)$/i, date: /Date$/i },
    },
    // Neutral panel behind the canvas so screenshots/tooling aren't skewed.
    backgrounds: {
      default: 'Light app',
      values: [
        { name: 'Light app', value: '#faf7f6' },
        { name: 'Light', value: '#ffffff' },
        { name: 'Dark', value: '#0b0b0d' },
      ],
    },
  },
};

export default preview;
