/* Boot + behaviour test for the two AI windows (ui/js/bot-chat.js,
   ui/js/bot-prompt.js).

   The REAL shipped modules are wired to the REAL element ids of
   ui/index.html and driven the way the QWebChannel bridge drives them:
   a slot is called with a request id, the answer arrives on a signal.

   It fails if a module reaches for an element the page does not have,
   if a bridge slot is called with the wrong shape, and — the acceptance
   criteria that matter most — if approving a suggestion were enough to
   send it, or if a rejected suggestion offered no retry.

   Run:  node tests/test_bot_chat_js.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f),
                                      'utf8');
const html = readUi('index.html');

// ── DOM stub ─────────────────────────────────────────────────────

function mkEl(tag) {
  const listeners = {};
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    _text: '', children: [], parentNode: null, style: {}, dataset: {},
    attrs: {}, title: '', value: '', type: '', disabled: false, listeners,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { on ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    get className() { return [...el.classList._set].join(' '); },
    set className(v) {
      el.classList._set = new Set(String(v).split(/\s+/).filter(Boolean));
    },
    get textContent() {
      return el._text + el.children.map((c) => c.textContent).join('');
    },
    set textContent(v) { el._text = String(v); el.children = []; },
    set innerHTML(v) { throw new Error('markup assignment is forbidden'); },
    appendChild(c) { el.children.push(c); c.parentNode = el; return c; },
    removeChild(c) {
      el.children = el.children.filter((n) => n !== c);
      c.parentNode = null;
      return c;
    },
    remove() { if (el.parentNode) el.parentNode.removeChild(el); },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    scrollIntoView() {},
    closest(sel) {
      let node = el;
      while (node) { if (matches(node, sel)) return node; node = node.parentNode; }
      return null;
    },
    querySelector(sel) { return findAll(el, sel)[0] || null; },
    querySelectorAll(sel) { return findAll(el, sel); },
    fire(ev, extra) {
      (listeners[ev] || []).forEach((fn) => fn(Object.assign(
        { target: el, preventDefault() {}, stopPropagation() {} },
        extra || {})));
    },
  };
  return el;
}

function matches(node, sel) {
  const s = String(sel).trim();
  if (s.startsWith('.')) return node.classList.contains(s.slice(1));
  return node.tagName === s.toUpperCase();
}
function walk(el, out) {
  out = out || [];
  el.children.forEach((c) => { out.push(c); walk(c, out); });
  return out;
}
function findAll(el, sel) {
  return walk(el).filter((n) => matches(n, String(sel).trim().split(/\s+/).pop()));
}

const byId = {};
global.document = {
  body: mkEl('body'),
  createElement: mkEl,
  getElementById(id) {
    if (!(id in byId)) byId[id] = html.includes('id="' + id + '"')
      ? mkEl('div') : null;
    return byId[id];
  },
  addEventListener() {},
};
global.window = global;

// ── bridge stub ──────────────────────────────────────────────────

const calls = [];
let REACTION = { nick: 'Anna', active: '', available: [
  { id: 'positive', name: 'Positive first reaction', color: '#00c853' },
  { id: 'negative', name: 'Negative first reaction', color: '#ff3b30' },
  { id: 'uncertain', name: 'Uncertain first reaction', color: '#ffcc00' }] };
const PROMPTS = [
  { id: 'suggest_reply', title: 'Suggest next message', text: 'ask {nick}',
    default: 'ask {nick}', edited: false },
  { id: 'analyze_reaction', title: "Analyze person's reaction",
    text: 'judge {last_message}', default: 'judge {last_message}',
    edited: false }];

const slot = (name) => (...args) => {
  calls.push({ name, args });
  const last = args[args.length - 1];
  if (typeof last === 'function') last('');
};
global.App = {
  bridge: {
    bot_load_today: slot('bot_load_today'),
    bot_suggest_reply: slot('bot_suggest_reply'),
    bot_analyze_reaction: slot('bot_analyze_reaction'),
    bot_preview_prompt: slot('bot_preview_prompt'),
    bot_send_message: slot('bot_send_message'),
    bot_reaction_state: (nick, cb) => {
      calls.push({ name: 'bot_reaction_state', args: [nick] });
      cb(JSON.stringify(REACTION));
    },
    bot_apply_reaction: (nick, reaction, cb) => {
      calls.push({ name: 'bot_apply_reaction', args: [nick, reaction] });
      REACTION = Object.assign({}, REACTION, { active: reaction,
                                               changed: true });
      cb(JSON.stringify(REACTION));
    },
    bot_get_prompts: (cb) => {
      calls.push({ name: 'bot_get_prompts', args: [] });
      cb(JSON.stringify(PROMPTS));
    },
    bot_save_prompt: (id, text, cb) => {
      calls.push({ name: 'bot_save_prompt', args: [id, text] });
      cb(true);
    },
    bot_reset_prompt: (id, cb) => {
      calls.push({ name: 'bot_reset_prompt', args: [id] });
      cb(true);
    },
  },
};
global.LogConsole = { log() {} };

const load = (file, name) =>
  new Function(readUi(file) + '\nreturn ' + name + ';')();
global.BotChat = load('js/bot-chat.js', 'BotChat');
global.BotPrompt = load('js/bot-prompt.js', 'BotPrompt');

// ── assertion kit ────────────────────────────────────────────────

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'expected truthy'); }
function eq(a, b, msg) {
  const sa = JSON.stringify(a), sb = JSON.stringify(b);
  if (sa !== sb) throw new Error((msg || 'mismatch') + '\n   got ' + sa +
                                 '\n   want ' + sb);
}
const $ = (id) => document.getElementById(id);
const lastCall = (name) => calls.filter((c) => c.name === name).pop();
const reply = (id, payload) => BotChat.onReply(id, JSON.stringify(payload));
const cards = () => $('botChatBox').children.filter(
  (c) => c.classList.contains('bot-card'));

// ── boot ─────────────────────────────────────────────────────────

BotChat.init();
BotPrompt.init();

t('every element the AI windows reach for exists in index.html', () => {
  ['winBotChat', 'botChatBox', 'botReactionLabels', 'botSendApprovedBtn',
   'botDirectInput', 'botSendDirectBtn', 'botChatStatus', 'winBotPrompt',
   'botPromptTabs', 'botPromptText', 'botPromptPreview'].forEach((id) =>
    ok($(id), id + ' is missing from ui/index.html'));
});

t('the Send to Person button starts disabled', () => {
  ok($('botSendApprovedBtn').disabled, 'send must start disabled');
});

t('opening a person loads today and asks for the label state', () => {
  BotChat.openPerson('Anna');
  eq(lastCall('bot_load_today').args[1], 'Anna');
  eq(lastCall('bot_reaction_state').args[0], 'Anna');
  eq($('botChatPerson').textContent, 'Anna');
});

t('three colour-coded labels render, none active', () => {
  const pills = $('botReactionLabels').children;
  eq(pills.length, 3);
  eq(pills.filter((p) => p.classList.contains('active')).length, 0);
});

t("today's messages render oldest first", () => {
  reply(lastCall('bot_load_today').args[0],
        { nick: 'Anna', day: '2026-09-13', empty: false,
          items: [{ dir: 'out', from: 'me', text: 'hi' },
                  { dir: 'in', from: 'Anna', text: 'hello you' }] });
  const box = $('botChatBox');
  eq(box.children.length, 2);
  ok(box.children[0].classList.contains('out'));
  ok(box.textContent.indexOf('hello you') >= 0);
});

t('an empty day says so instead of looking broken', () => {
  BotChat.openPerson('Nobody');
  reply(lastCall('bot_load_today').args[0],
        { nick: 'Nobody', day: '2026-09-13', empty: true, items: [] });
  ok(/no messages/i.test($('botChatStatus').textContent),
     'the empty state must be explained');
  BotChat.openPerson('Anna');
  reply(lastCall('bot_load_today').args[0],
        { nick: 'Anna', empty: false, items: [] });
});

// ── suggested reply: approve / send / reject / retry ─────────────

t('a suggestion renders as a pending card', () => {
  $('botSuggestBtn').fire('click');
  eq(lastCall('bot_suggest_reply').args[1], 'Anna');
  reply(lastCall('bot_suggest_reply').args[0],
        { nick: 'Anna', text: 'See you tomorrow?', state: 'pending' });
  const card = cards().pop();
  ok(card.classList.contains('pending'), 'the card must be pending');
  ok(card.textContent.indexOf('See you tomorrow?') >= 0);
});

t('approving does NOT send — it only enables the Send button', () => {
  const before = calls.filter((c) => c.name === 'bot_send_message').length;
  cards().pop().querySelector('.bot-approve').fire('click');
  eq(calls.filter((c) => c.name === 'bot_send_message').length, before,
     'approval must not deliver anything');
  ok(!$('botSendApprovedBtn').disabled, 'send must now be enabled');
});

t('clicking Send to Person delivers the approved text', () => {
  $('botSendApprovedBtn').fire('click');
  eq(lastCall('bot_send_message').args[2], 'See you tomorrow?');
  BotChat.onReply(lastCall('bot_send_message').args[0],
                  JSON.stringify('See you tomorrow?'));
  ok($('botSendApprovedBtn').disabled,
     'the button must disarm once the message is gone');
});

t('rejecting offers a retry that asks Grok again', () => {
  $('botSuggestBtn').fire('click');
  reply(lastCall('bot_suggest_reply').args[0],
        { nick: 'Anna', text: 'Another try', state: 'pending' });
  const card = cards().pop();
  card.querySelector('.bot-reject').fire('click');
  ok(card.classList.contains('rejected'));
  ok(!card.querySelector('.bot-approve'), 'the verify row must be gone');
  const before = calls.filter((c) => c.name === 'bot_suggest_reply').length;
  card.querySelector('.bot-retry').fire('click');
  eq(calls.filter((c) => c.name === 'bot_suggest_reply').length, before + 1);
});

t('rejecting an approved suggestion disables sending again', () => {
  $('botSuggestBtn').fire('click');
  reply(lastCall('bot_suggest_reply').args[0],
        { nick: 'Anna', text: 'Third', state: 'pending' });
  const card = cards().pop();
  card.querySelector('.bot-approve').fire('click');
  ok(!$('botSendApprovedBtn').disabled);
  card.querySelector('.bot-reject').fire('click');
  ok($('botSendApprovedBtn').disabled, 'a rejected suggestion cannot be sent');
});

// ── direct custom message ────────────────────────────────────────

t('a direct message is sent without any AI involvement', () => {
  const aiBefore = calls.filter((c) => c.name === 'bot_suggest_reply').length;
  $('botDirectInput').value = 'my own words';
  $('botSendDirectBtn').fire('click');
  eq(lastCall('bot_send_message').args[2], 'my own words');
  eq(calls.filter((c) => c.name === 'bot_suggest_reply').length, aiBefore);
});

t('every send names the person, so the backend can refuse a wrong chat', () => {
  // The window's person and the browser's open tab drift apart the moment
  // anyone clicks another chat; the nick is what lets the backend notice.
  $('botDirectInput').value = 'for Anna only';
  $('botSendDirectBtn').fire('click');
  eq(lastCall('bot_send_message').args[1], 'Anna', 'direct send carries nick');
  $('botSuggestBtn').fire('click');
  reply(lastCall('bot_suggest_reply').args[0],
        { nick: 'Anna', text: 'Approved one', state: 'pending' });
  cards().pop().querySelector('.bot-approve').fire('click');
  $('botSendApprovedBtn').fire('click');
  eq(lastCall('bot_send_message').args[1], 'Anna', 'AI send carries nick too');
});

t('an empty direct message is refused', () => {
  const before = calls.filter((c) => c.name === 'bot_send_message').length;
  $('botDirectInput').value = '   ';
  $('botSendDirectBtn').fire('click');
  eq(calls.filter((c) => c.name === 'bot_send_message').length, before);
});

// ── reaction analysis ────────────────────────────────────────────

t('an analysis renders pending and applies no label by itself', () => {
  const before = calls.filter((c) => c.name === 'bot_apply_reaction').length;
  $('botAnalyzeBtn').fire('click');
  reply(lastCall('bot_analyze_reaction').args[0],
        { nick: 'Anna', reaction: 'positive', reason: 'warm answer',
          state: 'pending' });
  const card = cards().pop();
  ok(card.classList.contains('reaction-positive'));
  eq(calls.filter((c) => c.name === 'bot_apply_reaction').length, before,
     'no label may be applied before the user confirms');
});

t('confirming applies exactly one label', () => {
  cards().pop().querySelector('.bot-approve').fire('click');
  eq(lastCall('bot_apply_reaction').args, ['Anna', 'positive']);
  const pills = $('botReactionLabels').children;
  eq(pills.filter((p) => p.classList.contains('active')).length, 1);
  ok(pills.filter((p) => p.dataset.reaction === 'positive')[0]
       .classList.contains('active'));
});

t('a manual click on another label replaces the active one', () => {
  const host = $('botReactionLabels');
  const pill = host.children.filter((p) => p.dataset.reaction === 'negative')[0];
  host.fire('click', { target: pill });
  eq(lastCall('bot_apply_reaction').args, ['Anna', 'negative']);
  const after = $('botReactionLabels').children;
  eq(after.filter((p) => p.classList.contains('active')).length, 1);
  ok(after.filter((p) => p.dataset.reaction === 'negative')[0]
       .classList.contains('active'));
  ok(/final decision/i.test($('botChatStatus').textContent));
});

t('a bridge error is shown instead of silence', () => {
  BotChat.onError('whatever', 'no Grok API key');
  ok(/no Grok API key/.test($('botChatStatus').textContent));
});

// ── the Prompt Editor window ─────────────────────────────────────

t('the editor lists both templates and opens the first', () => {
  eq($('botPromptTabs').children.length, 2);
  eq($('botPromptText').value, 'ask {nick}');
});

t('the [edit] button of a Bot Chat action opens that template', () => {
  $('botAnalyzeEditBtn').dataset.template = 'analyze_reaction';
  $('botAnalyzeEditBtn').fire('click');
  eq(BotPrompt.current, 'analyze_reaction');
  eq($('botPromptText').value, 'judge {last_message}');
});

t('the Prompt Editor is a separate window, not inside the Bot Chat', () => {
  const chat = html.indexOf('id="winBotChat"');
  const chatEnd = html.indexOf('id="winBotPrompt"');
  ok(chat >= 0 && chatEnd > chat, 'both windows must exist');
  ok(html.slice(chat, chatEnd).indexOf('botPromptText') < 0,
     'the editor must not be nested inside the Bot Chat panel');
});

t('saving sends the edited text to the backend', () => {
  $('botPromptText').value = 'judge {last_message} strictly';
  $('botPromptSaveBtn').fire('click');
  eq(lastCall('bot_save_prompt').args,
     ['analyze_reaction', 'judge {last_message} strictly']);
  ok(/saved/i.test($('botPromptStatus').textContent));
});

t('cancel restores the stored text', () => {
  $('botPromptText').value = 'scribble';
  $('botPromptCancelBtn').fire('click');
  eq($('botPromptText').value, 'judge {last_message}');
});

t('reset asks the backend to forget the edit', () => {
  $('botPromptResetBtn').fire('click');
  eq(lastCall('bot_reset_prompt').args, ['analyze_reaction']);
});

t('preview shows exactly what would be sent to Grok', () => {
  $('botPromptPreviewBtn').fire('click');
  const call = lastCall('bot_preview_prompt');
  eq(call.args.slice(1), ['Anna', 'analyze_reaction']);
  BotPrompt.onReply(call.args[0],
                    JSON.stringify({ prompt: 'judge hello you' }));
  eq($('botPromptPreview').textContent, 'judge hello you');
  ok(!$('botPromptPreview').classList.contains('hidden'));
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
