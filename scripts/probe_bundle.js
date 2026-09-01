const fs = require('fs');
const path = '/Users/octagon/Documents/github/eigent-theia/packages/eigent-agent/assets/agent-embed/agent-embed.umd.js';
const s = fs.readFileSync(path, 'utf8');
const pat = process.argv[2];
const before = parseInt(process.argv[3] || '0', 10);
const after = parseInt(process.argv[4] || '0', 10);
let i = -1, count = 0;
while ((i = s.indexOf(pat, i + 1)) !== -1 && count < 10) {
  count++;
  const start = Math.max(0, i - before);
  const end = Math.min(s.length, i + pat.length + after);
  console.log('----- match', count, '-----');
  console.log(s.slice(start, end));
}
console.log('\n[total matches for', JSON.stringify(pat), 'captured:', count, ']');
