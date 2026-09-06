/* Tests for the in-page chat agent (backend/js/chat_agent.js).

   The agent is the resource-saving half of the collector: it lives in the
   page, parses each message container AT MOST ONCE (cached per DOM node),
   and hands Python either a cheap summary (state) or an explicit range
   (slice). Nothing else may walk the conversation.

   Per AGENT_RULES RULE 6 this runs the REAL shipped file, in Node, against
   the DOM stub in tests/dom_stub.js (which mirrors the saved chat pages).

   Run:  node tests/test_history_agent_js.js
*/
'use strict';
const fs = require('fs');
const path = require('path');
const { buildChat } = require('./dom_stub.js');

const SRC = fs.readFileSync(
  path.join(__dirname, '..', 'backend', 'js', 'chat_agent.js'), 'utf8');

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error((msg || 'eq') + '\n  got:  ' + ja + '\n  want: ' + jb);
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }

/** load the agent into a fresh page environment */
function load(spec) {
  const env = buildChat(spec);
  new Function('window', 'document', 'MutationObserver', 'setTimeout',
               'clearTimeout', SRC)(
    env.window, env.document, env.MutationObserver, env.setTimeout,
    env.clearTimeout);
  env.agent = env.window.__cvbAgent;
  ok(env.agent, 'the agent must publish window.__cvbAgent');
  return env;
}

const msg = (i, over) => Object.assign(
  { dir: i % 2 ? 'out' : 'in', from: i % 2 ? 'HiHoney' : 'На работе 25',
    text: 'line ' + i, time: '17:' + String(10 + (i % 50)) }, over || {});

const many = (n, over) => Array.from({ length: n }, (_, i) => msg(i, over));

// ── installation ─────────────────────────────────────────────────

t('installing twice keeps a single agent and a single observer', () => {
  const env = load({ messages: many(3) });
  const first = env.agent;
  new Function('window', 'document', 'MutationObserver', 'setTimeout',
               'clearTimeout', SRC)(
    env.window, env.document, env.MutationObserver, env.setTimeout,
    env.clearTimeout);
  ok(env.window.__cvbAgent === first, 'the agent must not be replaced');
  const live = env.observers.filter((o) => o.target).length;
  eq(live, 1, 'exactly one live MutationObserver');
});

t('the agent reports a version', () => {
  const env = load({ messages: [] });
  ok(typeof env.agent.version === 'number' && env.agent.version >= 1,
     'version must be a number');
});

// ── state ────────────────────────────────────────────────────────

t('state describes a private conversation', () => {
  const env = load({ partner: 'На работе 25', me: 'HiHoney',
                     messages: many(6) });
  const s = env.agent.state();
  ok(s.ok, 'state.ok');
  eq(s.tab, 'private');
  eq(s.partner, 'На работе 25');
  eq(s.me, 'HiHoney');
  eq(s.participants, 2);
  eq(s.count, 6);
  eq(s.agent, env.agent.version);
});

t('state is cheap: head and tail only, never every fingerprint', () => {
  const env = load({ messages: many(120) });
  const s = env.agent.state();
  ok(s.head.length > 0 && s.head.length <= 10, 'head is a short prefix');
  ok(s.tail.length > 0 && s.tail.length <= 50, 'tail is a short suffix');
  ok(s.head.length + s.tail.length < 120, 'state must not ship everything');
  ok(!('items' in s), 'state must not carry message bodies');
});

t('the tail fingerprints are the last messages, in order', () => {
  const env = load({ messages: many(8) });
  const s = env.agent.state();
  const all = env.agent.slice(0, 8).items.map((r) => r.fp);
  eq(s.tail, all.slice(-s.tail.length), 'tail must be the suffix');
  eq(s.head, all.slice(0, s.head.length), 'head must be the prefix');
});

t('a room tab is reported as such', () => {
  const env = load({ tab: 'room', messages: many(3), participants: 17 });
  const s = env.agent.state();
  eq(s.tab, 'room');
  eq(s.participants, 17);
});

t('switching tabs changes the reported partner', () => {
  const env = load({ messages: many(2) });
  eq(env.agent.state().tab, 'private');
  env.setTab('room');
  eq(env.agent.state().tab, 'room');
});

t('an empty conversation is still a valid state', () => {
  const env = load({ messages: [] });
  const s = env.agent.state();
  ok(s.ok, 'empty must not be an error');
  eq(s.count, 0);
  eq(s.tail, []);
});

// ── slice ────────────────────────────────────────────────────────

