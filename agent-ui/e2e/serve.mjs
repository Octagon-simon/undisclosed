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

// Minimal static server for the render harness: serves e2e/harness.html plus
// the built agent-embed bundle + css from packages/eigent-agent/assets.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ASSETS = path.resolve(
  __dirname,
  '../../packages/eigent-agent/assets/agent-embed'
);
const PORT = Number(process.env.HARNESS_PORT || 4599);

const files = {
  '/': { file: path.join(__dirname, 'harness.html'), type: 'text/html' },
  '/harness.html': { file: path.join(__dirname, 'harness.html'), type: 'text/html' },
  '/agent-embed.umd.js': {
    file: path.join(ASSETS, 'agent-embed.umd.js'),
    type: 'text/javascript',
  },
  '/style.css': { file: path.join(ASSETS, 'style.css'), type: 'text/css' },
};

http
  .createServer((req, res) => {
    const url = req.url.split('?')[0];
    const entry = files[url];
    if (!entry || !fs.existsSync(entry.file)) {
      res.writeHead(404);
      res.end('not found: ' + url);
      return;
    }
    res.writeHead(200, {
      'Content-Type': entry.type,
      'Access-Control-Allow-Origin': '*',
    });
    fs.createReadStream(entry.file).pipe(res);
  })
  .listen(PORT, () => console.log(`[harness] serving on http://localhost:${PORT}`));
