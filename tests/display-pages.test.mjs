import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { setTimeout as pause } from 'node:timers/promises';
import { DisplaySession, observeDisplaySession } from '../display-session.mjs';

async function until(predicate) {
  const deadline = Date.now() + 2000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error('Visible page state did not arrive');
    await pause(5);
  }
}

class Element {
  textContent = '';
  innerHTML = '';
  style = { setProperty(name, value) { this[name] = value; } };
  events = new Map();
  clientHeight = 400;
  maxCharacters = Infinity;
  removed = false;
  classList = { add() {}, remove() {} };
  get scrollHeight() { return this.textContent.length > this.maxCharacters ? 500 : 100; }
  addEventListener(name, handler) { this.events.set(name, handler); }
  removeAttribute() {}
  setAttribute() {}
  getBoundingClientRect() { return { width: 400, height: 400 }; }
  cloneNode() { const copy = new Element(); copy.textContent = this.textContent; return copy; }
  remove() { this.removed = true; }
}

function fixture(t, { printer = false } = {}) {
  const name = `display-pages-${crypto.randomUUID()}`;
  const requests = [];
  const captures = [];
  const prints = [];
  const errors = [];
  const cleanup = [];
  const timers = new Set();
  let failPrint = false;
  const fetch = async (url, options) => {
    if (url.endsWith('/health')) return new Response('', { status: printer ? 200 : 503 });
    if (url.endsWith('/print-image')) {
      prints.push(JSON.parse(options.body));
      return new Response('', { status: failPrint ? 500 : 200 });
    }
    let controller;
    let ended = false;
    const body = new ReadableStream({
      start(value) { controller = value; },
      cancel() { ended = true; },
    });
    options.signal.addEventListener('abort', () => {
      if (!ended) { ended = true; controller.error(new DOMException('Aborted', 'AbortError')); }
    });
    requests.push({ record: record => controller.enqueue(new TextEncoder().encode(JSON.stringify(record) + '\n')) });
    return new Response(body);
  };
  function page(filename) {
    const elements = new Map();
    const body = new Element();
    const copies = [];
    body.appendChild = element => copies.push(element);
    const windowEvents = new Map();
    const context = {
      document: {
        body,
        getElementById(id) {
          if (!elements.has(id)) elements.set(id, new Element());
          return elements.get(id);
        },
        createElement() {
          let text = '';
          return { set textContent(value) { text = value; }, get innerHTML() { return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'); } };
        },
      },
      window: { innerWidth: 600, innerHeight: 600, addEventListener: (name, fn) => windowEvents.set(name, fn) },
      console: { log() {}, error: (...args) => errors.push(args) },
      fetch, AbortSignal,
      performance,
      getComputedStyle() {
        const properties = ['font-family', 'color', 'background-color'];
        properties.getPropertyValue = name => name === 'font-family' ? 'Unifont' : '#ffffff';
        return properties;
      },
      html2canvas: snapshot => new Promise(resolve => captures.push({ snapshot, finish() { resolve({ toDataURL: () => 'data:image/png,' + snapshot.textContent }); } })),
      setTimeout(fn, ms) {
        const timer = setTimeout(() => { timers.delete(timer); fn(); }, ms);
        timers.add(timer);
        return timer;
      },
      DisplaySession: class extends DisplaySession {
        constructor(options) {
          super({ ...options, fetch, random: () => 1, channel: new BroadcastChannel(name), onError: error => errors.push(error) });
          cleanup.push(() => this.close());
        }
      },
      observeDisplaySession(options) {
        const close = observeDisplaySession({ ...options, channel: new BroadcastChannel(name) });
        cleanup.push(close);
        return close;
      },
    };
    const html = readFileSync(new URL('../' + filename, import.meta.url), 'utf8');
    const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1]
      .replace(/^\s*import .* from '\.\/display-session\.mjs';\n/m, '');
    vm.runInNewContext(script, context, { filename });
    return { elements, copies, windowEvents };
  }
  t.after(() => { for (const close of cleanup) close(); for (const timer of timers) clearTimeout(timer); });
  return { page, requests, captures, prints, errors, failPrinting: () => { failPrint = true; } };
}

const token = text => ({ text, count: 1, final_prob: 0.8, candidates: [{ token: text, prob: 0.8 }, { token: 'other', prob: 0.2 }] });

test('the actual monitor page joins an already running display and shows its settings and token', async t => {
  const f = fixture(t);
  const main = f.page('main.html');
  f.requests[0].record(token('CURRENT'));
  await until(() => main.elements.get('canvas').textContent === 'CURRENT');
  const monitor = f.page('monitor.html');
  await until(() => monitor.elements.get('current-token').textContent === 'CURRENT');
  assert.equal(monitor.elements.get('meta').textContent, 'TEMP 1.50 | CTX 10 | DELAY 100ms');
  assert.equal(f.requests.length, 1);
  assert.deepEqual(f.errors, []);
});

test('a restart during monitor animation settles on the new round even with no further token', async t => {
  const f = fixture(t);
  const main = f.page('main.html');
  const monitor = f.page('monitor.html');
  f.requests[0].record(token('OLD'));
  await until(() => monitor.elements.get('candidates').innerHTML.includes('OLD'));
  main.elements.get('canvas').events.get('click')();
  f.requests[1].record(token('NEW'));
  await until(() => monitor.elements.get('current-token').textContent === 'NEW');
  await pause(150);
  assert.equal(monitor.elements.get('current-token').textContent, 'NEW');
  assert.equal(main.elements.get('canvas').textContent, 'NEW');
  assert.deepEqual(f.errors, []);
});

test('the actual main page starts a new round when its square overflows', async t => {
  const f = fixture(t);
  const main = f.page('main.html');
  const canvas = main.elements.get('canvas');
  canvas.maxCharacters = 3;
  const monitor = f.page('monitor.html');
  f.requests[0].record(token('TOO LONG'));
  await until(() => f.requests.length === 2);
  assert.equal(canvas.textContent, '');
  f.requests[1].record(token('NEW'));
  await until(() => monitor.elements.get('current-token').textContent === 'NEW');
  assert.equal(canvas.textContent, 'NEW');
  assert.deepEqual(f.errors, []);
});

test('printing uses the frozen old page while generation continues, including after a print failure', async t => {
  const f = fixture(t, { printer: true });
  const main = f.page('main.html');
  const canvas = main.elements.get('canvas');
  f.requests[0].record(token('FIRST'));
  await until(() => canvas.textContent === 'FIRST');
  canvas.events.get('click')();
  f.requests[1].record(token('SECOND'));
  await until(() => canvas.textContent === 'SECOND' && f.captures.length === 1);
  assert.equal(f.captures[0].snapshot.textContent, 'FIRST');
  assert.equal(f.prints.length, 0, 'generation must proceed before printing completes');
  f.failPrinting();
  f.captures[0].finish();
  await until(() => f.prints.length === 1 && main.copies[0].removed);
  assert.equal(f.prints[0].image, 'data:image/png,FIRST');
  canvas.events.get('click')();
  f.requests[2].record(token('THIRD'));
  await until(() => canvas.textContent === 'THIRD' && f.captures.length === 2);
  assert.equal(f.captures[1].snapshot.textContent, 'SECOND');
  f.captures[1].finish();
  await until(() => f.prints.length === 2);
  assert.deepEqual(f.prints.map(p => p.image), ['data:image/png,FIRST', 'data:image/png,SECOND']);
});