t('slice returns exactly the requested half-open range', () => {
  const env = load({ messages: many(10) });
  const res = env.agent.slice(3, 7);
  ok(res.ok, 'slice.ok');
  eq(res.items.length, 4);
  eq(res.items.map((r) => r.idx), [3, 4, 5, 6]);
  eq(res.items[0].text, 'line 3');
});

t('slice clamps out-of-range bounds instead of throwing', () => {
  const env = load({ messages: many(4) });
  eq(env.agent.slice(-5, 99).items.length, 4);
  eq(env.agent.slice(9, 99).items.length, 0);
  eq(env.agent.slice(3, 1).items.length, 0);
});

t('records carry direction, author, time and text', () => {
  const env = load({ messages: [
    { dir: 'in', from: 'На работе 25', text: 'повезло ученикам))', time: '17:31' },
    { dir: 'out', from: 'HiHoney', text: 'да', time: '17:32' },
  ] });
  const items = env.agent.slice(0, 2).items;
  eq(items[0].dir, 'in');
  eq(items[0].from, 'На работе 25');
  eq(items[0].text, 'повезло ученикам))');
  eq(items[0].time, '17:31');
  eq(items[0].kind, 'text');
  eq(items[0].media, null);
  eq(items[1].dir, 'out');
});

t('images and gifs become media records with no text', () => {
  const env = load({ messages: [
    { dir: 'in', from: 'Nick', media: 'https://cdn.example/pic.jpg' },
    { dir: 'in', from: 'Nick', media: 'https://cdn.example/anim.gif?x=1' },
  ] });
  const items = env.agent.slice(0, 2).items;
  eq(items[0].kind, 'image');
  eq(items[0].media.url, 'https://cdn.example/pic.jpg');
  eq(items[0].text, '');
  eq(items[1].kind, 'gif', 'a .gif url must be recognised as animated');
  eq(items[1].media.url, 'https://cdn.example/anim.gif?x=1');
});

t('identical neighbours get increasing occurrence numbers', () => {
  const env = load({ messages: [
    { dir: 'in', from: 'Nick', text: 'ok', time: '17:31' },
    { dir: 'in', from: 'Nick', text: 'ok', time: '17:31' },
    { dir: 'in', from: 'Nick', text: 'ok', time: '17:31' },
  ] });
  const items = env.agent.slice(0, 3).items;
  eq(items.map((r) => r.occ), [0, 1, 2]);
  eq(new Set(items.map((r) => r.fp)).size, 3, 'fingerprints must differ');
});

t('occurrence numbers are absolute, not relative to the slice', () => {
  const env = load({ messages: [
    { dir: 'in', from: 'Nick', text: 'ok', time: '17:31' },
    { dir: 'in', from: 'Nick', text: 'ok', time: '17:31' },
    { dir: 'in', from: 'Nick', text: 'ok', time: '17:31' },
  ] });
  eq(env.agent.slice(2, 3).items[0].occ, 2,
     'the third "ok" is occurrence 2 even when sliced alone');
});

// ── the fingerprint is shared with Python ────────────────────────

t('fingerprints match the Python implementation', () => {
  const env = load({ messages: [] });
  const f = env.agent.fingerprint;
  eq(f('in', 'Nick', '17:31', 'text', 'ok', 0), 'aba33d4f685b38b8');
  eq(f('in', 'Nick', '17:31', 'text', 'ok', 1), 'aaa33bbc4458c175');
  eq(f('out', 'HiHoney', '17:31', 'text', 'повезло ученикам))', 0),
     'a2fd79fbc97ac5a4');
  eq(f('in', 'Хочу_милфочку', '18:00', 'gif', 'https://x/y.gif', 0),
     'e8556ce6637277bf');
});

t('a message fingerprint equals fingerprint() of its own fields', () => {
  const env = load({ messages: [msg(0)] });
  const r = env.agent.slice(0, 1).items[0];
  eq(r.fp, env.agent.fingerprint(r.dir, r.from, r.time, r.kind,
                                 r.media ? r.media.url : r.text, r.occ));
});

// ── the parse cache (the whole point of the design) ──────────────

t('each DOM node is parsed once, however often it is read', () => {
  const env = load({ messages: many(20) });
  env.agent.slice(0, 20);
  const after = env.agent.stats().parsed;
  env.agent.state();
  env.agent.slice(0, 20);
  env.agent.slice(5, 10);
  eq(env.agent.stats().parsed, after, 'no message may be parsed twice');
});

t('only the newly appended nodes are parsed', () => {
  const env = load({ messages: many(20) });
  env.agent.slice(0, 20);
  const before = env.agent.stats().parsed;
  env.append(msg(20), msg(21));
  env.agent.state();
  eq(env.agent.stats().parsed - before, 2, 'exactly the two new nodes');
});

