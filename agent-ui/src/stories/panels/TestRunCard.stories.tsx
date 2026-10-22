// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';

import { TestRunCard } from '@/components/ChatBox/MessageItem/TestRunCard';
import type { TestCase } from '@/components/ChatBox/MessageItem/TestRunCard';
import type { ActivityItem } from '@/lib/activityClassifier';
import { testRunFromActivity } from '@/lib/testRunParser';

/**
 * The test-run receipt from the demo, now a live component.
 *
 * **Where it belongs.** The shell tool activity is already in the turn's
 * `ActivityItem[]` (category `shell`, with the command and its output).
 * `latestTestRun` in `@/lib/testRunParser` maps the last test command to these
 * props, and `UserQueryGroup` mounts the card as a sibling of the Execution
 * Summary, so folding the activity log never hides the verdict.
 * `ParsedFromActivity` below is that path end to end.
 *
 * **Why the rows, not just the total.** The nine rows are the evidence: they
 * show the agent wrote a test per behaviour, not that it printed "9 passed".
 * Default pytest output is dots only, so `SummaryOnly` shows the honest
 * fallback: totals without invented names.
 *
 * The header is the disclosure toggle. Folded, it keeps the verdict and
 * duration; the panel folds it by default so the answer stays above the fold.
 * Flip the toolbar sun/moon toggle to check both themes.
 */
const meta: Meta<typeof TestRunCard> = {
  title: 'ChatBox/TestRunCard',
  component: TestRunCard,
  parameters: { layout: 'centered' },
  decorators: [
    (Story) => (
      <div className="w-[600px] bg-ds-bg-neutral-subtle-default p-6">
        <Story />
      </div>
    ),
  ],
  argTypes: {
    animate: { control: 'boolean' },
    running: { control: 'boolean' },
    defaultOpen: { control: 'boolean' },
  },
  tags: ['autodocs'],
};

export default meta;

type Story = StoryObj<typeof TestRunCard>;

/** The real tests the agent wrote in the captured run, in file order. */
const CAPTURED_TESTS: TestCase[] = [
  { name: 'test_shout', status: 'passed' },
  { name: 'test_slugify_lowercases', status: 'passed' },
  { name: 'test_slugify_replaces_spaces_with_hyphens', status: 'passed' },
  { name: 'test_slugify_strips_punctuation', status: 'passed' },
  { name: 'test_slugify_collapses_whitespace_runs', status: 'passed' },
  { name: 'test_slugify_trims_leading_and_trailing_hyphens', status: 'passed' },
  { name: 'test_slugify_mixed_punctuation', status: 'passed' },
  { name: 'test_slugify_normalizes_underscores', status: 'passed' },
  { name: 'test_slugify_empty_string', status: 'passed' },
];

const COMMAND = '.venv/bin/python -m pytest test_app.py';

/** The demo's beat 08: nine checks land in sequence, then the verdict. */
export const Passed: Story = {
  args: {
    command: COMMAND,
    tests: CAPTURED_TESTS,
    duration: '0.01s',
    provenance: 'PYTEST OUTPUT FROM THE CAPTURED RUN',
    animate: true,
  },
};

/** The same run at rest, for screenshots and the docs page. */
export const Settled: Story = {
  args: {
    command: COMMAND,
    tests: CAPTURED_TESTS,
    duration: '0.01s',
    provenance: 'PYTEST OUTPUT FROM THE CAPTURED RUN',
  },
};

/** In flight: the caret blinks, the footer counts what has landed so far. */
export const Running: Story = {
  args: {
    command: COMMAND,
    tests: [
      ...CAPTURED_TESTS.slice(0, 4).map((t): TestCase => ({
        ...t,
        status: 'passed',
      })),
      ...CAPTURED_TESTS.slice(4).map((t): TestCase => ({
        ...t,
        status: 'pending',
      })),
    ],
    running: true,
    animate: true,
  },
};

/** A red row and a red verdict: the failure count leads, not the pass count. */
export const OneFailing: Story = {
  args: {
    command: COMMAND,
    tests: CAPTURED_TESTS.map((t, i): TestCase =>
      i === 6 ? { ...t, status: 'failed' } : t
    ),
    duration: '0.03s',
    provenance: 'PYTEST OUTPUT FROM THE CAPTURED RUN',
  },
};

/** Skipped tests keep their row (the coverage gap is visible) but strike through. */
export const WithSkipped: Story = {
  args: {
    command: 'npm test -- --run',
    tests: [
      { name: 'CardForm / renders', status: 'passed' },
      { name: 'CardForm / validates expiry', status: 'passed' },
      { name: 'CardForm / rejects past dates', status: 'skipped' },
      { name: 'CardForm / submits', status: 'passed' },
    ],
    duration: '1.42s',
  },
};

/** One test, no provenance: the smallest useful shape. */
export const SingleTest: Story = {
  args: {
    command: 'go test ./internal/...',
    tests: [{ name: 'TestSlugify', status: 'passed' }],
    duration: '0.12s',
  },
};

