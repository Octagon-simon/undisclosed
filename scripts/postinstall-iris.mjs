#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Best-effort fetch of the page-camera binary after npm install. Never fails
// the install: the capability is optional, and packaging fetches with
// --required separately.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const skip =
  process.platform === 'win32' ||
  process.env.UNDISCLOSED_SKIP_IRIS_FETCH === '1';

if (!skip) {
  const script = fileURLToPath(new URL('./fetch-iris.sh', import.meta.url));
  const result = spawnSync('bash', [script], { stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.warn(
      '[fetch-iris] skipped; Page Screenshots stays off until `npm run fetch:iris` succeeds.'
    );
  }
}

process.exit(0);