t('prepended history is parsed once and shifts the indices', () => {
  const env = load({ messages: many(5) });
  const firstFp = env.agent.slice(0, 1).items[0].fp;
  const before = env.agent.stats().parsed;
  env.prepend(msg(90), msg(91));
  eq(env.agent.state().count, 7);
  eq(env.agent.stats().parsed - before, 2, 'only the prepended nodes');
  eq(env.agent.slice(2, 3).items[0].fp, firstFp, 'the old first is now idx 2');
});

t('the cache does not leak when the virtual scroller trims the top', () => {
  const env = load({ messages: many(30) });
  env.agent.slice(0, 30);
  env.trim(10);
  const s = env.agent.state();
  eq(s.count, 10);
  ok(env.agent.stats().cached <= 30, 'cache must be bounded by the DOM');
});

// ── the push channel ─────────────────────────────────────────────

t('new messages are pushed to Python, debounced', () => {
  const env = load({ messages: many(2) });
  env.agent.state();
  env.append(msg(2), msg(3));
  eq(env.pushes.length, 0, 'the push must be debounced, not immediate');
  env.flushTimers();
  eq(env.pushes.length, 1, 'one coalesced push for both messages');
  const payload = JSON.parse(env.pushes[0]);
  eq(payload.kind, 'append');
  eq(payload.count, 4, 'the new DOM length');
  eq(payload.items.length, 2);
  eq(payload.items[1].text, 'line 3');
  eq(payload.partner, 'На работе 25');
});

t('a push carries the same fingerprints a slice would', () => {
  const env = load({ messages: many(2) });
  env.append(msg(2));
  env.flushTimers();
  const pushed = JSON.parse(env.pushes[0]).items[0];
  eq(pushed.fp, env.agent.slice(2, 3).items[0].fp);
});

t('drain returns the buffered records and empties the buffer', () => {
  const env = load({ messages: many(2) });
  env.append(msg(2), msg(3));
  const first = env.agent.drain();
  ok(first.ok, 'drain.ok');
  eq(first.items.length, 2);
  eq(env.agent.drain().items.length, 0, 'the buffer must be cleared');
});

t('state reports how many records are waiting in the buffer', () => {
  const env = load({ messages: many(2) });
  env.append(msg(2), msg(3));
  eq(env.agent.state().pending, 2);
  env.agent.drain();
  eq(env.agent.state().pending, 0);
});

t('the buffer is bounded and reports what it dropped', () => {
  const env = load({ messages: [] });
  for (let i = 0; i < 600; i++) env.append(msg(i));
  const res = env.agent.drain();
  ok(res.items.length <= 500, 'the buffer must be capped');
  ok(res.dropped > 0, 'dropping must be reported, not silent');
});

t('a missing push hook never breaks the observer', () => {
  const env = load({ messages: many(2) });
  delete env.window.__cvbPush;
  env.append(msg(2));
  env.flushTimers();               // must not throw
  eq(env.agent.state().pending, 1, 'the record is still buffered');
});

t('uninstall stops the observer and slice still works', () => {
  const env = load({ messages: many(2) });
  env.agent.uninstall();
  eq(env.observers.filter((o) => o.target).length, 0, 'observer disconnected');
  env.append(msg(2));
  env.flushTimers();
  eq(env.pushes.length, 0, 'no pushes after uninstall');
  eq(env.agent.slice(0, 9).items.length, 3, 'reading still works');
});

// ── hostile input ────────────────────────────────────────────────

t('a message with no author or text does not break the walk', () => {
  const env = load({ messages: many(2) });
  const broken = env.messagesRoot.children[0]
    .querySelector('div.message-container');
  broken.querySelector('p.message').children = [];
  const items = env.agent.slice(0, 2).items;
  eq(items.length, 2, 'the broken node must still be represented');
  eq(items[0].from, '');
  ok(typeof items[0].fp === 'string' && items[0].fp.length > 0,
     'even a broken node gets a fingerprint');
});

t('a page with no chat at all reports not-ok instead of throwing', () => {
  const env = load({ messages: [] });
  env.document.querySelector = () => null;
  env.document.querySelectorAll = () => [];
  const s = env.agent.state();
  ok(s.ok === false, 'state.ok must be false');
  ok(typeof s.reason === 'string' && s.reason.length > 0, 'reason given');
});

t('text is never interpreted as html', () => {
  const env = load({ messages: [
    { dir: 'in', from: 'Nick', text: '<img src=x onerror=alert(1)>' },
  ] });
  eq(env.agent.slice(0, 1).items[0].text, '<img src=x onerror=alert(1)>');
});

// ── reporting ────────────────────────────────────────────────────

console.log('history_agent_js: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
