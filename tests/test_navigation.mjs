import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Run the actual reader's pure tree helpers, without booting its DOM or network.
const source = fs.readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const instrumented = source.replace(/\n  init\(\);\n\}\)\(\);\s*$/, '\n  globalThis.navigationTest = {buildNavigationTree, filterNavigationTree};\n})();');
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
