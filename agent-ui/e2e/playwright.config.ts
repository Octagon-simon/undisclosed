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

import { defineConfig } from '@playwright/test';

// E2E render harness config. Assumes the local brain is already running on
// :5001 (./scripts/brain.sh start). Serves the built agent-embed bundle via
// e2e/serve.mjs and drives it in a real browser.
export default defineConfig({
  testDir: '.',
  testMatch: /render\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:4599',
    headless: true,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'node serve.mjs',
    url: 'http://localhost:4599/harness.html',
    reuseExistingServer: true,
    timeout: 20_000,
  },
});
