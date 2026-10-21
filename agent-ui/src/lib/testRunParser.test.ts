// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import type { ActivityItem } from '@/lib/activityClassifier';
import {
  isFullSuiteCommand,
  isTestCommand,
  latestTestRun,
  parseTestRun,
  testRunFromActivity,
} from '@/lib/testRunParser';

const PYTEST_VERBOSE = [
  '============================= test session starts ==============================',
  'collected 3 items',
  '',
  'test_app.py::test_shout PASSED                                            [ 33%]',
  'test_app.py::test_slugify_lowercases PASSED                               [ 66%]',
  'test_app.py::TestSlugify::test_empty_string FAILED                       [100%]',
  '',
  '=================================== FAILURES ===================================',
  '=========================== short test summary info ============================',
  'FAILED test_app.py::TestSlugify::test_empty_string - AssertionError',
  '========================= 2 passed, 1 failed in 0.04s ==========================',
].join('\n');

const PYTEST_DOTS = [
  '============================= test session starts ==============================',
  'collected 9 items',
  '',
  'test_app.py .........                                                    [100%]',
  '',
  '============================== 9 passed in 0.01s ==============================',
].join('\n');

describe('parseTestRun', () => {
  it('reads pytest -v rows, statuses, and duration', () => {
    const run = parseTestRun({
      command: '.venv/bin/python -m pytest -v test_app.py',
      output: PYTEST_VERBOSE,
    });

    expect(run).not.toBeNull();
    expect(run?.tests).toEqual([
      { name: 'test_shout', status: 'passed' },
      { name: 'test_slugify_lowercases', status: 'passed' },
      { name: 'TestSlugify › test_empty_string', status: 'failed' },
    ]);
    expect(run?.totals).toEqual({ passed: 2, failed: 1, skipped: 0 });
    expect(run?.duration).toBe('0.04s');
  });

  it('reads test files from pytest progress when it prints dots', () => {
    const run = parseTestRun({
      command: '.venv/bin/python -m pytest test_app.py',
      output: PYTEST_DOTS,
    });

    expect(run?.tests).toEqual([{ name: 'test_app.py', status: 'passed' }]);
    expect(run?.totals).toEqual({ passed: 9, failed: 0, skipped: 0 });
    expect(run?.duration).toBe('0.01s');
  });

  it('marks a pytest file failed when its progress line has failures', () => {
    const run = parseTestRun({
      command: '.venv/bin/python -m pytest',
      output: [
        'tests/test_calc.py ..F                                               [ 66%]',
        '',
        '===== 2 passed, 1 failed in 0.02s =====',
      ].join('\n'),
    });

    expect(run?.tests).toEqual([
      { name: 'tests/test_calc.py', status: 'failed' },
    ]);
    expect(run?.totals).toEqual({ passed: 2, failed: 1, skipped: 0 });
  });

  it('reads jest file verdicts', () => {
    const run = parseTestRun({
      command: 'npx jest --coverage',
      output: [
        'PASS src/lib/testRunParser.test.ts',
        'FAIL src/lib/legacy.test.ts',
        '',
        'Tests:       2 failed, 9 passed, 11 total',
      ].join('\n'),
    });

    expect(run?.tests).toEqual([
      { name: 'src/lib/testRunParser.test.ts', status: 'passed' },
      { name: 'src/lib/legacy.test.ts', status: 'failed' },
    ]);
    expect(run?.totals).toEqual({ passed: 9, failed: 2, skipped: 0 });
  });

  it('reads vitest marks', () => {
    const run = parseTestRun({
      command: 'npx vitest run',
      output: [
        ' ✓ CardForm / renders 5ms',
        ' ✓ CardForm / validates expiry 2ms',
        ' × CardForm / rejects past dates 3ms',
        '',
        ' Tests  1 failed | 2 passed (3)',
        ' Duration  1.42s',
      ].join('\n'),
    });

    expect(run?.tests).toEqual([
      { name: 'CardForm / renders', status: 'passed' },
      { name: 'CardForm / validates expiry', status: 'passed' },
      { name: 'CardForm / rejects past dates', status: 'failed' },
    ]);
    expect(run?.totals).toEqual({ passed: 2, failed: 1, skipped: 0 });
    expect(run?.duration).toBe('1.42s');
  });

  it('ignores commands that are not test runs', () => {
    expect(isTestCommand('git status')).toBe(false);
    expect(
      parseTestRun({ command: 'git status', output: 'nothing to commit' })
    ).toBeNull();
  });

  it('reads go test rows, including skips, and omits a missing duration', () => {
    const run = parseTestRun({
      command: 'go test ./internal/auth',
      output: [
        '--- PASS: TestLogin (0.00s)',
        '--- SKIP: TestSSO (0.00s)',
        '--- FAIL: TestLogout (0.00s)',
        'FAIL',
      ].join('\n'),
    });

    expect(run?.tests).toEqual([
      { name: 'TestLogin', status: 'passed' },
      { name: 'TestSSO', status: 'skipped' },
      { name: 'TestLogout', status: 'failed' },
    ]);
    expect(run?.duration).toBeUndefined();
  });
});

