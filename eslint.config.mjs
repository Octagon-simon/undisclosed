// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

// Root ESLint flat config (ESLint 9). The repo had no lint for the Theia
// extension packages under packages/*, so a change there could not be checked
// locally or in CI. This covers their TypeScript sources only; agent-ui keeps
// its own config (it needs the React plugins) and brain is linted with ruff.
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default [
  {
    // Compiled output, generated code, and anything owned by a nested toolchain.
    ignores: [
      '**/lib/**',
      '**/node_modules/**',
      'src-gen/**',
      '**/*.d.ts',
      'apps/**',
      'agent-ui/**',
      'brain/**',
      // Local scratch/debug scripts (already gitignored).
      '.tmp/**',
      'resources/**',
      'plugins/**',
      'site/**',
      // The committed agent-embed bundle (built from agent-ui) and the
      // generated language definitions are machine output, not source.
      'packages/*/assets/**',
      'packages/undisclosed-languages/src/generated/**',
      '**/script/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['packages/**/*.ts'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.node },
    },
    rules: {
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
    },
  },
  {
    // Repo scripts run under Node (process, console, ...).
    files: ['scripts/**/*.mjs', 'scripts/**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.node },
    },
  },
];
