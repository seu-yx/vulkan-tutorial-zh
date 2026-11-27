import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Run the actual reader's pure tree helpers, without booting its DOM or network.
const source = fs.readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const instrumented = source.replace(/\n  init\(\);\n\}\)\(\);\s*$/, '\n  globalThis.navigationTest = {buildNavigationTree, filterNavigationTree, prepareTerms};\n})();');
assert.notEqual(instrumented, source, 'Reader test hook did not match');
const context = {document: {currentScript: {src: 'https://example.test/tutorial/app.js'}}, localStorage: {getItem: () => null}, URL};
vm.runInNewContext(instrumented, context);
const {buildNavigationTree, filterNavigationTree} = context.navigationTest;
const page = (id, title = id) => ({id, title, titleZh: title, group: '基础教程'});
const leaves = nodes => nodes.flatMap(node => node.children.length ? leaves(node.children) : node.page ? [node.page.id] : []);

const catalog = {
  pages: [page('triangle/setup/base', 'Base code'), page('triangle/setup/instance', 'Instance'), page('triangle/presentation/surface', 'Window surface'), page('engine/architecture/intro', 'Introduction'), page('unlisted/new', 'New chapter')],
  navigation: [
    {id: 'triangle/setup/base', title: 'Drawing a triangle', depth: 1},
    {id: 'triangle/setup/base', title: 'Setup', depth: 2},
    {id: 'triangle/setup/base', title: 'Base Code', depth: 3},
    {id: 'triangle/setup/instance', title: 'Instance', depth: 3},
    {id: 'triangle/presentation/surface', title: 'Window surface', depth: 2},
    {title: 'Building a Simple Engine', depth: 1},
    {title: 'Engine Architecture', depth: 2},
    {id: 'engine/architecture/intro', title: 'Introduction', depth: 3},
    {href: 'https://example.test', title: 'External repository', depth: 1},
  ],
};
const tree = buildNavigationTree(catalog);
assert.equal(tree[0].title, 'Drawing a triangle');
assert.equal(tree[0].children[0].title, 'Setup');
assert.equal(tree[0].children[0].children[0].page.id, 'triangle/setup/base');
assert.equal(tree[1].children[0].title, 'Engine Architecture');
assert.equal(tree[0].ids.size, 3, 'Repeated xrefs must count each chapter once');
assert.equal(leaves(tree).length, catalog.pages.length, 'Every source chapter must have a reachable leaf');
assert.equal(new Set(leaves(tree)).size, catalog.pages.length, 'Container xrefs must not create duplicate chapter leaves');
assert.equal(tree.at(-1).title, '更多专题', 'Pages missing from official nav must remain reachable');

for (const query of ['setup', '基础设置']) {
  const filtered = filterNavigationTree(tree, query);
  assert.equal(filtered[0].title, 'Drawing a triangle', 'Search must retain ancestor context');
  assert.deepEqual([...leaves(filtered)].sort(), ['triangle/setup/base', 'triangle/setup/instance']);
}
assert.deepEqual([...leaves(filterNavigationTree(tree, 'instance'))], ['triangle/setup/instance']);
assert.deepEqual([...leaves(filterNavigationTree(tree, 'base_code'))], ['triangle/setup/base']);
assert.equal(filterNavigationTree(tree, 'no-such-chapter').length, 0);
assert.equal(filterNavigationTree(tree, ''), tree);

const ownPage = buildNavigationTree({pages: [page('parent'), page('child')], navigation: [{id: 'parent', title: 'Parent', depth: 1}, {id: 'child', title: 'Child', depth: 2}]});
assert.deepEqual([...leaves(ownPage)].sort(), ['child', 'parent'], 'A linked branch without a repeated child must preserve its own page');

const legacy = buildNavigationTree({pages: catalog.pages});
assert.equal(leaves(legacy).length, catalog.pages.length);
assert.ok(legacy[0].children.some(node => node.title === 'triangle' && node.children.some(child => child.title === 'setup')), 'Legacy catalogs must gain real folder nesting');
console.log('Navigation tree: hierarchy, unique reachability, search context and legacy fallback passed');

// Exercise the translation DOM pass with the same attributes as generated pages.
const term = (english, chinese, {inside, before = '', after = ''} = {}) => ({
  dataset: {term: english}, textContent: chinese, title: english, appended: [],
  previousSibling: {nodeType: 3, data: before}, nextSibling: {nodeType: 3, data: after, textContent: after},
  closest(selector) { return inside && selector.split(', ').includes(inside); },
  classList: {add() {}},
  append(gloss) { this.appended.push(gloss); },
});
const settings = {}, tip = {};
context.Node = {TEXT_NODE: 3};
context.document.querySelector = selector => ({'.term-setting': settings, '.toc-tip': tip})[selector];
context.document.createElement = () => ({});
const first = term('queue family', '队列族', {before: '每个 ', after: ' 支持'});
const repeated = term('Queue Family', '队列族');
const heading = term('queue family', '队列族', {inside: 'h3'});
const code = term('queue', 'VkQueue', {inside: 'code'});
const linked = term('fence', '栅栏', {inside: 'a', before: 'GPU ', after: ' 1'});
const explained = term('image', '图像', {after: '（image）'});
const identical = term('GPU', 'GPU');
const annotations = [heading, code, first, repeated, linked, explained, identical];
const content = {
  querySelectorAll: () => annotations,
  querySelector: () => annotations.some(node => node.appended.length),
};
context.navigationTest.prepareTerms(content);
assert.deepEqual(first.appended, [{lang: 'en', className: 'vt-term-original', textContent: '（queue family）'}]);
assert.equal(first.textContent, '队列族');
assert.equal(first.tabIndex, 0);
assert.equal(first.previousSibling.data, '每个');
assert.equal(first.nextSibling.data, '支持');
assert.equal(linked.appended.length, 1);
assert.equal(linked.tabIndex, undefined, 'A link provides its own focus stop');
assert.equal(linked.previousSibling.data, 'GPU ');
assert.equal(linked.nextSibling.data, ' 1');
for (const node of [heading, code, repeated, explained, identical]) assert.equal(node.appended.length, 0);
assert.equal(settings.hidden, false);
annotations.length = 0;
context.navigationTest.prepareTerms(content);
assert.equal(settings.hidden, true);
assert.equal(tip.hidden, true);
console.log('Reader terminology: first prose mention, CJK spacing, link focus, heading/code protection and explicit glosses passed');
