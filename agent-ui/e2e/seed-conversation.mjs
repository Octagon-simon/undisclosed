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

// Seeds a deterministic multi-turn conversation into the local brain's data
// (~/.undisclosed) and binds it to the eigent-theia folder space, so the E2E
// render harness can open it and assert no stacking + reload retention.
//
// Usage: node e2e/seed-conversation.mjs
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const HOME = os.homedir();
const UND = path.join(HOME, '.undisclosed');
const FOLDER = '/Users/octagon/Documents/github/eigent-theia';
// Stable, obvious id so it sorts newest (large timestamp) and is easy to find.
export const CHAT_ID = '9999999999999-0001';

const TURNS = [
  {
    queryId: `${CHAT_ID}-q1`,
    question: 'E2E-Q1 what is two plus two',
    answer: 'E2E-A1 the answer is four',
    createdAt: '2027-01-01T00:00:01.000Z',
  },
  {
    queryId: `${CHAT_ID}-q2`,
    question: 'E2E-Q2 and three plus three',
    answer: 'E2E-A2 the answer is six',
    createdAt: '2027-01-01T00:00:10.000Z',
  },
];

function writeJson(p, data) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(data, null, 2));
}

// 1) turn files
const chatDir = path.join(UND, 'turns', CHAT_ID);
fs.rmSync(chatDir, { recursive: true, force: true });
for (const t of TURNS) {
  writeJson(path.join(chatDir, `turn_${t.queryId}.json`), {
    chatId: CHAT_ID,
    queryId: t.queryId,
    userMessage: {
      id: t.queryId,
      content: t.question,
      createdAt: t.createdAt,
      attaches: [],
      fileList: [],
      agent_name: null,
    },
    otherMessages: [
      {
        id: `${t.queryId}-a`,
        step: 'end',
        content: t.answer,
        createdAt: t.createdAt,
        attaches: [],
        fileList: [],
        agent_name: null,
        reasoning: null,
      },
    ],
  });
}

// 2) friendly name
const namesPath = path.join(UND, 'project_names.json');
const names = fs.existsSync(namesPath)
  ? JSON.parse(fs.readFileSync(namesPath, 'utf8'))
  : {};
names[CHAT_ID] = TURNS[0].question;
writeJson(namesPath, names);

// 3) bind to the eigent-theia folder space
const regPath = path.join(UND, 'folder_spaces.json');
const reg = fs.existsSync(regPath)
  ? JSON.parse(fs.readFileSync(regPath, 'utf8'))
  : { by_root: {} };
reg.by_root = reg.by_root || {};
const entry = reg.by_root[FOLDER] || {
  id: null,
  name: 'eigent-theia',
  root_path: FOLDER,
  conversations: {},
};
// derive the folder space id the same way the brain does (sha256[:16]) if absent
if (!entry.id) {
  const crypto = await import('node:crypto');
  entry.id =
    'folder_' + crypto.createHash('sha256').update(FOLDER).digest('hex').slice(0, 16);
}
entry.conversations = entry.conversations || {};
entry.conversations[CHAT_ID] = {
  name: TURNS[0].question,
  added_at: new Date().toISOString(),
};
reg.by_root[FOLDER] = entry;
writeJson(regPath, reg);

console.log(
  JSON.stringify(
    { CHAT_ID, folderSpaceId: entry.id, turns: TURNS.length },
    null,
    2
  )
);
