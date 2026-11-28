// Text rules shared by the browser reader and offline translation review.
(() => {
  'use strict';
  // Only remove MT padding between Chinese prose and its adjacent term.
  function trimTermPadding(text, previousTerm, nextTerm) {
    if (/^\p{Script=Han}/u.test(nextTerm)) {
      text = text.replace(/([\p{Script=Han}，。！？；：、（）《》“”‘’]) +$/u, '$1');
    }
    if (/\p{Script=Han}$/u.test(previousTerm)) {
      text = text.replace(/^ +(?=[\p{Script=Han}，。！？；：、（）《》“”‘’])/u, '');
    }
    return text;
  }
  // Project English labels onto the original inline text. Text-node boundaries
  // include links and emphasis, so spacing is consistent across nested markup.
  function englishTermTexts(runs) {
    const values = runs.map(run => run.english || run.text);
    for (let i = 0; i + 1 < runs.length; i++) {
      if (!runs[i].english || runs[i + 1].protected || runs[i + 1].english) continue;
      // Suppress an explicit copy of this English name; keep abbreviations,
      // interface identifiers, links and explanatory parentheticals.
      const gloss = /^\s*[（(]\s*([^（）()]+?)\s*[）)]/.exec(values[i + 1]);
      if (gloss && gloss[1].toLowerCase() === runs[i].english.toLowerCase()) {
        values[i + 1] = values[i + 1].slice(gloss[0].length);
      }
    }
    let previous = -1;
    for (let i = 0; i < runs.length; i++) {
      if (!values[i]) continue;
      if (previous !== -1 && /[\p{L}\p{N}]$/u.test(values[previous]) && /^[\p{L}\p{N}]/u.test(values[i])) {
        if (runs[i].english) values[i] = ' ' + values[i];
        else if (runs[previous].english) values[previous] += ' ';
      }
      previous = i;
    }
    return values;
  }
  globalThis.VulkanTermText = {trimTermPadding, englishTermTexts};
})();
