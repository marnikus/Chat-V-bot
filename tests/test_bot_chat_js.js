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
    set textContent(v) {
      // the real DOM DETACHES the children it removes; a stub that leaves
      // them pointing at their old parent makes closest() keep succeeding
      // on a node that is no longer in the document, which is exactly the
      // bug that shipped (a re-rendered row looked "inside" the popup).
      el.children.forEach((c) => { c.parentNode = null; });
      el._text = String(v); el.children = [];
    },
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
    focus() {},
    setSelectionRange(a, b) { el.selectionStart = a; el.selectionEnd = b; },
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
  if (s.startsWith('#')) return node.id === s.slice(1);
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

/* Build the element the way the PAGE declares it — id and class attributes
   included. A stub that handed every module a bare <div> could not tell a
   popup that reuses the Bookmarks panel from one that merely looks like it,
   and `closest('#id')` would never match. */
function realEl(id) {
  const el = mkEl('div');
  el.id = id;
  const tag = new RegExp('<([a-zA-Z]+)([^>]*\\sid="' + id + '"[^>]*)>')
    .exec(html);
  if (tag) {
    el.tagName = tag[1].toUpperCase();
    const cls = /\sclass="([^"]*)"/.exec(tag[2]);
    if (cls) el.className = cls[1];
  }
  return el;
}

const byId = {};
global.document = {
  body: mkEl('body'),
  createElement: mkEl,
  // HistoryView's el() builds text nodes; the real DB window does this too.
  createTextNode(text) {
    const node = mkEl('#text');
    node.textContent = String(text);
    return node;
  },
  getElementById(id) {
    if (!(id in byId)) byId[id] = html.includes('id="' + id + '"')
      ? realEl(id) : null;
    return byId[id];
  },
  // Real, not a no-op: the popups dismiss themselves through a
  // document-level click handler, which a swallowed listener would hide.
  _listeners: {},
  _capture: {},
  // Capture listeners are a separate list that runs FIRST, as the real
  // event model does. A stub that ignored the third argument would run a
  // capture handler in bubble order and silently defeat the very trick
  // used to judge "inside the popup" before the DOM is redrawn.
  addEventListener(ev, fn, capture) {
    const bag = capture ? this._capture : this._listeners;
    (bag[ev] = bag[ev] || []).push(fn);
  },
  fire(ev, extra) {
    const event = Object.assign(
      { target: null, preventDefault() {}, stopPropagation() {} },
      extra || {});
    (this._capture[ev] || []).forEach((fn) => fn(event));
    (this._listeners[ev] || []).forEach((fn) => fn(event));
  },
};
global.window = global;
// The scope checkbox remembers itself here, exactly as the sash grid does.
const STORE = {};
global.localStorage = {
  getItem(k) { return k in STORE ? STORE[k] : null; },
  setItem(k, v) { STORE[k] = String(v); },
  removeItem(k) { delete STORE[k]; },
};

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

const VARIABLES = [
  { name: 'msg', token: '{msg}', description: 'the message',
    example: 'hi' },
  { name: 'last_msg', token: '{last_msg}', description: 'their last message',
    example: 'yes' },
  { name: 'person_name', token: '{person_name}', description: 'their name',
    example: 'Anna' },
];

/* Named connections: several may share one provider, so the fixture has
   two Grok ones — a shape the old "one row per provider" model could not
   express, and the reason the UI keys everything by connection id. */
const CONN_STATE = {
  active: 'c-grok-main',
  // the shape bot_providers.catalog() really sends
  providers: [
    { id: 'grok', title: 'Grok (xAI)', model: 'grok-2-latest',
      url: 'https://api.x.ai/v1/chat/completions' },
    { id: 'google', title: 'Google Gemini', model: 'gemini-2.0-flash',
      url: 'https://g/v1beta/models/{model}:generateContent' }],
  connections: [
    { id: 'c-grok-main', title: 'Grok — work', provider: 'grok',
      model: 'grok-2-latest', url: 'https://api.x.ai/v1/chat/completions',
      has_key: true, masked: 'xai-…mnop', ok: true, problem: '' },
    { id: 'c-grok-cheap', title: 'Grok — cheap', provider: 'grok',
      model: 'grok-2-mini', url: 'https://api.x.ai/v1/chat/completions',
      has_key: true, masked: 'xai-…zzzz', ok: true, problem: '' },
    { id: 'c-gem', title: 'Gemini — personal', provider: 'google',
      model: 'gemini-2.0-flash',
      url: 'https://g/v1beta/models/gemini-2.0-flash:generateContent',
      has_key: false, masked: '', ok: false, problem: 'no API key' },
  ],
};

