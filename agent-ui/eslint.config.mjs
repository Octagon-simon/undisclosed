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
  prettier,
];
