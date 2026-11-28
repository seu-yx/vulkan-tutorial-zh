// One JSON line per batch. Keep the process warm across all chapters of an audit.
import {createInterface} from 'node:readline';
import '../public/term-text.js';

const {trimTermPadding, englishTermTexts} = globalThis.VulkanTermText;
for await (const line of createInterface({input: process.stdin, crlfDelay: Infinity})) {
  const result = JSON.parse(line).map(runs => {
    for (const run of runs) {
      run.text = trimTermPadding(run.text, run.previousTerm || '', run.nextTerm || '');
    }
    return [runs.map(run => run.text), englishTermTexts(runs)];
  });
  process.stdout.write(JSON.stringify(result) + '\n');
}