const PRESETS = { suggest_reply: [], analyze_reaction: [
  { id: 'p-strict', title: 'Strict', text: 'judge {last_message} strictly' }] };

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
    media_restore: slot('media_restore'),
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
    bot_connections: (cb) => {
      calls.push({ name: 'bot_connections', args: [] });
      cb(JSON.stringify(CONN_STATE));
    },
    bot_prompt_connections: (cb) => {
      calls.push({ name: 'bot_prompt_connections', args: [] });
      cb(JSON.stringify({ active: CONN_STATE.active,
                          connections: CONN_STATE.connections }));
    },
    bot_save_connection: (id, fieldsJson, cb) => {
      const f = JSON.parse(fieldsJson);
      calls.push({ name: 'bot_save_connection', args: [id, f] });
      const title = f.title, provider = f.provider, key = f.api_key,
            model = f.model, url = f.url;
      let entry = CONN_STATE.connections.find((c) => c.id === id);
      if (!entry) {
        entry = { id: 'c-new', title: title, provider: provider,
                  has_key: false, masked: '', ok: true, problem: '' };
        CONN_STATE.connections.push(entry);
      }
      entry.title = title || entry.title;
      if (key) { entry.has_key = true; entry.masked = 'set'; entry.ok = true; }
      if (model) entry.model = model;
      if (url) entry.url = url;
      cb(entry.id);
    },
    bot_delete_connection: (id, cb) => {
      calls.push({ name: 'bot_delete_connection', args: [id] });
      const before = CONN_STATE.connections.length;
      CONN_STATE.connections = CONN_STATE.connections.filter(
        (c) => c.id !== id);
      cb(CONN_STATE.connections.length < before);
    },
    bot_use_connection: (id, cb) => {
      calls.push({ name: 'bot_use_connection', args: [id] });
      CONN_STATE.active = id;
      cb(true);
    },
    bot_test_connection: slot('bot_test_connection'),
    bot_get_presets: (template, cb) => {
      calls.push({ name: 'bot_get_presets', args: [template] });
      cb(JSON.stringify(PRESETS[template] || []));
    },
    bot_save_preset: (template, title, text, ident, cb) => {
      calls.push({ name: 'bot_save_preset',
                   args: [template, title, text, ident] });
      const list = PRESETS[template] = PRESETS[template] || [];
      const found = list.filter((p) => p.id === ident)[0];
      if (found) { found.text = text; found.title = title; cb(found.id); return; }
      const made = { id: 'p-' + list.length + '-' + template, title: title,
                     text: text };
      list.push(made);
      cb(made.id);
    },
    bot_delete_preset: (ident, cb) => {
      calls.push({ name: 'bot_delete_preset', args: [ident] });
      let gone = false;
      Object.keys(PRESETS).forEach((k) => {
        const kept = PRESETS[k].filter((p) => p.id !== ident);
        if (kept.length !== PRESETS[k].length) gone = true;
        PRESETS[k] = kept;
      });
      cb(gone);
    },
    bot_get_variables: (cb) => {
      calls.push({ name: 'bot_get_variables', args: [] });
      cb(JSON.stringify(VARIABLES));
    },
    bot_check_prompt: (text, cb) => {
      calls.push({ name: 'bot_check_prompt', args: [text] });
      const unknown = (text.match(/\{([a-z][a-z0-9_]*)\}/g) || [])
        .map((t) => t.slice(1, -1))
        .filter((n) => !VARIABLES.some((v) => v.name === n));
      cb(JSON.stringify({ used: [], unknown: unknown, malformed: [],
                          ok: !unknown.length }));
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
// The REAL DB-window media stack. Bot Chat must draw media with these and
// not with a private copy, so the test loads the shipped modules rather than
// stubbing them — a stub would pass no matter which renderer ran.
global.HistoryModel = require('../ui/js/history-model.js');
global.HistoryView = load('js/history-view.js', 'HistoryView');
global.DarkSelect = load('js/dark-select.js', 'DarkSelect');
global.BotMessages = load('js/bot-messages.js', 'BotMessages');
global.BotConnView = load('js/bot-connection-view.js', 'BotConnView');
global.BotSettings = load('js/bot-settings.js', 'BotSettings');
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
  eq(call.args.slice(1), ['Anna', 'analyze_reaction', 'today']);
  BotPrompt.onReply(call.args[0],
                    JSON.stringify({ prompt: 'judge hello you' }));
  eq($('botPromptPreview').textContent, 'judge hello you');
  ok(!$('botPromptPreview').classList.contains('hidden'));
});

// ── media (the GIF bug) ──────────────────────────────────────────

/** Load a day through the real bridge round-trip and return the box. */
function loadDay(items) {
  BotChat.openPerson('Anna');
  const req = lastCall('bot_load_today').args[0];
  BotChat.onReply(req, JSON.stringify({
    nick: 'Anna', day: '2026-09-13', empty: !items.length, items: items }));
  return $('botChatBox');
}

const gifItem = (media) => ({
  dir: 'in', from: 'Anna', text: '', time: '12:30', day: '2026-09-13',
  kind: 'gif', id: 7, ord: 2, media: media,
});

t('a cached GIF renders as an image, not a blank bubble', () => {
  const box = loadDay([gifItem({ id: 3, url: 'http://x/a.gif', kind: 'gif',
                                 state: 'cached', path: '/tmp/a.gif' })]);
  const imgs = findAll(box, 'img');
  eq(imgs.length, 1);
  eq(imgs[0].attrs.alt, 'GIF');
  ok(imgs[0].classList.contains('is-gif'));
  ok(/a\.gif/.test(imgs[0].attrs.src), 'src points at the cached file');
});

t('it is the DB window renderer, not a second one', () => {
  // .msg-media is HistoryView's class. If Bot Chat ever grew its own media
  // code this class would quietly disappear and the two windows would drift.
  const box = loadDay([gifItem({ id: 3, url: 'http://x/a.gif', kind: 'gif',
                                 state: 'cached', path: '/tmp/a.gif' })]);
  eq(findAll(box, '.msg-media').length, 1);
  eq(findAll(box, '.msg-media-box').length, 1);
});

