// Explicit-language browser highlighting; never auto-detect terminal output or unlabeled listings.
import hljs from 'highlight.js/lib/core';
import c from 'highlight.js/lib/languages/c';
import cpp from 'highlight.js/lib/languages/cpp';
import glsl from 'highlight.js/lib/languages/glsl';
import bash from 'highlight.js/lib/languages/bash';
import cmake from 'highlight.js/lib/languages/cmake';
import python from 'highlight.js/lib/languages/python';
import yaml from 'highlight.js/lib/languages/yaml';
import json from 'highlight.js/lib/languages/json';
import java from 'highlight.js/lib/languages/java';
import groovy from 'highlight.js/lib/languages/groovy';
import xml from 'highlight.js/lib/languages/xml';
import swift from 'highlight.js/lib/languages/swift';
import kotlin from 'highlight.js/lib/languages/kotlin';
import nsis from 'highlight.js/lib/languages/nsis';
import makefile from 'highlight.js/lib/languages/makefile';
import powershell from 'highlight.js/lib/languages/powershell';
import dockerfile from 'highlight.js/lib/languages/dockerfile';
import sql from 'highlight.js/lib/languages/sql';

function slang(core) {
  // Slang is explicitly labeled upstream. Reuse the BSD C++ lexer and add shader type vocabulary.
  const grammar = cpp(core);
  grammar.name = 'Slang';
  grammar.aliases = [];
  grammar.keywords.keyword.push('let', 'var', 'import', 'module', 'export', 'in', 'out', 'inout', 'uniform', 'groupshared', 'discard', 'cbuffer', 'tbuffer', 'extension', 'interface', 'associatedtype', 'where', 'property', 'get', 'set');
  grammar.keywords.type.push('uint', 'half', 'vector', 'matrix', 'ConstantBuffer', 'StructuredBuffer', 'RWStructuredBuffer', 'ByteAddressBuffer', 'RWByteAddressBuffer', 'Texture1D', 'Texture2D', 'Texture3D', 'TextureCube', 'RWTexture2D', 'SamplerState', 'SamplerComparisonState');
  for (const scalar of ['float', 'half', 'double', 'int', 'uint', 'bool']) {
    for (let rows = 1; rows <= 4; rows++) {
      grammar.keywords.type.push(`${scalar}${rows}`);
      for (let cols = 1; cols <= 4; cols++) grammar.keywords.type.push(`${scalar}${rows}x${cols}`);
    }
  }
  grammar.contains.unshift({scope: 'meta', match: /\bSV_[A-Za-z0-9_]+\b/, relevance: 0});
  return grammar;
}

const definitions = {c, cpp, glsl, slang, bash, cmake, python, yaml, json, java, groovy, xml, swift, kotlin, nsis, makefile, powershell, dockerfile, sql};
for (const [name, definition] of Object.entries(definitions)) hljs.registerLanguage(name, definition);

const aliases = Object.freeze({'c++': 'cpp', cc: 'cpp', cxx: 'cpp', hpp: 'cpp', shell: 'bash', sh: 'bash', zsh: 'bash', py: 'python', yml: 'yaml', html: 'xml', ps1: 'powershell', pwsh: 'powershell', make: 'makefile', docker: 'dockerfile'});
const plain = new Set(['text', 'txt', 'plain', 'plaintext', 'none', 'nohighlight', 'no-highlight', 'console', 'output']);
const handled = new WeakMap();

export function resolveLanguage(label) {
  const name = typeof label === 'string' ? label.trim().toLowerCase() : '';
  if (!name || plain.has(name)) return null;
  const canonical = aliases[name] || name;
  return Object.prototype.hasOwnProperty.call(definitions, canonical) ? canonical : null;
}

export function highlightText(text, label) {
  const language = resolveLanguage(label);
  if (!language || typeof text !== 'string') return null;
  return {language, html: hljs.highlight(text, {language, ignoreIllegals: true}).value};
}

function explicitLanguage(code) {
  const pre = code.parentElement;
  if ([code, pre].some(node => node?.classList.contains('nohighlight') || node?.classList.contains('no-highlight'))) return null;
  for (const node of [code, pre]) {
    const labeled = node?.getAttribute('data-lang');
    if (labeled) return labeled;
    for (const name of node?.classList || []) {
      const match = /^(?:language|lang)-(.+)$/i.exec(name);
      if (match) return match[1];
    }
  }
  return null;
}

export function highlight(container) {
  if (!container?.querySelectorAll) return 0;
  let count = 0;
  for (const code of container.querySelectorAll('pre > code')) {
    const source = code.textContent;
    const language = resolveLanguage(explicitLanguage(code));
    if (!language) continue;
    const previous = handled.get(code);
    if (previous?.source === source && previous.language === language) continue;
    try {
      const result = highlightText(source, language);
      const template = code.ownerDocument.createElement('template');
      template.innerHTML = result.html;
      // The lexer escapes source markup. Verify the DOM round trip before changing a live listing.
      if (template.content.textContent !== source) continue;
      if ([...template.content.querySelectorAll('*')].some(node => node.tagName !== 'SPAN' || [...node.attributes].some(attribute => attribute.name !== 'class'))) continue;
      code.replaceChildren(template.content);
      code.classList.add('hljs');
      code.dataset.syntaxLanguage = language;
      code.parentElement.classList.add('syntax-highlighted');
      handled.set(code, {source, language});
      count++;
    } catch {
      // Preserve the readable original if a future grammar cannot process a particular listing.
    }
  }
  return count;
}

if (typeof window !== 'undefined') {
  window.VulkanSyntax = Object.freeze({highlight, version: hljs.versionString});
}
