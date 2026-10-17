// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * Agent activity -> `TestRunCard` props.
 *
 * The shell tool already sends the exact command and its output, so a turn
 * needs no new event to light up the card: `testRunFromActivity` parses the
 * pair and the panel renders the receipt. Runners that print per-test lines
 * (pytest -v, vitest, jest, go test) fill the rows; a default pytest run only
 * prints dots, so it falls back to the summary counts.
 */

import type { ActivityItem } from '@/lib/activityClassifier';
import type {
  TestCase,
  TestCaseStatus,
  TestRunTotals,
} from '@/components/ChatBox/MessageItem/TestRunCard';

export interface TestRunSnapshot {
  command: string;
  tests: TestCase[];
  totals?: TestRunTotals;
  duration?: string;
  running?: boolean;
}

const TEST_RUNNER =
  /(?:^|[\s;&|(])(?:[\w./-]*python[\w./-]*\s+-m\s+(?:pytest|unittest)|pytest|py\.test|vitest|jest|go\s+test|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+(?:run\s+)?test|bun\s+(?:run\s+)?test|cargo\s+test|dotnet\s+test|mvn(?:w)?\s+test|gradlew?\s+test|rspec|phpunit)\b/i;

export function isTestCommand(command: string): boolean {
  return TEST_RUNNER.test(command);
}

function commandFromInput(input: string): string {
  const match = input.match(
    /["']?(?:command|cmd)["']?\s*[:=]\s*(?:"([^"]*)"|'([^']*)')/
  );
  if (match) return match[1] ?? match[2] ?? '';
  return isTestCommand(input) ? input.trim() : '';
}

const TEST_FILE = /\.(?:[cm]?[jt]sx?|py|go|rs|rb|php|java|kt|swift|cs)$/i;
/** Flags that narrow the run by name/marker instead of running everything. */
const SCOPING_FLAG =
  /^(?:-k|-m|-t|-run|-Dtest=|--filter|--tests?|--deselect|--testNamePattern|--testPathPattern)\b/;
/** Flag + separate value pairs that are configuration, not a target. */
const VALUE_FLAG = new Set([
  '-p',
  '-c',
  '-n',
  '-o',
  '--maxfail',
  '--tb',
  '--rootdir',
  '--confcutdir',
  '--junitxml',
  '--cov',
  '--cov-report',
  '--ignore',
  '--durations',
  '--timeout',
  '--basetemp',
  '--log-level',
  '--color',
  '--reporter',
]);
const RUNNER_SUBCOMMAND = new Set(['run', 'watch', 'dev', 'serve', 'ci']);

/**
 * True when the command runs the whole suite rather than a target: `pytest` with
 * no paths, `npm test`, `vitest run --coverage`, `go test ./...`. The card is
 * scoped to the files the turn touched, so these never produce it.
 */
export function isFullSuiteCommand(command: string): boolean {
  if (!isTestCommand(command)) return false;

  const start = command.search(TEST_RUNNER);
  if (start === -1) return true;
  const rest = command.slice(start).replace(TEST_RUNNER, '');
  const args = rest.match(/"(?:[^"\\]|\\.)*"|'[^']*'|\S+/g) ?? [];

  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i].replace(/^['"]|['"]$/g, '');
    if (!arg || arg === '--') continue;
    if (SCOPING_FLAG.test(arg)) return false;
    if (VALUE_FLAG.has(arg)) {
      i += 1;
      continue;
    }
    if (arg.startsWith('-')) continue;
    if (RUNNER_SUBCOMMAND.has(arg)) continue;
    // `./...` and `dir/...` are whole-tree runs in Go tooling.
    if (arg === '...' || arg.endsWith('/...')) continue;
    return false;
  }
  return true;
}

const PYTEST_LINE = /^\s*(\S.*?)\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b/;
const MARK_LINE = /^\s*[✓✔×✕✗○◯√]\s+(.+?)\s*$/;
const GO_LINE = /^\s*---\s+(PASS|FAIL|SKIP):\s+(\S+)/;

const PYTEST_STATUS: Record<string, TestCaseStatus> = {
  PASSED: 'passed',
  XPASS: 'passed',
  FAILED: 'failed',
  XFAIL: 'failed',
  ERROR: 'failed',
  SKIPPED: 'skipped',
};

function pytestName(node: string): string {
  const parts = node.split('::').filter(Boolean);
  return parts.length > 1 ? parts.slice(1).join(' › ') : node;
}

function stripTiming(name: string): string {
  return name.replace(/\s+\d+(?:\.\d+)?\s*(?:ms|s)$/, '').trim();
}

function collectNamedTests(output: string): TestCase[] {
  const byName = new Map<string, TestCaseStatus>();

  for (const line of output.split('\n')) {
    const pytest = line.match(PYTEST_LINE);
    if (pytest && pytest[1].includes('::')) {
      byName.set(pytestName(pytest[1]), PYTEST_STATUS[pytest[2]] ?? 'failed');
      continue;
    }

    const go = line.match(GO_LINE);
    if (go) {
      byName.set(
        go[2],
        go[1] === 'PASS' ? 'passed' : go[1] === 'FAIL' ? 'failed' : 'skipped'
      );
      continue;
    }

    const mark = line.match(MARK_LINE);
    if (mark) {
      const status: TestCaseStatus =
        /[×✕✗]/.test(line.trim()[0]) ? 'failed' : 'passed';
      byName.set(stripTiming(mark[1]), status);
    }
  }

  return [...byName.entries()].map(([name, status]) => ({ name, status }));
}

function lastMatch(output: string, re: RegExp): RegExpMatchArray | null {
  const flags = re.flags.includes('g') ? re.flags : `${re.flags}g`;
  const global = new RegExp(re.source, flags);
  let found: RegExpMatchArray | null = null;
  for (const match of output.matchAll(global)) found = match;
  return found;
}

function count(re: RegExp, text: string): number {
  const match = lastMatch(text, re);
  return match ? Number(match[1]) : 0;
}

function totalsFromText(output: string): TestRunTotals | null {
  const line =
    lastMatch(output, /^=+.*\b(?:passed|failed|error|skipped)\b.*=+$/m)?.[0] ??
    lastMatch(output, /^Tests:\s+.*$/m)?.[0] ??
    lastMatch(output, /^\s*Tests\s+.*$/m)?.[0] ??
    '';

  const passed = count(/(\d+)\s+passed/i, line || output);
  const failed =
    count(/(\d+)\s+failed/i, line || output) +
    count(/(\d+)\s+error(?:s)?\b/i, line || output);
  const skipped = count(/(\d+)\s+skipped/i, line || output);

  if (!passed && !failed && !skipped) return null;
  return { passed, failed, skipped };
}

function durationFromText(output: string): string | undefined {
  const patterns = [
    /\bin\s+(\d+(?:\.\d+)?\s*(?:ms|s|µs|us))\b/,
    /\bTime:\s*(\d+(?:\.\d+)?\s*s)\b/,
    /\bDuration\s+(\d+(?:\.\d+)?\s*(?:ms|s))\b/,
    /^ok\s+\S+\s+(\d+(?:\.\d+)?s)\b/m,
  ];
  for (const pattern of patterns) {
    const match = lastMatch(output, pattern);
    if (match) return match[1];
  }
  return undefined;
}

export function parseTestRun({
  command,
  output,
  running = false,
}: {
  command: string;
  output: string;
  running?: boolean;
}): TestRunSnapshot | null {
  if (!isTestCommand(command)) return null;

  const tests = collectNamedTests(output);
  const totals = totalsFromText(output);
  if (!tests.length && !totals) return null;

  return {
    command,
    tests,
    totals: totals ?? undefined,
    duration: durationFromText(output),
    running,
  };
}

export function testRunFromActivity(
  item: ActivityItem
): TestRunSnapshot | null {
  if (item.category !== 'shell') return null;
  const command = commandFromInput(item.input);
  if (!command) return null;
  return parseTestRun({ command, output: item.output, running: item.running });
}

/**
 * The turn's scoped verification run: the last targeted test shell activity
 * AFTER the turn's last file edit.
 *
 * Two gates keep the card tied to the work:
 * - The edit gate: a bare "run the suite" turn leaves it hidden.
 * - The scope gate: an unscoped suite command (`npm test`, bare `pytest`) is
 *   skipped, so editing one file cannot flood the panel with the whole project.
 *
 * If the turn ran several targeted commands, the last one wins; if it ran only
 * the full suite, the card stays hidden.
 */
export function latestTestRun(
  items: ActivityItem[],
  { requireEdit = true }: { requireEdit?: boolean } = {}
): TestRunSnapshot | null {
  const lastEdit = requireEdit
    ? items.reduce((index, item, i) => (item.category === 'edit' ? i : index), -1)
    : -1;
  if (requireEdit && lastEdit === -1) return null;

  for (let i = items.length - 1; i > lastEdit; i--) {
    const run = testRunFromActivity(items[i]);
    if (run && !isFullSuiteCommand(run.command)) return run;
  }
  return null;
}