t('a missing file offers restore instead of a broken image', () => {
  const box = loadDay([gifItem({ id: 4, url: 'http://x/b.gif', kind: 'gif',
                                 state: 'missing', path: '' })]);
  eq(findAll(box, 'img').length, 0);
  const marker = findAll(box, '.msg-media-restore');
  eq(marker.length, 1);
  ok(/GIF/.test(marker[0].textContent));
  ok(/restore/.test(marker[0].textContent));
});

t('clicking restore asks the archive to fetch the file again', () => {
  const box = loadDay([gifItem({ id: 5, url: 'http://x/c.gif', kind: 'gif',
                                 state: 'failed', path: '' })]);
  findAll(box, '.msg-media-restore')[0].fire('click');
  eq(lastCall('media_restore').args[1], '5');
});

t('a media message is never blank', () => {
  ['cached', 'pending', 'failed', 'missing', 'evicted', 'skipped']
    .forEach((state) => {
      const box = loadDay([gifItem({ id: 6, url: 'http://x/d.gif',
                                     kind: 'gif', state: state,
                                     path: state === 'cached' ? '/t/d.gif' : '' })]);
      const bubble = findAll(box, '.bot-msg')[0];
      ok(bubble.children.length > 2 || findAll(box, 'img').length > 0,
         'state ' + state + ' drew something');
    });
});

t('a plain text message still has no media block', () => {
  const box = loadDay([{ dir: 'in', from: 'Anna', text: 'hello', time: '12:00',
                         day: '2026-09-13', id: 1, ord: 1 }]);
  eq(findAll(box, '.msg-media').length, 0);
  eq(findAll(box, '.msg-media-restore').length, 0);
  ok(/hello/.test(box.textContent));
});

// ── the variable library ─────────────────────────────────────────

/** The chips are click-delegated to the list, as in the real DOM. */
function clickVar(token) {
  const chip = findAll($('botVarsList'), '.bot-var')
    .find((c) => c.dataset.token === token);
  $('botVarsList').fire('click', { target: chip });
}

t('the editor lists every variable the backend offers', () => {
  const chips = findAll($('botVarsList'), '.bot-var');
  eq(chips.length, VARIABLES.length);
  ok(/\{person_name\}/.test($('botVarsList').textContent));
  ok(/their name/.test($('botVarsList').textContent),
     'each variable is described, not just named');
});

t('clicking a variable inserts it AT THE CURSOR', () => {
  const box = $('botPromptText');
  box.value = 'Hello , how are you?';
  box.selectionStart = box.selectionEnd = 6;
  clickVar('{person_name}');
  eq(box.value, 'Hello {person_name}, how are you?');
});

t('inserting replaces the selected text', () => {
  const box = $('botPromptText');
  box.value = 'Hi NAME!';
  box.selectionStart = 3; box.selectionEnd = 7;
  clickVar('{msg}');
  eq(box.value, 'Hi {msg}!');
});

t('an unknown variable is warned about, visibly', () => {
  $('botPromptText').value = 'hi {nope}';
  $('botPromptText').fire('input');
  ok(!$('botPromptWarn').classList.contains('hidden'));
  ok(/nope/.test($('botPromptWarn').textContent));
});

t('a clean template shows no warning', () => {
  $('botPromptText').value = 'hi {person_name}';
  $('botPromptText').fire('input');
  ok($('botPromptWarn').classList.contains('hidden'));
  eq($('botPromptWarn').textContent, '');
});

t('a warned template can still be saved — warnings never block', () => {
  $('botPromptText').value = 'hi {nope}';
  $('botPromptText').fire('input');
  $('botPromptSaveBtn').fire('click');
  eq(lastCall('bot_save_prompt').args[1], 'hi {nope}');
});

// ── which conversation the AI reads (today only / everything) ────

t('the scope checkbox exists and starts on today', () => {
  ok($('botScopeToday'), 'the scope checkbox is missing from index.html');
  eq(BotChat.scope(), 'today');
});

t('every request carries the scope, not just the message list', () => {
  BotChat.openPerson('Anna');
  eq(lastCall('bot_load_today').args[2], 'today');
  $('botSuggestBtn').fire('click');
  eq(lastCall('bot_suggest_reply').args[2], 'today');
  $('botAnalyzeBtn').fire('click');
  eq(lastCall('bot_analyze_reaction').args[2], 'today');
});

t('unticking it asks for the whole conversation and reloads', () => {
  $('botScopeToday').checked = false;
  $('botScopeToday').fire('change');
  eq(BotChat.scope(), 'all');
  eq(lastCall('bot_load_today').args.slice(1), ['Anna', 'all'],
     'the window must reload with the new scope, not wait for the next click');
  $('botSuggestBtn').fire('click');
  eq(lastCall('bot_suggest_reply').args[2], 'all');
});

t('the preview previews the scope that would actually be sent', () => {
  $('botPromptPreviewBtn').fire('click');
  eq(lastCall('bot_preview_prompt').args.slice(1),
     ['Anna', 'analyze_reaction', 'all']);
});

