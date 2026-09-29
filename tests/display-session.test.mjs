import test from 'node:test';
import assert from 'node:assert/strict';
import { setImmediate as flush } from 'node:timers/promises';
import { DisplaySession, observeDisplaySession } from '../display-session.mjs';

// An asynchronous in-memory BroadcastChannel adapter, with browser-like copies.
function channels() {
  const peers = new Set();
  return () => {
    const listeners = new Set();
    const peer = {
      addEventListener: (_, listener) => listeners.add(listener),
      removeEventListener: (_, listener) => listeners.delete(listener),
      postMessage(message) {
        for (const target of peers) {
          if (target === peer) continue;
          const data = structuredClone(message);
          queueMicrotask(() => target.deliver(data));
        }
      },
      deliver(data) { for (const listener of listeners) listener({ data }); },
      close() { peers.delete(peer); listeners.clear(); },
    };
    peers.add(peer);
    return peer;
  };
}

const encoder = new TextEncoder();
const line = record => JSON.stringify(record) + '\n';

function setup(t, { overflow = () => false, random = () => 0, savePage, fetch } = {}) {
  const channel = channels();
  const requests = [];
  const views = [];
  const saved = [];
  const errors = [];
  const session = new DisplaySession({
    channel: channel(), random,
    render(text) { views.push(text); return overflow(text); },
    savePage: savePage ?? (text => saved.push(text)),
    onError: error => errors.push(error),
    fetch: fetch ?? (async (url, options) => {
      let controller;
      let ended = false;
      const body = new ReadableStream({
        start(value) { controller = value; },
        cancel() { ended = true; },
      });
      options.signal.addEventListener('abort', () => {
        if (!ended) {
          ended = true;
          controller.error(new DOMException('Aborted', 'AbortError'));
        }
      });
      requests.push({
        url, options,
        bytes: bytes => controller.enqueue(bytes),
        text: text => controller.enqueue(encoder.encode(text)),
        record: record => controller.enqueue(encoder.encode(line(record))),
        end() { if (!ended) { ended = true; controller.close(); } },
      });
      return new Response(body);
    }),
  });
  t.after(() => session.close());
  function monitor() {
    const events = [];
    const close = observeDisplaySession({
      channel: channel(),
      onReset: settings => events.push({ type: 'reset', settings }),
      onToken: record => events.push({ type: 'token', record }),
    });
    t.after(close);
    return events;
  }
  return { session, requests, views, saved, errors, monitor };
}

test('a record split at every byte position displays exactly once, including Unicode and special tokens', async t => {
  const record = { text: '字🙂<|endoftext|>', count: 1, candidates: [{ token: '字', prob: 0.7 }] };
  const bytes = encoder.encode(line(record));
  for (let cut = 1; cut < bytes.length; cut++) {
    const h = setup(t);
    const monitor = h.monitor();
    const completed = h.session.restart();
    h.requests[0].bytes(bytes.slice(0, cut));
    h.requests[0].bytes(bytes.slice(cut));
    h.requests[0].end();
    await completed;
    await flush();
    assert.equal(h.views.at(-1), record.text, `byte split ${cut}`);
    assert.deepEqual(monitor.filter(e => e.type === 'token').map(e => e.record), [record]);
    assert.deepEqual(h.errors, []);
    h.session.close();
  }
});

test('multiple records and a final record without a newline are all retained', async t => {
  const h = setup(t);
  const completed = h.session.restart();
  h.requests[0].text(line({ text: 'A', count: 0 }) + '\n' + line({ text: ' B', count: 1 }) + JSON.stringify({ text: ' C', count: 2 }));
  h.requests[0].end();
  await completed;
  assert.equal(h.views.at(-1), 'A B C');
  assert.deepEqual(h.errors, []);
});

test('overflow saves the old page once and drops remaining old records before the next round', async t => {
  const h = setup(t, { overflow: text => text === 'OLD' });
  const monitor = h.monitor();
  const completed = h.session.restart();
  h.requests[0].text(line({ text: 'OLD', count: 1 }) + line({ text: 'LEAK', count: 2 }));
  await completed;
  await flush();
  assert.equal(h.requests.length, 2);
  assert.deepEqual(h.saved, ['OLD']);
  assert.equal(h.views.at(-1), '');
  h.requests[1].record({ text: 'NEW', count: 0 });
  h.requests[1].end();
  await flush();
  assert.equal(h.views.at(-1), 'NEW');
  assert.deepEqual(monitor.map(e => e.type === 'reset' ? 'reset' : e.record.text), ['reset', 'OLD', 'reset', 'NEW']);
  assert.ok(!h.views.some(text => text.includes('LEAK')));
  assert.deepEqual(h.errors, []);
});

