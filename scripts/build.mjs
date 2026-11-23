import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import Asciidoctor from '@asciidoctor/core';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const upstream = path.resolve(option('--upstream', path.join(root, '.local/upstream')));
const output = path.resolve(option('--output', path.join(root, '.local/rendered.json')));
const asciidoctor = Asciidoctor();
const old = fs.existsSync(output) ? JSON.parse(fs.readFileSync(output, 'utf8')) : {pages: []};
const previous = new Map(old.pages.map(page => [page.id, page]));
const walk = dir => fs.readdirSync(dir, {withFileTypes: true}).flatMap(entry => entry.isDirectory() ? walk(path.join(dir, entry.name)) : entry.name.endsWith('.adoc') ? [path.join(dir, entry.name)] : []);
const nav = fs.readFileSync(path.join(upstream, 'antora/modules/ROOT/nav.adoc'), 'utf8');
const navigation = [];
let currentGroup = '基础教程';
for (const line of nav.split('\n')) {
  const entry = line.match(/^(\*+)\s+(?:xref:([^\[]+)\[([^\]]+)\]|(.+))/);
  if (!entry) continue;
  const depth = entry[1].length;
  const title = entry[3] || entry[4];
  if (depth === 1) currentGroup = title;
  if (entry[2]) navigation.push({id: entry[2].replace(/\.adoc$/, ''), title, depth, group: currentGroup});
}
const navMap = new Map();
for (const [order, entry] of navigation.entries()) if (!navMap.has(entry.id)) navMap.set(entry.id, {...entry, order});
const pages = [];
for (const file of walk(path.join(upstream, 'en'))) {
  const id = path.relative(path.join(upstream, 'en'), file).replaceAll('\\', '/').replace(/\.adoc$/, '');
  const source = fs.readFileSync(file, 'utf8');
  const hash = crypto.createHash('sha256').update('render-v4:' + source).digest('hex');
  const meta = navMap.get(id) || {id, title: id.split('/').at(-1).replaceAll('_', ' '), depth: 2, group: '更多专题', order: 10000};
  if (previous.get(id)?.hash === hash) { pages.push({...meta, ...previous.get(id), depth: meta.depth, group: meta.group, order: meta.order}); continue; }
  // Secure mode disables includes and remote file reads in untrusted upstream content.
  const doc = asciidoctor.load(source, {safe: 'secure', standalone: false, attributes: {showtitle: false, sectanchors: true, 'source-highlighter': 'none', 'experimental': true, 'relfilesuffix': '.html'}});
  const title = doc.getDocumentTitle() || meta.title;
  let html = doc.convert();
  const explicitLicense = source.match(/SPDX-License-Identifier:\s*([^\s]+)/)?.[1];
  const apacheSections = ['ML_Inference/', 'OpenXR_Vulkan_Spatial_Computing/', 'AI_Assisted_Vulkan/', 'Advanced_glTF/', 'Advanced_Vulkan_Compute/', 'Building_a_Simple_Engine/', 'Synchronization/'];
  const license = explicitLicense || (apacheSections.some(prefix => id.startsWith(prefix)) ? 'Apache-2.0' : 'CC-BY-SA-4.0');
  const copyright = source.split('\n').filter(line => /copyright\s*(?:\(c\)|©|\d)/i.test(line)).map(line => line.trim());
  pages.push({...meta, title, hash, html, license, copyright});
}
pages.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
fs.mkdirSync(path.dirname(output), {recursive: true});
fs.writeFileSync(output + '.tmp', JSON.stringify({pages, navigation}));
fs.renameSync(output + '.tmp', output);
console.log(`Rendered ${pages.length} tutorial pages -> ${output}`);