t('a trimmed history admits it rather than shortening in silence', () => {
  reply(lastCall('bot_load_today').args[0],
        { nick: 'Anna', scope: 'all', empty: false, truncated: true,
          total: 940, items: [{ dir: 'in', from: 'Anna', text: 'hello you' }] });
  const note = $('botChatStatus').textContent;
  ok(/940/.test(note), 'the real total must be visible: ' + note);
  ok(/whole conversation/i.test(note), note);
});

t('an empty archive and an empty day read differently', () => {
  BotChat.openPerson('Anna');
  reply(lastCall('bot_load_today').args[0],
        { nick: 'Anna', scope: 'all', empty: true, items: [] });
  ok(/archive/i.test($('botChatStatus').textContent));
  $('botScopeToday').checked = true;
  $('botScopeToday').fire('change');
  reply(lastCall('bot_load_today').args[0],
        { nick: 'Anna', scope: 'today', empty: true, items: [] });
  ok(/today/i.test($('botChatStatus').textContent));
});

t('the choice survives a restart', () => {
  $('botScopeToday').checked = false;
  $('botScopeToday').fire('change');
  $('botScopeToday').checked = true;           // as a fresh page would be
  BotChat._restoreScope();
  eq(BotChat.scope(), 'all');
  $('botScopeToday').checked = true;
  $('botScopeToday').fire('change');
});

// ── prompt presets (saved wordings, in the editor) ───────────────

const presetRows = () =>
  findAll($('botPresetSelect'), '.dark-select-option');

t('presets of the open template are listed, current template first', () => {
  BotPrompt.open('analyze_reaction', 'Anna');
  eq(lastCall('bot_get_presets').args[0], 'analyze_reaction');
  const rows = presetRows();
  eq(rows[0].dataset.value, '');
  ok(rows.some((r) => r.textContent.indexOf('Strict') >= 0));
});

t('the preset chooser is a dark menu, not a native select', () => {
  ok(!$('botPresetSelect').querySelector('OPTION'),
     'a native <option> list is drawn by the OS and cannot be themed');
  ok($('botPresetSelect').querySelector('.dark-select-trigger'));
});

t('the preset menu is built from the Bookmarks panel classes', () => {
  const menu = $('botPresetSelect').querySelector('.dark-select-menu');
  ok(menu.classList.contains('layout-menu'),
     'it must BE the Bookmarks panel, not a second copy of its styling');
  ok(presetRows().some((r) => r.querySelector('.lm-sub')),
     'rows carry the Bookmarks subtitle class');
});

t('picking from the menu applies that preset and closes it', () => {
  const box = BotPrompt._presetBox;
  box.open();
  const row = presetRows().find((r) => r.dataset.value === 'p-strict');
  row.fire('click');
  eq($('botPromptText').value, 'judge {last_message} strictly');
  ok(!box.isOpen(), 'the menu must close after a choice');
});

t('applying a preset only FILLS the editor — it never saves by itself', () => {
  const before = calls.length;
  BotPrompt.applyPreset('p-strict');
  eq($('botPromptText').value, 'judge {last_message} strictly');
  eq(calls.slice(before).filter((c) => c.name === 'bot_save_prompt').length, 0,
     'browsing presets must not change what the app sends');
});

t('save-as stores a new preset under this template', () => {
  global.window.prompt = () => 'Friendly';
  $('botPromptText').value = 'be kind to {person_name}';
  $('botPresetSaveBtn').fire('click');
  eq(lastCall('bot_save_preset').args.slice(0, 3),
     ['analyze_reaction', 'Friendly', 'be kind to {person_name}']);
  eq(lastCall('bot_get_presets').args[0], 'analyze_reaction');
});

t('a preset needs a name — cancelling the prompt writes nothing', () => {
  global.window.prompt = () => '';
  const before = calls.filter((c) => c.name === 'bot_save_preset').length;
  $('botPresetSaveBtn').fire('click');
  eq(calls.filter((c) => c.name === 'bot_save_preset').length, before);
});

t('deleting with nothing selected explains itself instead of guessing', () => {
  BotPrompt.preset = '';
  const before = calls.filter((c) => c.name === 'bot_delete_preset').length;
  $('botPresetDeleteBtn').fire('click');
  eq(calls.filter((c) => c.name === 'bot_delete_preset').length, before);
  ok(/select a preset/i.test($('botPromptStatus').textContent));
});

t('deleting a selected preset removes only that one', () => {
  BotPrompt.applyPreset('p-strict');
  $('botPresetDeleteBtn').fire('click');
  eq(lastCall('bot_delete_preset').args[0], 'p-strict');
  ok(!BotPrompt.presets.some((p) => p.id === 'p-strict'));
});

// ── the editor holds NO api configuration ───────────────────────

t('the editor holds no key, model, endpoint or connection control', () => {
  ['botApiKeyInput', 'botModelInput', 'botConnSaveBtn',
   'botConnSelect', 'botConnWarn'].forEach((id) =>
    ok(!html.includes('id="' + id + '"'),
       id + ' still lives in the Prompt Editor markup'));
});

