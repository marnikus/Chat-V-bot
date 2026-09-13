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
  // HistoryView's el() builds text nodes; the real DB window does this too.
  createTextNode(text) {
    const node = mkEl('#text');
    node.textContent = String(text);
    return node;
  },
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

const VARIABLES = [
  { name: 'msg', token: '{msg}', description: 'the message',
    example: 'hi' },
  { name: 'last_msg', token: '{last_msg}', description: 'their last message',
    example: 'yes' },
  { name: 'person_name', token: '{person_name}', description: 'their name',
    example: 'Anna' },
];

const PROVIDER_STATE = {
  active: 'grok',
  providers: [
    { id: 'grok', title: 'Grok (xAI)', model: 'grok-2-latest',
      url: 'https://api.x.ai/v1/chat/completions', has_key: true,
      masked: 'xai-…mnop', active: true },
    { id: 'google', title: 'Google Gemini', model: 'gemini-2.0-flash',
      url: 'https://g/v1beta/models/{model}:generateContent',
      has_key: false, masked: '', active: false },
  ],
};

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
    bot_providers: (cb) => {
      calls.push({ name: 'bot_providers', args: [] });
      cb(JSON.stringify({ active: PROVIDER_STATE.active,
                          providers: PROVIDER_STATE.providers }));
    },
    bot_save_provider: (id, key, model, url, cb) => {
      calls.push({ name: 'bot_save_provider', args: [id, key, model, url] });
      const entry = PROVIDER_STATE.providers.find((p) => p.id === id);
      if (key) { entry.has_key = true; entry.masked = 'set'; }
      if (model) entry.model = model;
      cb(true);
    },
    bot_use_provider: (id, cb) => {
      calls.push({ name: 'bot_use_provider', args: [id] });
      PROVIDER_STATE.active = id;
      PROVIDER_STATE.providers.forEach((p) => { p.active = p.id === id; });
      cb(true);
    },
    bot_test_provider: slot('bot_test_provider'),
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
  eq(call.args.slice(1), ['Anna', 'analyze_reaction']);
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

// ── AI provider settings dialog ──────────────────────────────────

BotSettings.init();          // once, exactly as the page does it

function openSettings() {
  $('botSettingsBtn').fire('click');
}

function clickProvider(id) {
  const row = findAll($('botProviderList'), '.bot-provider')
    .find((r) => r.dataset.provider === id);
  $('botProviderList').fire('click', { target: row });
}

t('the settings dialog opens from the bot chat title bar', () => {
  openSettings();
  ok(!$('botSettingsBackdrop').classList.contains('hidden'));
  eq(findAll($('botProviderList'), '.bot-provider').length, 2);
});

t('the active provider is marked as in use', () => {
  openSettings();
  const rows = findAll($('botProviderList'), '.bot-provider');
  const grok = rows.find((r) => r.dataset.provider === 'grok');
  ok(grok.classList.contains('active'));
  ok(/in use/.test(grok.textContent));
});

t('a stored key is shown masked and NEVER filled into the field', () => {
  openSettings();
  clickProvider('grok');
  eq($('botProviderKey').value, '', 'the secret is never echoed into the DOM');
  ok(/xai-…mnop/.test($('botProviderKeyState').textContent));
});

t('selecting a provider shows ITS model and endpoint', () => {
  openSettings();
  clickProvider('google');
  eq($('botProviderModel').value, 'gemini-2.0-flash');
  ok(/generativelanguage|\/v1beta\//.test($('botProviderUrl').value));
});

t('saving sends the selected provider its own fields', () => {
  openSettings();
  clickProvider('google');
  $('botProviderKey').value = 'AIza-typed-key';
  $('botSettingsSaveBtn').fire('click');
  const call = lastCall('bot_save_provider');
  eq(call.args[0], 'google');
  eq(call.args[1], 'AIza-typed-key');
});

t('switching the active provider goes through the backend', () => {
  openSettings();
  clickProvider('google');
  $('botUseProviderBtn').fire('click');
  eq(lastCall('bot_use_provider').args[0], 'google');
  ok(/using this provider/i.test($('botSettingsStatus').textContent));
});

t('test connection reports success in words', () => {
  openSettings();
  clickProvider('grok');
  $('botTestConnBtn').fire('click');
  const req = lastCall('bot_test_provider').args[0];
  BotSettings.onReply(req, JSON.stringify({ ok: true, detail: 'answered: ok' }));
  ok(/works/i.test($('botSettingsStatus').textContent));
});

t('a failed test says why, and does not look like success', () => {
  openSettings();
  clickProvider('google');
  $('botTestConnBtn').fire('click');
  const req = lastCall('bot_test_provider').args[0];
  BotSettings.onReply(req, JSON.stringify(
    { ok: false, code: 'grok_no_key', detail: 'no Google Gemini API key' }));
  ok(/Failed/.test($('botSettingsStatus').textContent));
  ok(/no Google Gemini API key/.test($('botSettingsStatus').textContent));
});

t('a test answer never leaks into the chat window', () => {
  openSettings();
  $('botTestConnBtn').fire('click');
  const req = lastCall('bot_test_provider').args[0];
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