describe('testRunFromActivity', () => {
  const activity: ActivityItem = {
    id: 'shell-1',
    category: 'shell',
    verb: 'Ran',
    object: 'pytest test_app.py',
    running: false,
    input: '{"command": ".venv/bin/python -m pytest test_app.py"}',
    output: PYTEST_DOTS,
  };

  it('maps a shell activity to card props', () => {
    const run = testRunFromActivity(activity);
    expect(run?.command).toBe('.venv/bin/python -m pytest test_app.py');
    expect(run?.totals?.passed).toBe(9);
    expect(run?.tests).toEqual([{ name: 'test_app.py', status: 'passed' }]);
  });

  it('reads a coverage-toolkit run from its plan header', () => {
    const run = testRunFromActivity({
      id: 'tool-1',
      category: 'other',
      method: 'run_tests',
      verb: 'run tests',
      object: 'Test Runner Toolkit',
      running: false,
      input: '{"scope": "", "base": ""}',
      output: [
        'COVERAGE-GAP PLAN (read-only, no model, no lacuna CLI)',
        'Command:    npx vitest run --coverage',
        'Patch:      100.0% (4/4 changed executable lines)',
        '',
        'Suite output:',
        ' ✓ src/lib/card.test.ts (3 tests) 8ms',
        '',
        ' Tests  3 passed (3)',
      ].join('\n'),
    });

    expect(run?.command).toBe('npx vitest run --coverage');
    expect(run?.tests).toEqual([
      { name: 'src/lib/card.test.ts (3 tests)', status: 'passed' },
    ]);
    expect(run?.totals).toEqual({ passed: 3, failed: 0, skipped: 0 });
  });

  const edit: ActivityItem = {
    id: 'edit-1',
    category: 'edit',
    verb: 'Wrote',
    object: 'test_app.py',
    filePath: 'test_app.py',
    diff: { added: 12, removed: 0 },
    running: false,
    input: '',
    output: '',
  };

  it('returns the last verification run after the last edit', () => {
    const failed: ActivityItem = {
      ...activity,
      id: 'shell-2',
      input: '{"command": ".venv/bin/python -m pytest test_app.py"}',
      output: '1 failed, 8 passed in 0.03s',
    };
    expect(latestTestRun([edit, activity, failed])?.totals).toEqual({
      passed: 8,
      failed: 1,
      skipped: 0,
    });
  });

  it('stays hidden on a turn that never edited code or tests', () => {
    expect(latestTestRun([activity])).toBeNull();
  });

  it('can be asked for the run without the edit gate', () => {
    expect(latestTestRun([activity], { requireEdit: false })?.totals).toEqual({
      passed: 9,
      failed: 0,
      skipped: 0,
    });
  });

  it('ignores runs from before the last edit', () => {
    const editAfter = { ...edit, id: 'edit-2' };
    expect(latestTestRun([edit, activity, editAfter])).toBeNull();
  });

  it('shows the scoped run for a turn that touched several files', () => {
    const createdTest: ActivityItem = {
      ...edit,
      id: 'edit-2',
      object: 'test_slugify.py',
      filePath: 'tests/test_slugify.py',
    };
    const sourceEdit = { ...edit, id: 'edit-3', filePath: 'app/slugify.py' };
    const scoped = {
      ...activity,
      id: 'shell-3',
      input:
        '{"command": ".venv/bin/python -m pytest tests/test_slugify.py test_app.py"}',
    };

    expect(latestTestRun([createdTest, sourceEdit, scoped])?.command).toContain(
      'tests/test_slugify.py'
    );
  });

  it('stays hidden when the turn only ran the full suite', () => {
    const fullSuite = {
      ...activity,
      id: 'shell-4',
      input: '{"command": ".venv/bin/python -m pytest"}',
      output: '412 passed in 8.20s',
    };
    expect(latestTestRun([edit, fullSuite])).toBeNull();
  });

  it('keeps the coverage toolkit full-suite run as the receipt', () => {
    const toolkitRun: ActivityItem = {
      id: 'tool-2',
      category: 'other',
      method: 'run_tests',
      verb: 'run tests',
      object: 'Test Runner Toolkit',
      running: false,
      input: '{"scope": ""}',
      output: [
        'Command:    .venv/bin/python -m pytest --cov',
        '',
        'Suite output:',
        'tests/test_app.py ..                    [100%]',
        '2 passed in 0.01s',
      ].join('\n'),
    };

    expect(latestTestRun([edit, toolkitRun])?.tests).toEqual([
      { name: 'tests/test_app.py', status: 'passed' },
    ]);
  });

  it('prefers the scoped run over a later full-suite run', () => {
    const scoped = {
      ...activity,
      id: 'shell-5',
      input: '{"command": ".venv/bin/python -m pytest test_app.py"}',
      output: '9 passed in 0.01s',
    };
    const fullSuite = {
      ...activity,
      id: 'shell-6',
      input: '{"command": ".venv/bin/python -m pytest"}',
      output: '412 passed in 8.20s',
    };
    expect(latestTestRun([edit, scoped, fullSuite])?.totals?.passed).toBe(9);
  });
});

describe('isFullSuiteCommand', () => {
  it('treats bare runner invocations as the whole suite', () => {
    for (const command of [
      'pytest',
      '.venv/bin/python -m pytest -v',
      'npm test',
      'npx vitest run --coverage',
      'go test ./...',
      'cargo test --quiet',
    ]) {
      expect(isFullSuiteCommand(command)).toBe(true);
    }
  });

  it('treats named targets and filters as scoped', () => {
    for (const command of [
      '.venv/bin/python -m pytest test_app.py',
      'pytest tests/test_login_input.py',
      'pytest -k login',
      'npm test -- src/components/Login.test.tsx',
      'npx vitest run src/lib/testRunParser.test.ts',
      'go test ./internal/auth',
      'cargo test slugify',
    ]) {
      expect(isFullSuiteCommand(command)).toBe(false);
    }
  });

  it('does not mistake a flag value for a target', () => {
    expect(isFullSuiteCommand('pytest --maxfail 1')).toBe(true);
    expect(isFullSuiteCommand('pytest --maxfail 1 tests/test_app.py')).toBe(
      false
    );
  });

  it('does not classify non-test commands as suites', () => {
    expect(isFullSuiteCommand('git status')).toBe(false);
  });
});