t('the editor cannot change which AI runs — that is the popup\'s job', () => {
  ok(!BotPrompt.useConnection, 'a second way to switch connection');
  ok(!BotPrompt.loadConnections);
  const before = calls.length;
  BotPrompt.open('suggest_reply', 'Anna');
  eq(calls.slice(before).filter(
    (c) => c.name.indexOf('connection') >= 0).length, 0,
     'opening the editor must not touch connection state');
});

// ── AI Connections window ────────────────────────────────────────

BotSettings.init();          // once, exactly as the page does it

function openSettings() {
  // the ⚙ TOGGLES, like the Grid view button — make sure we end up open
  if (!BotSettings.isOpen()) $('botPromptSettingsBtn').fire('click');
}

// the DOM stub does not bubble, so dispatch on the delegating host the
// way a real bubbled click would reach it
function clickPreset(n) {
  const opt = findAll($('botPresetOptions'), '.bot-preset-opt')[n || 0];
  $('botPresetOptions').fire('click', { target: opt });
  return opt;
}

/* A real click runs the list's delegated handler AND THEN keeps bubbling
   to the document's dismiss handler, with the SAME target. Firing only on
   the list hid a shipped bug: the delegated handler re-renders the rows,
   so by the time the document handler looks at the target it has been
   detached and closest('#botSettingsBackdrop') finds nothing — a click on
   a row was judged a click OUTSIDE the popup, and closed it. */
function clickConnection(id) {
  const row = findAll($('botProviderList'), '.bot-provider')
    .find((r) => r.dataset.provider === id);
  clickPath(row, $('botProviderList'));
}

/* One real click, in the real order: the document's CAPTURE handlers, then
   the element's own handler, then the document's BUBBLE handlers — all with
   the same target. Getting this order right is what lets the test see the
   shipped bug, because the middle step is the one that detaches the row. */
function clickPath(target, host) {
  const ev = { target: target };
  (document._capture.click || []).forEach((fn) => fn(ev));
  if (host) (host.listeners.click || []).forEach((fn) => fn(
    Object.assign({ preventDefault() {}, stopPropagation() {} }, ev)));
  (document._listeners.click || []).forEach((fn) => fn(ev));
}

t('the ⚙ toggles the popup rather than only opening it', () => {
  BotSettings.close();
  $('botPromptSettingsBtn').fire('click');
  ok(BotSettings.isOpen());
  $('botPromptSettingsBtn').fire('click');
  ok(!BotSettings.isOpen());
});

t('a click outside dismisses it, like the Bookmarks menu', () => {
  openSettings();
  document.fire('click', { target: document.body });
  ok(!BotSettings.isOpen(), 'an anchored popup closes on an outside click');
});

t('a click inside does NOT dismiss it', () => {
  openSettings();
  // the page nests the list inside the popup; the stub builds elements
  // by id alone, so attach it the way index.html does before asserting
  const inside = $('botProviderList');
  if (inside.parentNode !== $('botSettingsBackdrop'))
    $('botSettingsBackdrop').appendChild(inside);
  document.fire('click', { target: inside });
  ok(BotSettings.isOpen(), 'editing a field must not close the popup');
});

t('it reuses the Bookmarks panel styling', () => {
  openSettings();
  ok($('botSettingsBackdrop').classList.contains('layout-menu'),
     'the popup must reuse the Bookmarks panel styling');
});

/* CSS specificity, computed the way the cascade does: (#id, .class, element).
   A bare `.ui-btn` is (0,1,0) and loses to `.layout-menu button` (0,1,1). */
