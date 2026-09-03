// ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========

import { test, expect, Page } from '@playwright/test';

// Drives the REAL agent panel (agent-embed) against the REAL local brain and
// asserts a seeded multi-turn conversation renders each message EXACTLY once
// (no "stacking") — both on first load and after a full page reload (retention).
//
// Prereqs: `./scripts/brain.sh start` (brain on :5001) and
// `node e2e/seed-conversation.mjs` (seeds the conversation). The npm script
// `test:render` wires both up.

const Q1 = 'E2E-Q1 what is two plus two';
const A1 = 'E2E-A1 the answer is four';
const Q2 = 'E2E-Q2 and three plus three';
const A2 = 'E2E-A2 the answer is six';

function countOccurrences(haystack: string, needle: string): number {
  let count = 0;
  let i = 0;
  for (;;) {
    const idx = haystack.indexOf(needle, i);
    if (idx === -1) break;
    count += 1;
    i = idx + needle.length;
  }
  return count;
}

async function openSeededConversation(page: Page): Promise<void> {
  // Wait for the panel to bootstrap and the conversation to auto-load. If the
  // first turn isn't visible within the window, try clicking it from History.
  const firstTurn = page.getByText(Q1, { exact: false }).first();
  try {
    await firstTurn.waitFor({ state: 'visible', timeout: 12_000 });
    return;
  } catch {
    // Fall back to opening it via the History list.
    const historyEntry = page.getByText(Q1, { exact: false }).first();
    await historyEntry.click({ timeout: 5_000 }).catch(() => undefined);
    await firstTurn.waitFor({ state: 'visible', timeout: 12_000 });
  }
}

async function assertNoStacking(page: Page, label: string): Promise<void> {
  // Let any late hydration/replay settle.
  await page.waitForTimeout(2500);
  const text = await page.locator('#agent-root').innerText();
  const counts = {
    Q1: countOccurrences(text, Q1),
    A1: countOccurrences(text, A1),
    Q2: countOccurrences(text, Q2),
    A2: countOccurrences(text, A2),
  };
  console.log(`[${label}] occurrence counts:`, counts);
  // Each message must render exactly once (retention: >=1; no stacking: <=1).
  expect(counts.Q1, `${label} Q1`).toBe(1);
  expect(counts.A1, `${label} A1 (answer must come back)`).toBe(1);
  expect(counts.Q2, `${label} Q2`).toBe(1);
  expect(counts.A2, `${label} A2 (answer must come back)`).toBe(1);
}

test('conversation renders once and survives reload', async ({ page }) => {
  page.on('console', (m) => {
    const t = m.text();
    if (t.includes('TURNS HYDRATE') || t.includes('[ProjectStore]')) {
      console.log('  browser:', t);
    }
  });

  await page.goto('/harness.html');
  await openSeededConversation(page);
  await assertNoStacking(page, 'first-load');

  // Full reload — exercises the reload path again.
  await page.reload();
  await openSeededConversation(page);
  await assertNoStacking(page, 'after-reload');
});
