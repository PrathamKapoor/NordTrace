/* Synthetic contract responses. Script tests do not establish browser accessibility. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../../src/nordtrace/frontend/index.html'), 'utf8');

function runtime(fetch) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
      innerHTML: '', textContent: '', dataset: {}, attributes: {}, style: {}, hidden: false,
      classList: {add(name) {classes.add(name)}, remove(name) {classes.delete(name)},
        contains(name) {return classes.has(name)}}, addEventListener() {}, querySelectorAll() {return []},
      setAttribute(name, value) { this.attributes[name] = value; },
      focus() { this.focused = true; }, scrollIntoView() {},
      });
    }
    return elements.get(id);
  }
  const context = vm.createContext({URL, console, setTimeout, clearTimeout, fetch,
    document: {getElementById: element, querySelector: element, querySelectorAll() {return []}},
    window: {scrollTo() {}},
  });
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  return {context, element};
}

test('source links reject unsafe schemes and escape their visible text', () => {
  const {context} = runtime();
  for (const value of ['javascript:alert(1)', 'data:text/html,test', '//evil.example/',
    'https://user:secret@example.no/', 'https://example.no/\npath']) {
    context.value = value;
    assert.doesNotMatch(vm.runInContext('safeSourceLink(value)', context), /<a\b/);
  }
  context.value = 'https://example.no/?q="<script>';
  const rendered = vm.runInContext('safeSourceLink(value)', context);
  assert.match(rendered, /<a\b/);
  assert.doesNotMatch(rendered, /<script>/);
  assert.match(rendered, /noopener noreferrer/);
});

test('company and trace reads stay within the selected historical run', async () => {
  const calls = [];
  const {context} = runtime(async url => {
    calls.push(url);
    return {ok: true, json: async () => ({company: {}, facts: [], sources: [], trace: []})};
  });
  await vm.runInContext('loadCompany("982463718", "run old/1")', context);
  assert.equal(calls[0], '/companies/982463718?run_id=run%20old%2F1');
  assert.equal(calls[1], '/runs/run%20old%2F1/trace');
});

test('drawer loads exact run evidence, escapes values and reports snapshot failure', async () => {
  const calls = [];
  let available = true;
  const {context, element} = runtime(async url => {
    calls.push(url);
    return {ok: available, status: available ? 200 : 409, json: async () => available ? {
      format: 'nordtrace-evidence-view-v1', run_id: 'old', organisation_number: '982463718',
      evidence: {locator: {kind: 'json_pointer', pointer: '/antallAnsatte', raw_value: 0},
        evidence_text: '<img src=x onerror=alert(1)>', retrieved_at: '2025-01-01T00:00:00Z'},
      source: {url: 'javascript:alert(1)', content_hash: 'fixture', retrieved_at: '2025-01-01T00:00:00Z'},
      snapshot: {verified: true, content_hash: 'fixture', representation: 'http-response-body-v1'},
      claims: [{state: 'current', claim: {value: 0}}],
    } : {detail: {code: 'snapshot_unavailable'}}};
  });
  context.fact = {org_number: '982463718', evidence_id: 'ev/old', category: 'identity',
    field: 'employee_count', value: 0};
  await vm.runInContext('showEvidence(fact, "old")', context);
  assert.equal(calls[0], '/companies/982463718/evidence/ev%2Fold?run_id=old');
  const output = element('evidencePanel').innerHTML;
  assert.match(output, /\/antallAnsatte/);
  assert.match(output, /&lt;img/);
  assert.doesNotMatch(output, /<img\b|href="javascript:/);
  assert.match(output, /Source value/);
  available = false;
  await vm.runInContext('showEvidence(fact, "old")', context);
  assert.match(element('evidencePanel').innerHTML, /retained snapshot is unavailable/i);
  assert.doesNotMatch(element('evidencePanel').innerHTML, /Source value/);
});

test('closing pending evidence restores trigger state and ignores a late response', async () => {
  let resolve;
  const {context, element} = runtime(() => new Promise(done => {resolve = done}));
  context.trigger = element('trigger');
  context.fact = {org_number: '982463718', evidence_id: 'old'};
  const pending = vm.runInContext('showEvidence(fact, "old", trigger)', context);
  assert.equal(context.trigger.attributes['aria-expanded'], 'true');
  vm.runInContext('closeEvidence()', context);
  assert.equal(context.trigger.attributes['aria-expanded'], 'false');
  assert.equal(context.trigger.focused, true);
  const closedContent = element('evidencePanel').innerHTML;
  resolve({ok: true, json: async () => ({})});
  await pending;
  assert.equal(element('evidencePanel').innerHTML, closedContent);
});

test('committing a new company closes evidence opened during its pending load', async () => {
  let resolveCompany;
  const {context, element} = runtime(url => {
    if (url.startsWith('/companies/958973306?')) return new Promise(done => {resolveCompany = done});
    if (url.includes('/evidence/')) return Promise.resolve({ok: true, json: async () => ({
      run_id: 'old', evidence: {locator: {raw_value: 'OLD AS', pointer: '/navn'}, evidence_text: 'OLD AS'},
      source: {url: 'https://example.no'}, snapshot: {}, claims: [{state: 'current'}],
    })});
    return Promise.resolve({ok: true, json: async () => ({trace: []})});
  });
  const loading = vm.runInContext('loadCompany("958973306", "new")', context);
  await vm.runInContext('showEvidence({org_number:"982463718",evidence_id:"old",value:"OLD AS"},"old")', context);
  assert.match(element('evidencePanel').innerHTML, /OLD AS/);
  resolveCompany({ok: true, json: async () => ({run_id: 'new', company: {legal_name: 'NEW AS'}})});
  await loading;
  assert.equal(element('cName').textContent, 'NEW AS');
  assert.equal(element('evidencePanel').classList.contains('hidden'), true);
});

test('a late company response cannot replace the latest selected company', async () => {
  let resolveFirst;
  const {context, element} = runtime(url => {
    if (url.startsWith('/companies/982463718?')) return new Promise(done => {resolveFirst = done});
    return Promise.resolve({ok: true, json: async () => ({run_id: 'new', company: {legal_name: 'NEW AS'}})});
  });
  const old = vm.runInContext('loadCompany("982463718", "old")', context);
  await vm.runInContext('loadCompany("958973306", "new")', context);
  resolveFirst({ok: true, json: async () => ({run_id: 'old', company: {legal_name: 'OLD AS'}})});
  await old;
  assert.equal(element('cName').textContent, 'NEW AS');
});

test('a failed new-run trace cannot retain the previous company trace', async () => {
  const {context, element} = runtime(async url => {
    if (url === '/runs/old/trace') return {ok: true, json: async () => ({trace: [{
      timestamp: '2025-01-01T00:00:00Z', stage: 'identity', message: 'OLD COMPANY TRACE',
    }]})};
    if (url === '/runs/new/trace') return {ok: false};
    const old = url.includes('982463718');
    return {ok: true, json: async () => ({run_id: old ? 'old' : 'new',
      company: {legal_name: old ? 'OLD AS' : 'NEW AS'}})};
  });
  await vm.runInContext('loadCompany("982463718", "old")', context);
  assert.match(element('traceBox').innerHTML, /OLD COMPANY TRACE/);
  await vm.runInContext('loadCompany("958973306", "new")', context);
  assert.equal(element('cName').textContent, 'NEW AS');
  assert.doesNotMatch(element('traceBox').innerHTML, /OLD COMPANY TRACE/);
  assert.match(element('traceBox').innerHTML, /trace unavailable/i);
});