function specificity(sel) {
  const ids = (sel.match(/#[\w-]+/g) || []).length;
  const cls = (sel.match(/\.[\w-]+/g) || []).length;
  const els = (sel.match(/(?:^|[\s>+~])([a-z][\w-]*)/g) || []).length;
  return (ids * 100) + (cls * 10) + els;
}

t('the popup\'s buttons outrank .layout-menu button', () => {
  /* The reported broken header. The popup reuses `.layout-menu` for its
     panel chrome, which drags in `.layout-menu button { display:block;
     width:100% }` from sash-layout.css. That selector is (0,1,1) and beat
     every bare `.ui-btn` rule at (0,1,0), so EVERY button in the popup was
     forced full-width and stacked: the cross filled the header and shoved
     the headings down to a few pixels wide.

     Reusing another component's panel class means inheriting its element
     selectors, so this popup's own button rules must be scoped to it. */
  const css = readUi('css/bot-chat.css');
  const rival = specificity('.layout-menu button');
  const missed = [];
  const wanted = ['.ui-btn', '.ui-btn--icon', '.bot-provider',
                  '.bot-preset-opt'];
  wanted.forEach((base) => {
    // find the rule that actually declares this component
    const re = new RegExp('([^{}]*\\' + base + '[^{},]*)(?:,[^{}]*)?\\{',
                          'g');
    let best = 0;
    let m = re.exec(css);
    while (m) {
      m[1].split(',').forEach((sel) => {
        if (sel.indexOf(base) >= 0) best = Math.max(best, specificity(sel));
      });
      m = re.exec(css);
    }
    if (best <= rival) missed.push(base + ' (' + best + ' <= ' + rival + ')');
  });
  eq(missed.join('; '), '', 'these lose to .layout-menu button');
});

t('the popup does not inherit full-width stacked buttons', () => {
  const css = readUi('css/bot-chat.css');
  const rule = /\.bot-settings\s+\.ui-btn\s*,?[^{]*\{([^}]*)\}/.exec(css);
  ok(rule, 'the popup must restate the button box scoped to itself');
  ok(/width:\s*auto/.test(rule[1]),
     'width:100% is inherited from .layout-menu button and must be undone');
  ok(/display:\s*inline-flex/.test(rule[1]),
     'display:block is inherited too, and stacks the footer vertically');
});

t('the close button is pinned right and cannot be resized by the title', () => {
  /* The reported drift: the header is a flex row whose text block had no
     flex sizing, so its width followed the wrapping of the title and
     subtitle. `margin-left:auto` pushes the button right relative to THAT
     moving box, and a flex item with no flex-none shrinks besides — so the
     cross floated and changed size as the heading reflowed. The text block
     must absorb the free space and the button must be rigid. */
  const css = readUi('css/bot-chat.css');
  const text = /\.bot-settings-headings[^{]*\{([^}]*)\}/.exec(css);
  ok(text, 'the heading block needs a class of its own to be sized');
  ok(/flex:\s*1/.test(text[1]),
     'the text block must take the slack, so the button stops moving');
  ok(/min-width:\s*0/.test(text[1]),
     'without min-width:0 a long title pushes the button off instead');

  const btn = /\.bot-settings-head\s+\.ui-btn[^{]*\{([^}]*)\}/.exec(css);
  ok(btn, 'the close button must be pinned explicitly');
  ok(/flex:\s*none/.test(btn[1]),
     'a flex item with no flex:none is resized by its neighbours');
});

t('the close button keeps the shared button metrics', () => {
  const css = readUi('css/bot-chat.css');
  const icon = /\.ui-btn--icon\s*\{([^}]*)\}/.exec(css)[1];
  ok(/width:\s*28px/.test(icon), 'square, matching the 28px button height');
  ok(/height:\s*28px/.test(icon),
     'height must be stated too — flex-start would otherwise shrink it');
});

t('every field in the popup is dark, like the rest of the app', () => {
  /* The reported "white elements". This app has NO global input rule —
     each window styles its own fields by id or class — so a bare <input>
     in a new panel inherits the browser default, which is white on a
     black app. The popup must therefore paint its own. */
  const css = readUi('css/bot-chat.css');
  const rule = /\.bot-provider-form input[^{]*\{([^}]*)\}/.exec(css);
  ok(rule, 'the popup must style its own inputs');
  ok(/background:\s*var\(--bg-input\)/.test(rule[1]),
     'fields must use the app input background, not the browser default');
  ok(/color:\s*var\(--text-primary\)/.test(rule[1]),
     'typed text must be light, or it is invisible on a dark field');
});

t('the whole popup stays on screen, however low the button sits', () => {
  /* The reported bug: anchored at anchor.bottom + 6, a gear near the
     bottom of the window pushed the footer — Delete, Test, Save, Cancel,
     Select — off the edge where it could not be clicked. */
  global.window.innerWidth = 1280;
  global.window.innerHeight = 800;
  const panel = $('botSettingsBackdrop');
  panel.offsetWidth = 760;
  panel.offsetHeight = 600;
  const lowGear = {
    getBoundingClientRect: () => (
      { left: 1100, right: 1140, top: 760, bottom: 784 }),
  };
  BotConnView.place(panel, lowGear);
  const top = parseInt(panel.style.top, 10);
  const left = parseInt(panel.style.left, 10);
  ok(top >= 0, 'the top edge must be on screen');
  ok(top + 600 <= 800, 'the BOTTOM edge — the buttons — must be on screen');
  ok(left >= 0 && left + 760 <= 1280, 'both side edges must be on screen');
});

t('a popup taller than the window is pinned, not hung off the bottom', () => {
  global.window.innerWidth = 1280;
  global.window.innerHeight = 500;
  const panel = $('botSettingsBackdrop');
  panel.offsetWidth = 760;
  panel.offsetHeight = 600;          // taller than the 500px window
  BotConnView.place(panel, {
    getBoundingClientRect: () => ({ left: 10, right: 50, top: 5, bottom: 29 }),
  });
  eq(parseInt(panel.style.top, 10), 8, 'pin to the top and let it scroll');
});

t('the popup lives OUTSIDE the sash grid, or it is destroyed on boot', () => {
  /* The bug this pins: SashGrid.render() does
       gridEl.replaceChildren(frag)
     which wipes every child of <main class="sash-grid"> and re-adds ONLY
     the registered window panels. The popup is not one of those, so while
     it sat inside <main> it was deleted from the DOM at startup —
     getElementById returned null, BotSettings.init() bailed at its guard,
     and the ⚙ button silently did nothing. Being a child of <main> is the
     whole bug; every other assertion here passed while it was broken. */
  const grid = html.slice(html.indexOf('<main class="sash-grid"'),
                          html.indexOf('</main>'));
  ok(grid.indexOf('id="botSettingsBackdrop"') < 0,
     'the popup is inside <main> and SashGrid will delete it on render');
  ok(html.indexOf('id="botSettingsBackdrop"') >= 0, 'it must still exist');
  // the reference popup it is modelled on lives outside <main> too
  ok(grid.indexOf('id="layoutMenu"') < 0);
});

t('the connections window opens from the prompt editor title bar', () => {
  openSettings();
  ok(!$('botSettingsBackdrop').classList.contains('hidden'));
  eq(findAll($('botProviderList'), '.bot-provider').length,
     CONN_STATE.connections.length);
});

t('the active connection is marked as in use', () => {
  openSettings();
  const rows = findAll($('botProviderList'), '.bot-provider');
  const row = rows.find((r) => r.dataset.provider === CONN_STATE.active);
  ok(row.classList.contains('active'));
  ok(/In use/.test(row.textContent));
});

t('a stored key is shown masked and NEVER filled into the field', () => {
  openSettings();
  clickConnection('c-grok-main');
  eq($('botProviderKey').value, '', 'the secret is never echoed into the DOM');
  ok(/xai-…mnop/.test($('botProviderKeyState').textContent));
});

const providerRows = () =>
  findAll($('botConnProvider'), '.dark-select-option');

t('the provider chooser is a dark menu listing every provider', () => {
  openSettings();
  eq(providerRows().map((r) => r.dataset.value), ['grok', 'google']);
  ok(!$('botConnProvider').querySelector('OPTION'),
     'a native select cannot be themed — that was the reported bug');
});

t('picking a provider offers that provider\'s preset', () => {
  openSettings();
  BotSettings.addNew();
  const google = providerRows().find((r) => r.dataset.value === 'google');
  google.fire('click');
  eq(BotSettings.providerId(), 'google');
  const opts = findAll($('botPresetOptions'), '.bot-preset-opt');
  ok(opts.length >= 1, 'the provider must offer a recommended preset');
  ok(/gemini/.test($('botPresetDesc').textContent + opts[0].textContent) ||
     /Google/.test(opts[0].textContent));
});

t('Select routes prompts through the viewed connection and closes', () => {
  openSettings();
  clickConnection('c-grok-main');
  $('botConnSelectBtn').fire('click');
  eq(lastCall('bot_use_connection').args[0], 'c-grok-main');
  ok(!BotSettings.isOpen(), 'Select is the action that confirms and closes');
});

t('Select SAVES the visible edits before it activates', () => {
  /* Activating an unsaved edit would run prompts on values the user
     cannot see, so the order is save-then-use, not use-then-save. */
  openSettings();
  clickConnection('c-grok-main');
  $('botProviderModel').value = 'grok-4.3-edited';
  const before = calls.length;
  $('botConnSelectBtn').fire('click');
  const after = calls.slice(before).map((c) => c.name);
  ok(after.indexOf('bot_save_connection') >= 0, 'it must save');
  ok(after.indexOf('bot_save_connection') < after.indexOf('bot_use_connection'),
     'the save must happen BEFORE the activation');
  eq(lastCall('bot_save_connection').args[1].model, 'grok-4.3-edited');
});

t('browsing rows never activates or closes anything', () => {
  /* The reported bug: clicking a connection was read as choosing it.
     A click may only load the row into the form. */
  openSettings();
  const before = calls.length;
  clickConnection('c-gem');
  clickConnection('c-grok-cheap');
  const made = calls.slice(before).map((c) => c.name);
  eq(made.filter((n) => n === 'bot_use_connection').length, 0,
     'browsing must not activate');
  eq(made.filter((n) => n === 'bot_save_connection').length, 0,
     'browsing must not save');
  ok(BotSettings.isOpen(), 'browsing must not close the popup');
  eq(BotSettings.viewed, 'c-grok-cheap');
});

t('Cancel closes without changing the active connection', () => {
  openSettings();
  const wasActive = BotSettings.active;
  clickConnection('c-gem');
  const before = calls.length;
  $('botSettingsCancelBtn').fire('click');
  eq(calls.slice(before).filter(
    (c) => c.name === 'bot_use_connection').length, 0);
  eq(BotSettings.active, wasActive);
  ok(!BotSettings.isOpen());
});

t('Apply Preset Settings fills the fields and keeps the popup OPEN', () => {
  openSettings();
  BotSettings.addNew();
  providerRows().find((r) => r.dataset.value === 'google').fire('click');
  clickPreset(0);
  ok(!$('botApplyPresetBtn').disabled, 'choosing a preset enables Apply');
  const before = calls.length;
  $('botApplyPresetBtn').fire('click');
  ok(/gemini/.test($('botProviderModel').value),
     'Apply must write the preset into the visible field');
  ok(BotSettings.isOpen(), 'applying a preset must not close the popup');
  eq(calls.slice(before).filter(
    (c) => c.name === 'bot_use_connection').length, 0,
     'applying a preset is not selecting a connection');
});

t('choosing a preset alone writes nothing', () => {
  openSettings();
  BotSettings.addNew();
  providerRows().find((r) => r.dataset.value === 'google').fire('click');
  $('botProviderModel').value = 'hand-typed';
  clickPreset(0);
  eq($('botProviderModel').value, 'hand-typed',
     'selecting a preset only describes it; Apply is what writes');
});

t('Apply is disabled until a preset is chosen', () => {
  openSettings();
  BotSettings.addNew();
  ok($('botApplyPresetBtn').disabled);
});

t('the provider preset is NOT a prompt preset', () => {
  /* Two different libraries share the word. Applying a connection preset
     must never call the prompt-preset bridge. */
  openSettings();
  BotSettings.addNew();
  providerRows().find((r) => r.dataset.value === 'google').fire('click');
  clickPreset(0);
  const before = calls.length;
  $('botApplyPresetBtn').fire('click');
  eq(calls.slice(before).filter(
    (c) => /preset/.test(c.name)).length, 0);
});

t('viewing a connection shows ITS model and endpoint', () => {
  openSettings();
  clickConnection('c-gem');
  eq($('botProviderModel').value, 'gemini-2.0-flash');
  ok(/generativelanguage|\/v1beta\//.test($('botProviderUrl').value));
  clickConnection('c-grok-cheap');
  eq($('botProviderModel').value, 'grok-2-mini');
});

t('Save stores the connection and KEEPS the popup open', () => {
  /* Adding a connection must not force you to activate it. Select is for
     "use this one"; Save is for "keep this one and carry on editing". */
  openSettings();
  BotSettings.addNew();
  $('botConnTitle').value = 'My second Grok';
  $('botProviderKey').value = 'xai-fresh-key';
  const before = calls.length;
  $('botSettingsSaveBtn').fire('click');
  const made = calls.slice(before).map((c) => c.name);
  ok(made.indexOf('bot_save_connection') >= 0, 'Save must save');
  eq(made.filter((n) => n === 'bot_use_connection').length, 0,
     'Save must NOT activate the connection');
  ok(BotSettings.isOpen(), 'Save must not close the popup');
  eq(lastCall('bot_save_connection').args[1].title, 'My second Grok');
});

t('Save is offered for a brand-new connection too', () => {
  openSettings();
  BotSettings.addNew();
  ok(!$('botSettingsSaveBtn').disabled,
     'a new connection needs a way to be stored without selecting it');
});

t('a saved new connection appears in the list and stays viewed', () => {
  openSettings();
  BotSettings.addNew();
  $('botConnTitle').value = 'Kimi work';
  $('botProviderKey').value = 'sk-kimi-key';
  $('botSettingsSaveBtn').fire('click');
  ok(BotSettings.viewed, 'the new row becomes the viewed one');
  ok(CONN_STATE.connections.some((c) => c.title === 'Kimi work'));
});

t('saving sends the viewed connection its own fields', () => {
  openSettings();
  clickConnection('c-gem');
  $('botProviderKey').value = 'AIza-typed-key';
  $('botConnSelectBtn').fire('click');
  const call = lastCall('bot_save_connection');
  eq(call.args[0], 'c-gem');
  eq(call.args[1].api_key, 'AIza-typed-key');
  eq(call.args[1].model, 'gemini-2.0-flash',
     'the form must save THIS connection\'s fields, not the last one shown');
});

t('a connection must be named before it can be saved', () => {
  openSettings();
  BotSettings.addNew();
  $('botConnTitle').value = '';
  const before = calls.filter((c) => c.name === 'bot_save_connection').length;
  $('botConnSelectBtn').fire('click');
  eq(calls.filter((c) => c.name === 'bot_save_connection').length, before);
  ok(/name/i.test($('botSettingsStatus').textContent));
});

t('+ New starts a blank form without touching the stored ones', () => {
  openSettings();
  const before = CONN_STATE.connections.length;
  $('botConnNewBtn').fire('click');
  eq($('botConnTitle').value, '');
  eq(BotSettings.viewed, '');
  eq(CONN_STATE.connections.length, before);
});

t('deleting removes that connection and only that one', () => {
  openSettings();
  clickConnection('c-grok-cheap');
  $('botConnDeleteBtn').fire('click');
  eq(lastCall('bot_delete_connection').args[0], 'c-grok-cheap');
  ok(CONN_STATE.connections.some((c) => c.id === 'c-grok-main'),
     'the other Grok connection must survive');
});

t('test connection reports success in words', () => {
  openSettings();
  clickConnection('c-grok-main');
  $('botTestConnBtn').fire('click');
  const call = lastCall('bot_test_connection');
  eq(call.args[1], 'c-grok-main');
  BotSettings.onReply(call.args[0],
                      JSON.stringify({ ok: true, detail: 'answered: ok' }));
  ok(/works/i.test($('botSettingsStatus').textContent));
});

t('a failed test says why, and does not look like success', () => {
  openSettings();
  clickConnection('c-gem');
  $('botTestConnBtn').fire('click');
  const req = lastCall('bot_test_connection').args[0];
  BotSettings.onReply(req, JSON.stringify(
    { ok: false, code: 'grok_no_key', detail: 'no Google Gemini API key' }));
  ok(/Failed/.test($('botSettingsStatus').textContent));
  ok(/no Google Gemini API key/.test($('botSettingsStatus').textContent));
});

t('a test answer never leaks into the chat window', () => {
  openSettings();
  clickConnection('c-grok-main');
  $('botTestConnBtn').fire('click');
  const req = lastCall('bot_test_connection').args[0];
  const before = $('botChatStatus').textContent;
  BotChat.onReply(req, JSON.stringify({ ok: true, detail: 'fine' }));
  eq($('botChatStatus').textContent, before);
});

t('closing clears any typed key', () => {
  openSettings();
  $('botProviderKey').value = 'AIza-typed-but-cancelled';
  $('botSettingsCancelBtn').fire('click');
  ok($('botSettingsBackdrop').classList.contains('hidden'));
  eq($('botProviderKey').value, '');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
