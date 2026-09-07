/* Bug #2 (UI half) — Person History must show the SAVED file.

   The window used to fall back to the remote, percent-encoded URL
   (`https://images.virt-chat.com/images/m_%D0%A5%D0%BE…gif`), which the app
   renders as a broken "GIF" placeholder once the site expires it or the
   session cookie is missing. Every cached message must instead point at the
   file we saved under `saved_media/<Nick>/…`, as a proper `file://` URL.

   Run:  node tests/test_media_paths_js.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

// ── minimal DOM (same shape as tests/test_history_render.js) ─────

function mkEl(tag) {
  const listeners = {};
  const el = {
    tagName: String(tag).toUpperCase(),
    _text: '', children: [], parentNode: null, style: {}, dataset: {},
    attrs: {}, title: '', listeners,
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
    set innerHTML(v) { throw new Error('innerHTML is forbidden'); },
    appendChild(c) { el.children.push(c); c.parentNode = el; return c; },
    append(...cs) { cs.forEach((c) => el.appendChild(
      typeof c === 'string' ? mkText(c) : c)); },
    replaceChildren(...cs) { el.children = []; el.append(...cs); },
    replaceWith(c) {
      const at = el.parentNode ? el.parentNode.children.indexOf(el) : -1;
      if (el.parentNode && at >= 0) {
        el.parentNode.children.splice(at, 1, c);
        c.parentNode = el.parentNode;
      }
    },
    replaceChild(c, old) {
      const at = el.children.indexOf(old);
      if (at >= 0) { el.children.splice(at, 1, c); c.parentNode = el; }
    },
    setAttribute(k, v) { el.attrs[k] = String(v); if (k === 'src') el.src = v; },
    getAttribute(k) { return k in el.attrs ? el.attrs[k] : null; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener() {},
    querySelector(sel) { return findAll(el, sel)[0] || null; },
    querySelectorAll(sel) { return findAll(el, sel); },
    click(evt) {
      (listeners.click || []).forEach((fn) => fn(Object.assign(
        { target: el, button: 0, preventDefault() {}, stopPropagation() {} },
        evt || {})));
    },
    scrollIntoView() {},
  };
  return el;
}
function mkText(s) { const n = mkEl('#text'); n._text = s; return n; }
function walk(el, out) {
  out = out || [];
  el.children.forEach((c) => { out.push(c); walk(c, out); });
  return out;
}
function findAll(el, sel) {
  const last = String(sel).trim().split(/\s+/).pop();
  return walk(el).filter((n) => (last.startsWith('.')
    ? n.classList.contains(last.slice(1))
    : n.tagName === last.toUpperCase()));
}

global.document = {
  createElement: mkEl, createTextNode: mkText,
  getElementById: () => mkEl('div'),
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener() {},
};
global.window = global;

const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f), 'utf8');
const modelMod = { exports: {} };
new Function('module', 'exports', readUi('js/history-model.js'))(
  modelMod, modelMod.exports);
global.HistoryModel = modelMod.exports;
const V = new Function('window', 'document', 'HistoryModel',
                       readUi('js/history-view.js') + '\nreturn HistoryView;')(
  global.window, global.document, global.HistoryModel);

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

const REMOTE = 'https://images.virt-chat.com/images/m_%D0%A5%D0%BE.gif';
const SAVED = '/home/user/Chat-V-bot/saved_media/Anski/gifs/2026-09-07_001.gif';

const item = (over) => Object.assign({
  ord: 7, fp: 'fp7', dir: 'in', from: 'Ански', kind: 'gif', text: '',
  time: '11:55', day: '2026-09-07',
  media: { id: 3, url: REMOTE, kind: 'gif', state: 'cached', path: SAVED },
}, over || {});

// ── path → file URL ──────────────────────────────────────────────

t('a POSIX path becomes a file URL', () => {
  eq(HistoryModel.fileUrl(SAVED), 'file:///home/user/Chat-V-bot/saved_media/'
     + 'Anski/gifs/2026-09-07_001.gif');
});

t('a Windows path becomes a file URL with forward slashes', () => {
  eq(HistoryModel.fileUrl('C:\\chatflow\\saved_media\\Anski\\gifs\\a.gif'),
     'file:///C:/chatflow/saved_media/Anski/gifs/a.gif');
});

t('spaces and non-latin folder names are escaped, not mangled', () => {
  const url = HistoryModel.fileUrl('/data/saved media/Хорошо_Все/images/a.png');
  ok(url.startsWith('file:///data/saved%20media/'), 'spaces are escaped: ' + url);
  ok(url.indexOf(' ') < 0, 'no raw spaces survive');
  ok(url.endsWith('/images/a.png'), 'the file name is intact: ' + url);
});

t('an http url is left alone and an empty path yields nothing', () => {
  eq(HistoryModel.fileUrl(REMOTE), REMOTE);
  eq(HistoryModel.fileUrl(''), '');
  eq(HistoryModel.fileUrl(null), '');
});

// ── the model ────────────────────────────────────────────────────

t('a cached message prefers the saved file over the remote url', () => {
  const rows = HistoryModel.toRows([item()], { nick: 'Ански', myNick: 'Я' });
  eq(rows[0].media.src, HistoryModel.fileUrl(SAVED));
  eq(rows[0].media.url, REMOTE, 'the original url is still remembered');
});

t('a message whose file is not cached keeps the remote url', () => {
  const rows = HistoryModel.toRows(
    [item({ media: { id: 4, url: REMOTE, kind: 'gif', state: 'pending',
                     path: '' } })], { nick: 'Ански' });
  eq(rows[0].media.src, REMOTE);
});

// ── the view ─────────────────────────────────────────────────────

t('the rendered img points at the saved file', () => {
  const host = mkEl('div');
  V.renderRows(host, HistoryModel.toRows([item()], { nick: 'Ански' }), {});
  const img = host.querySelectorAll('.msg-media')[0];
  ok(img, 'an image node is rendered');
  eq(img.getAttribute('src'), HistoryModel.fileUrl(SAVED));
  ok(String(img.title || '').length > 0, 'the tooltip explains the click');
});

t('a not-yet-cached image shows a restore marker instead of a broken img', () => {
  const host = mkEl('div');
  V.renderRows(host, HistoryModel.toRows(
    [item({ media: { id: 4, url: REMOTE, kind: 'gif', state: 'pending',
                     path: '' } })], { nick: 'Ански' }), {});
  const marker = host.querySelectorAll('.msg-media-restore')[0];
  ok(marker, 'a restore marker is drawn');
  ok(marker.textContent.toLowerCase().includes('restore'), marker.textContent);
  eq(host.querySelectorAll('.msg-media').length, 0,
     'no broken remote <img> is shown');
});

t('a cached file that arrives later can be swapped in place', () => {
  const host = mkEl('div');
  V.renderRows(host, HistoryModel.toRows(
    [item({ media: { id: 9, url: REMOTE, kind: 'gif', state: 'pending',
                     path: '' } })], { nick: 'Ански' }), {});
  const changed = V.applyMediaPath(host, 9, SAVED);
  ok(changed, 'the renderer reports that it swapped a node');
  eq(host.querySelectorAll('.msg-media')[0].getAttribute('src'),
     HistoryModel.fileUrl(SAVED));
});

t('swapping an unknown media id changes nothing', () => {
  const host = mkEl('div');
  V.renderRows(host, HistoryModel.toRows([item()], { nick: 'Ански' }), {});
  ok(!V.applyMediaPath(host, 404, SAVED), 'nothing to swap');
});

console.log(`\nmedia_paths_js: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