test('rapid restarts ignore late responses even when transport does not honor cancellation', async t => {
  const pending = [];
  const h = setup(t, { fetch: () => new Promise(resolve => pending.push(resolve)) });
  const monitor = h.monitor();
  const first = h.session.restart();
  const second = h.session.restart();
  const third = h.session.restart();
  pending[2](new Response(line({ text: 'LATEST', count: 0 })));
  await third;
  pending[0](new Response(line({ text: 'STALE-A', count: 0 })));
  pending[1](new Response(line({ text: 'STALE-B', count: 0 })));
  await Promise.all([first, second]);
  await flush();
  assert.equal(h.views.at(-1), 'LATEST');
  assert.deepEqual(h.saved, []);
  assert.deepEqual(monitor.filter(e => e.type === 'token').map(e => e.record.text), ['LATEST']);
  assert.deepEqual(h.errors, []);
});

test('a monitor opened midway immediately receives current settings and the latest token only', async t => {
  const h = setup(t);
  const completed = h.session.restart();
  h.requests[0].record({ text: 'A', count: 0 });
  h.requests[0].record({ text: ' B', count: 1, candidates: [{ token: ' B', prob: 0.8 }], final_prob: 0.8 });
  await flush();
  const monitor = h.monitor();
  await flush();
  assert.equal(monitor[0].type, 'reset');
  assert.deepEqual(monitor[0].settings, { temp: 0.5, context: 10, delay: 1 });
  assert.deepEqual(monitor.filter(e => e.type === 'token').map(e => e.record.text), [' B']);
  h.requests[0].record({ text: ' C', count: 2 });
  h.requests[0].end();
  await completed;
  await flush();
  assert.deepEqual(monitor.filter(e => e.type === 'token').map(e => e.record.text), [' B', ' C']);
  assert.equal(h.requests.length, 1, 'joining a monitor must not start a generation request');
});

test('memory flush text remains in the same display round', async t => {
  const h = setup(t);
  const monitor = h.monitor();
  const completed = h.session.restart();
  h.requests[0].record({ text: 'old text', count: 3999 });
  h.requests[0].record({ text: '\n\n[AUTO-RESET: MEMORY FLUSH]\nZ', count: 0 });
  h.requests[0].record({ text: 'ebra', count: 1 });
  h.requests[0].end();
  await completed;
  await flush();
  assert.equal(h.views.at(-1), 'old text\n\n[AUTO-RESET: MEMORY FLUSH]\nZebra');
  assert.equal(monitor.filter(e => e.type === 'reset').length, 1);
  assert.deepEqual(h.saved, []);
});

test('page capture happens before clearing and capture failure cannot stop the next round', async t => {
  let h;
  const seen = [];
  h = setup(t, { savePage(text) { seen.push([text, h.views.at(-1)]); throw new Error('Printer unavailable'); } });
  const first = h.session.restart();
  h.requests[0].record({ text: 'FINISHED PAGE', count: 1 });
  h.requests[0].end();
  await first;
  const second = h.session.restart();
  assert.deepEqual(seen, [['FINISHED PAGE', 'FINISHED PAGE']]);
  h.requests[1].record({ text: 'NEXT PAGE', count: 0 });
  h.requests[1].end();
  await second;
  assert.equal(h.views.at(-1), 'NEXT PAGE');
  assert.equal(h.errors.length, 1);
});

test('temperature still controls the requested delay with a 10-token context', async t => {
  const h = setup(t, { random: () => 1 });
  const completed = h.session.restart();
  const settings = JSON.parse(h.requests[0].options.body);
  assert.equal(settings.temp, 1.5);
  assert.equal(settings.context, 10);
  assert.equal(settings.reset, true);
  assert.ok(Math.abs(settings.delay - 0.1) < 1e-9);
  h.requests[0].end();
  await completed;
});

test('malformed records report an error instead of silently dropping text and continuing', async t => {
  const h = setup(t);
  const completed = h.session.restart();
  h.requests[0].text(line({ text: 'A', count: 0 }) + 'broken JSON\n' + line({ text: 'B', count: 1 }));
  h.requests[0].end();
  await completed;
  assert.equal(h.views.at(-1), 'A');
  assert.equal(h.errors.length, 1);
});