/** Folded: the header keeps the verdict and duration so the receipt still reads. */
export const Collapsed: Story = {
  args: {
    command: COMMAND,
    tests: CAPTURED_TESTS,
    duration: '0.01s',
    provenance: 'PYTEST OUTPUT FROM THE CAPTURED RUN',
    defaultOpen: false,
  },
};

/**
 * The real-world long command (a scoped vitest run with coverage). The header
 * truncates it, `title` shows the full string on hover, and the copy button is
 * the way to take it elsewhere without retyping.
 */
export const LongCommand: Story = {
  args: {
    command:
      "cd packages/admin && npx vitest run src/components/CountBadge/__tests__/index.test.tsx --coverage --coverage.include='src/components/CountBadge/**' 2>&1 | tail -20",
    tests: [
      { name: 'renders the count', status: 'passed' },
      { name: 'hides at zero', status: 'passed' },
      { name: 'hides below zero', status: 'passed' },
      { name: 'caps above max', status: 'passed' },
      { name: 'keeps the exact max', status: 'passed' },
      { name: 'accepts a custom max', status: 'passed' },
      { name: 'labels the badge by default', status: 'passed' },
      { name: 'accepts a custom label', status: 'passed' },
    ],
    duration: '0.71s',
  },
};

/**
 * The shape a real default pytest run produces: dots, no per-test names. The
 * card falls back to the summary totals instead of inventing rows.
 */
export const SummaryOnly: Story = {
  args: {
    command: COMMAND,
    tests: [],
    totals: { passed: 9, failed: 0, skipped: 0 },
    duration: '0.01s',
    provenance: 'PYTEST OUTPUT FROM THE CAPTURED RUN',
  },
};

/** Twenty rows: the roster caps and scrolls, the verdict stays fixed below. */
export const LongRun: Story = {
  args: {
    command: '.venv/bin/python -m pytest -v test_app.py',
    tests: Array.from({ length: 20 }, (_, i): TestCase => ({
      name: `test_slugify_case_${String(i + 1).padStart(2, '0')}`,
      status: i === 17 ? 'failed' : 'passed',
    })),
    duration: '0.08s',
    provenance: 'PYTEST OUTPUT FROM THE CAPTURED RUN',
  },
};

/** Vitest's per-file roster above the individual tests. */
export const VitestFiles: Story = {
  args: {
    command: 'npx vitest run src/lib',
    files: [
      {
        path: 'src/lib/card.test.ts',
        status: 'passed',
        passed: 3,
        failed: 0,
        duration: '23ms',
      },
      {
        path: 'src/lib/legacy.spec.ts',
        status: 'failed',
        passed: 1,
        failed: 1,
        duration: '45ms',
      },
      { path: 'src/lib/skip.spec.ts', status: 'skipped', skipped: 2 },
    ],
    tests: [],
    totals: { passed: 4, failed: 1, skipped: 2 },
    duration: '1.42s',
    provenance: 'VITEST OUTPUT FROM THE CAPTURED RUN',
  },
};

/**
 * Deep monorepo paths: the head is elided and the file name stays legible,
 * which end-truncation would have eaten.
 */
export const LongFilePaths: Story = {
  args: {
    command:
      'cd packages/business-web && npx vitest run src/screens/SignupWizard/steps/__tests__/DateOfBirthStep.test.tsx',
    files: [
      {
        path: 'packages/business-web/src/screens/SignupWizard/steps/__tests__/DateOfBirthStep.test.tsx',
        status: 'passed',
        passed: 6,
        failed: 0,
        duration: '38ms',
      },
      {
        path: 'packages/business-web/src/screens/SignupWizard/steps/__tests__/DateOfBirthStep.validation.test.tsx',
        status: 'failed',
        passed: 2,
        failed: 1,
        duration: '41ms',
      },
      {
        path: 'packages/business-web/src/components/__tests__/DateOfBirth.helpers.test.ts',
        status: 'passed',
        passed: 4,
        failed: 0,
        duration: '12ms',
      },
    ],
    tests: [],
    totals: { passed: 12, failed: 1, skipped: 0 },
    duration: '1.08s',
    provenance: 'VITEST OUTPUT FROM THE CAPTURED RUN',
  },
};

/** The agent contract: a shell activity in, card props out. */
export const ParsedFromActivity: Story = {
  render: () => {
    const activity: ActivityItem = {
      id: 'shell-1',
      category: 'shell',
      verb: 'Ran',
      object: 'pytest test_app.py',
      running: false,
      input:
        '{"command": ".venv/bin/python -m pytest -v test_app.py", "cwd": "/workspace"}',
      output: [
        'test_app.py::test_shout PASSED',
        'test_app.py::test_slugify_lowercases PASSED',
        'test_app.py::test_slugify_strips_punctuation PASSED',
        '',
        '3 passed in 0.02s',
      ].join('\n'),
    };
    const run = testRunFromActivity(activity);
    return run ? (
      <TestRunCard {...run} provenance="PARSED FROM THE SHELL ACTIVITY" />
    ) : (
      <p className="text-sm text-ds-text-neutral-subtle-default">
        No test run in that activity.
      </p>
    );
  },
};
