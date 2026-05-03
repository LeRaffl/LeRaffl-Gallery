#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const repo = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(repo, 'index.html'), 'utf8');

function listFromConst(name) {
  const re = new RegExp(String.raw`const\s+${name}\s*=\s*\[([\s\S]*?)\];`);
  const m = html.match(re);
  if (!m) throw new Error(`Could not find ${name} in index.html`);
  return [...m[1].matchAll(/'([^']+)'/g)].map(x => x[1]);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];

    if (quoted) {
      if (ch === '"' && next === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ',') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else if (ch !== '\r') {
      cell += ch;
    }
  }

  if (cell !== '' || row.length) {
    row.push(cell);
    rows.push(row);
  }

  const header = rows.shift() || [];
  return rows
    .filter(r => r.some(c => String(c).trim()))
    .map(r => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
}

const known = new Set(listFromConst('DS_KNOWN_CATEGORIES'));
const ordered = new Set(listFromConst('DS_CATEGORY_ORDER'));
const marketsDir = path.join(repo, 'data', 'markets');
const categories = new Map();

for (const file of fs.readdirSync(marketsDir).sort()) {
  if (!file.endsWith('.csv') || file === '_index.csv') continue;
  const rows = parseCsv(fs.readFileSync(path.join(marketsDir, file), 'utf8'));
  for (const row of rows) {
    const cat = String(row.category || '').trim().toUpperCase();
    if (!cat) continue;
    if (!categories.has(cat)) categories.set(cat, []);
    categories.get(cat).push(file.replace(/\.csv$/, ''));
  }
}

const missingKnown = [...categories.keys()].filter(cat => !known.has(cat)).sort();
const missingOrder = [...categories.keys()].filter(cat => !ordered.has(cat)).sort();

if (missingKnown.length || missingOrder.length) {
  if (missingKnown.length) {
    console.error(`Missing from DS_KNOWN_CATEGORIES: ${missingKnown.join(', ')}`);
  }
  if (missingOrder.length) {
    console.error(`Missing from DS_CATEGORY_ORDER: ${missingOrder.join(', ')}`);
  }
  for (const cat of new Set([...missingKnown, ...missingOrder])) {
    console.error(`${cat}: ${categories.get(cat).slice(0, 12).join(', ')}`);
  }
  process.exit(1);
}

console.log(`Submit Data categories cover ${categories.size} CSV categories: ${[...categories.keys()].sort().join(', ')}`);
