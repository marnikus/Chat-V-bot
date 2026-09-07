/* Bug #1 — the in-page agent must never mix two conversations.

   The site keeps every open chat alive in the DOM: the main room pane plus
   one pane per private tab. The old agent walked
   `document.querySelectorAll('div.message-container')`, so ROOM messages
   (from anybody) were handed to Python and archived under the private
   partner — exactly what the bug report shows.

   The agent must therefore:
     * parse only the pane that is on screen;
     * report the distinct nicks it saw, split by direction, so Python can
       apply the two-step gate (only my nick + the partner);
     * report the active tab title, so Python can check step two;
     * follow the user when they switch tabs (observer re-attaches, buffered
       lines of the old pane are dropped).

   Run:  node tests/test_private_scope_js.js
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

const PARTNER = 'Ански';
const ME = 'Хорошо Все';

const priv = [
  { dir: 'in', from: PARTNER, text: 'привет', time: '11:55' },
  { dir: 'out', from: ME, text: 'привет :)', time: '11:58' },
];
const room = [
  { dir: 'in', from: 'Макс__Б', text: 'всем привет', time: '11:57' },
  { dir: 'in', from: 'Lizalo4ka', text: 'ку', time: '11:57' },
];

// ── version ──────────────────────────────────────────────────────

t('the agent version was bumped for the scoped parser', () => {
  const env = load({ messages: [] });
  ok(env.agent.version >= 6,
     'a page still running the old agent must be re-installed');
});

// ── pane scoping ─────────────────────────────────────────────────

t('only the visible pane is parsed when the room pane is still in the DOM', () => {
  const env = load({ partner: PARTNER, me: ME, messages: priv });
  env.addPane(room, { hidden: true });          // the room, kept alive, hidden
  const st = env.agent.state();
  eq(st.count, 2, 'the room pane must not be counted');
  eq(st.panes, 2, 'the agent still knows both panes exist');
  eq(st.in_authors, [PARTNER], 'only the partner wrote inbound lines');
  eq(st.out_authors, [ME], 'my nick is the only outbound author');
  eq(st.authors, [PARTNER, ME], 'exactly two nicks in this conversation');
});

t('a visible room pane never wins over the active private pane', () => {
  // The live regression: the room pane is still "measurably visible" (not
  // display:none) and is much longer, but the active tab is the private chat.
  const env = load({ partner: PARTNER, me: ME, messages: priv });
  const bigRoom = [];
  for (let i = 0; i < 40; i++) {
    bigRoom.push({ dir: 'in', from: i % 2 ? 'Макс__Б' : 'Lizalo4ka',
                   text: 'room ' + i, time: '12:0' + (i % 10) });
  }
  // The room pane is NOT hidden (the bug report shows it being picked).
  env.addPane(bigRoom, { hidden: false });
  const st = env.agent.state();
  eq(st.tab, 'private', 'the active tab stays private');
  eq(st.count, 2, 'the active private pane is parsed');
  eq(st.in_authors, [PARTNER], 'room authors are not reported as partners');
  eq(st.out_authors, [ME], 'only my nick writes outbound lines');
  eq(st.authors, [PARTNER, ME], 'exactly two nicks in this conversation');
});

t('among private panes, the one matching the active partner wins', () => {
  const env = load({ partner: PARTNER, me: ME, messages: priv });
  const other = [
    { dir: 'in', from: 'Аня', text: 'привет', time: '12:00' },
    { dir: 'out', from: ME, text: 'привет)', time: '12:01' },
  ];
  // Another open private chat, visible by the site's own measurement.
  env.addPane(other, { hidden: false });
  const st = env.agent.state();
  eq(st.count, 2, 'the AlisskaBi pane is parsed');
  eq(st.in_authors, [PARTNER], 'Аня is not mixed into the active chat');
  eq(st.out_authors, [ME]);
});

t('slice() ships the visible pane too', () => {
  const env = load({ partner: PARTNER, me: ME, messages: priv });
  env.addPane(room, { hidden: true });
  const sliced = env.agent.slice(0, 99);
  eq(sliced.count, 2, 'slice counts the visible pane only');
  eq(sliced.items.map((i) => i.from), [PARTNER, ME], 'no room authors');
});

t('a room pane that IS visible is parsed with its many authors', () => {
  const env = load({ tab: 'room', partner: PARTNER, me: ME,
                     messages: room.concat([
                       { dir: 'in', from: PARTNER, text: 'и я тут', time: '11:58' },
                     ]) });
  const st = env.agent.state();
  eq(st.tab, 'room', 'the room tab is reported as a room');
  eq(st.in_authors, ['Макс__Б', 'Lizalo4ka', PARTNER],
     'the room has many authors');
  ok(st.authors.length > 2, 'more than two nicks ⇒ Python refuses to save');
});

t('a private pane with a third author is reported honestly', () => {
  const env = load({ partner: PARTNER, me: ME,
                     messages: priv.concat([
                       { dir: 'in', from: 'Макс__Б', text: 'ку', time: '11:59' },
                     ]) });
  const st = env.agent.state();
  eq(st.in_authors, [PARTNER, 'Макс__Б'], 'the stranger is visible to Python');
});

// ── the tab title (step two of the gate) ─────────────────────────

t('state() reports the active tab title', () => {
  const env = load({ partner: PARTNER, me: ME, messages: priv });
  eq(env.agent.state().title, PARTNER, 'the trimmed chat-title');
  eq(env.agent.state().partner, PARTNER, 'partner mirrors the title');
});

t('a trailing space in the tab title is trimmed away', () => {
  const env = load({ partner: PARTNER, me: ME, messages: priv,
                     title: PARTNER + ' ' });
  eq(env.agent.state().title, PARTNER, 'chat-title own text is trimmed');
});

t('switching to the room tab reports the room, not the last partner', () => {
  const env = load({ partner: PARTNER, me: ME, messages: priv });
  env.setTab('room');
  eq(env.agent.state().tab, 'room', 'the tab classification follows the UI');
});

// ── the push channel ─────────────────────────────────────────────

t('the push payload carries authors and the tab title', () => {
  const env = load({ partner: PARTNER, me: ME, messages: priv });
  env.append({ dir: 'in', from: PARTNER, text: 'ты тут?', time: '12:01' });
  env.flushTimers();
  eq(env.pushes.length, 1, 'one debounced push');
  const payload = JSON.parse(env.pushes[0]);
  eq(payload.tab, 'private', 'the pane classification travels with the push');
  eq(payload.title, PARTNER, 'so does the tab title');
  eq(payload.in_authors, [PARTNER], 'inbound authors');
  eq(payload.out_authors, [ME], 'outbound authors');
  eq(payload.items.map((i) => i.from), [PARTNER], 'only the new line');
});

t('lines appended to a hidden pane never reach the push buffer', () => {
  const env = load({ partner: PARTNER, me: ME, messages: priv });
  const other = env.addPane(room, { hidden: true });
  other.append({ dir: 'in', from: 'Макс__Б', text: 'опять я', time: '12:02' });
  env.flushTimers();
  eq(env.pushes.length, 0, 'the hidden pane is not observed at all');
  eq(env.agent.state().count, 2, 'and it is not parsed either');
});

t('switching panes re-attaches the observer and drops the old buffer', () => {
  const env = load({ partner: PARTNER, me: ME, messages: priv });
  const other = env.addPane(room, { hidden: true });
  env.append({ dir: 'in', from: PARTNER, text: 'ещё', time: '12:03' });
  // the user switches to the room: the private pane goes away, the room shows
  env.hideMainPane();
  other.show();
  env.setTab('room');
  const st = env.agent.state();             // probing re-attaches the observer
  eq(st.count, 2, 'the room pane is what we see now');
  eq(st.in_authors, ['Макс__Б', 'Lizalo4ka'], 'and its authors are the room’s');
  eq(env.agent.drain().items.length, 0,
     'lines buffered for the previous pane are discarded, not re-attributed');
  other.append({ dir: 'in', from: 'Lizalo4ka', text: 'ку-ку', time: '12:04' });
  env.flushTimers();
  const payload = JSON.parse(env.pushes[env.pushes.length - 1]);
  ok(payload.in_authors.indexOf('Lizalo4ka') >= 0,
     'the push now describes the room pane');
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
