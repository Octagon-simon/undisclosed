// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

// ESLint flat config (ESLint 9). The repo shipped the eslint deps and a
// `lint` script but no config, so `eslint .` died with "couldn't find an
// eslint.config.js". This wires the installed plugins into one flat config:
// @eslint/js recommended, typescript-eslint recommended, eslint-plugin-react
// (recommended + jsx-runtime) and react-hooks, then eslint-config-prettier
// last so formatting stays Prettier's job.
import js from '@eslint/js';
import globals from 'globals';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import reactPlugin from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import prettier from 'eslint-config-prettier';

// The desktop preload bridge is `null` inside the Theia panel and the web build,
// so a read on a panel path silently does nothing. src/ is therefore denied by
// default and only the legacy desktop-shell code below is exempt. Delete entries
// as those files move to `useHost()` (src/host/types.ts); do not add new ones.
const DESKTOP_SHELL_FILES = [
  'src/App.tsx',
  'src/api/http.ts',
  'src/client/platform.ts',
  'src/components/AddWorker/ToolSelect.tsx',
  'src/components/BrowserAgentWorkspace/index.tsx',
  'src/components/ChatBox/MessageItem/MarkDown.tsx',
  'src/components/ChatBox/MessageItem/UserMessageCard.tsx',
  'src/components/ChatBox/MessageItem/UserMessageRichContent.tsx',
  'src/components/ChatBox/TaskBox/TaskCard.tsx',
  'src/components/ChatBox/index.tsx',
  'src/components/CodeAgentWorkspace/index.tsx',
  'src/components/Dashboard/GroupedHistoryView/index.tsx',
  'src/components/Dialog/CloseNotice.tsx',
  'src/components/Dialog/ReportBugDialog.tsx',
  'src/components/Folder/FilePreview.tsx',
  'src/components/Folder/FolderComponent.tsx',
  'src/components/Folder/index.tsx',
  'src/components/HistorySidebar/index.tsx',
  'src/components/Layout/index.tsx',
  'src/components/ProjectPageSidebar/useProjectNavActions.tsx',
  'src/components/Session/PreviewPanel/index.tsx',
  'src/components/Session/PreviewPanel/tabs/browser/BrowserTab.tsx',
  'src/components/Session/PreviewPanel/tabs/browser/PreviewBrowserLayer.tsx',
  'src/components/Session/PreviewPanel/tabs/terminal/ShellTerminal.tsx',
  'src/components/Session/PreviewPanel/tabs/terminal/TerminalTab.tsx',
  'src/components/Session/SidePanelSections/useProjectOutputFiles.ts',
  'src/components/Session/Workforce/ExpandedOverlay.tsx',
  'src/components/Session/Workforce/FoldedPanel/AgentDetailPane.tsx',
  'src/components/Session/Workforce/FoldedPanel/index.tsx',
  'src/components/TerminalAgentWorkspace/index.tsx',
  'src/components/TopBar/UpdateButton.tsx',
  'src/components/TopBar/index.tsx',
  'src/components/WindowControls/index.tsx',
  'src/components/WorkFlow/node.tsx',
  'src/components/WorkforceMenu/index.tsx',
  'src/components/Workspace/index.tsx',
  'src/context/ConnectionContext.tsx',
  'src/hooks/use-app-version.tsx',
  'src/hooks/useInstallationSetup.ts',
  'src/hooks/useIntegrationManagement.ts',
  'src/hooks/useModelConfigCheck.ts',
  'src/lib/attachmentUrl.ts',
  'src/lib/createSpaceFromFolder.ts',
  'src/lib/fileUtils.ts',
  'src/lib/htmlSanitization.ts',
  'src/lib/index.ts',
  'src/lib/oauth.ts',
  'src/lib/shellSessions.ts',
  'src/pages/Browser/CDP.tsx',
  'src/pages/Browser/Cookies.tsx',
  'src/pages/Home/hooks/useHomeHubProjects.ts',
  'src/pages/Setting/General.tsx',
  'src/pages/Setting/index.tsx',
  'src/pages/Workspace.tsx',
  'src/store/chatStore.ts',
  'src/store/connectionStore.ts',
  'src/store/installationStore.ts',
  'src/store/pageTabStore.ts',
];

const BRIDGE_MESSAGE =
  'The desktop preload bridge is null in the panel and the web build, so this ' +
  'read silently does nothing. Use useHost() (src/host/types.ts) instead.';

const preloadBridgeRule = {
  'no-restricted-syntax': [
    'error',
    { selector: 'MemberExpression[property.name=/^(electronAPI|ipcRenderer)$/]', message: BRIDGE_MESSAGE },
    { selector: 'MemberExpression[object.name=/^(electronAPI|ipcRenderer)$/]', message: BRIDGE_MESSAGE },
    {
      selector: 'MemberExpression[computed=true][property.value=/^(electronAPI|ipcRenderer)$/]',
      message: BRIDGE_MESSAGE,
    },
    {
      selector: 'ObjectPattern > Property[key.name=/^(electronAPI|ipcRenderer)$/]',
      message: BRIDGE_MESSAGE,
    },
  ],
};

export default [
  {
    // Build output and generated artifacts, never linted.
    ignores: [
      'node_modules/**',
      'dist/**',
      'dist-agent-embed/**',
      'dist-web/**',
      'storybook-static/**',
      'test-results/**',
      'playwright-report/**',
      '**/*.d.ts',
    ],
  },
  js.configs.recommended,
  ...tsPlugin.configs['flat/recommended'],
  reactPlugin.configs.flat.recommended,
  reactPlugin.configs.flat['jsx-runtime'],
  reactHooks.configs.flat.recommended,
  {
    files: ['**/*.{ts,tsx,js,jsx,mjs,cjs}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
    },
    settings: { react: { version: 'detect' } },
    rules: {
      // TS code, so runtime prop-types are redundant.
      'react/prop-types': 'off',
      // `any` is reviewed, not banned outright.
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      // The newest react-hooks compiler rules (v7) are stricter than this
      // codebase, which predates them. Keep them visible as warnings so they
      // do not fail CI, but surface real regressions.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/set-state-in-render': 'warn',
      'react-hooks/refs': 'warn',
      'react-hooks/purity': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/static-components': 'warn',
      'react-hooks/preserve-manual-memoization': 'warn',
      'react-hooks/use-memo': 'warn',
      'react-hooks/error-boundaries': 'warn',
      'react-hooks/globals': 'warn',
      'react-hooks/config': 'warn',
      'react-hooks/gating': 'warn',
    },
  },
  {
    // Tests simulate the bridge, and src/host/ is the seam that owns it.
    files: ['src/**/*.{ts,tsx,js,jsx}'],
    ignores: ['src/host/**', '**/*.test.{ts,tsx}', '**/*.spec.{ts,tsx}', ...DESKTOP_SHELL_FILES],
    rules: preloadBridgeRule,
  },
  prettier,
];
