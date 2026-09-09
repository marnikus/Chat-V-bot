/* Tests for the label UI: the pill renderer, the Label Manager window and
   the "Pick Color" popup.

   What the user was promised:
     · a label shows next to the nick as a small coloured pill with an ✕;
     · that ✕ removes the label FROM THAT PERSON ONLY — deleting a label
       everywhere happens in the Label Manager;
     · the same renderer feeds People and the Full User Database, so the
       two tables can never disagree;
     · clicking a badge in Active Labels ASSIGNS it to the selected person
       (toggle), a separate "edit" text opens an inline rename/colour
       editor, and the ✕ still deletes system-wide — three distinct zones;
     · clicking a person in People targets them for quick assign: the
       Label Manager opens, the target chip follows, and both tables
       highlight the target row;
     · the colour picker is a movable popup with 20 bright presets in a
       5×4 grid, a white ring on the current colour, and a Cancel button;
     · label names are user text and must never become markup.

   Per AGENT_RULES RULE 8 this executes the REAL shipped modules
   (ui/js/labels.js, ui/js/color-picker.js) against a DOM stub that throws
   if a markup setter is touched, and asserts against the REAL CSS.

   Run:  node tests/test_labels_ui_js.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

// ── DOM stub ─────────────────────────────────────────────────────
const byId = {};

function mkEl(tag) {
  const listeners = {};
  const el = {
    tagName: String(tag).toUpperCase(),
    _text: '',
    children: [],
    parentNode: null,
    style: {},
    dataset: {},
    attrs: {},
    title: '',
    type: '',
    value: '',
    checked: false,
    disabled: false,
    listeners,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { if (on) this._set.add(c); else this._set.delete(c); },
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
    set innerHTML(v) { throw new Error('innerHTML is forbidden here'); },
    get innerHTML() { return ''; },
    get offsetWidth() { return 280; },
    get offsetHeight() { return 320; },
    appendChild(c) { el.children.push(c); c.parentNode = el; return c; },
    append(...cs) { cs.forEach((c) => el.appendChild(c)); },
    removeChild(c) {
      const i = el.children.indexOf(c);
      if (i >= 0) el.children.splice(i, 1);
      c.parentNode = null;
      return c;
    },
    replaceChildren(...cs) { el.children = []; cs.forEach((c) => el.appendChild(c)); },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    getAttribute(k) { return k in el.attrs ? el.attrs[k] : null; },
    getBoundingClientRect() {
      return { left: 100, top: 50, right: 380, bottom: 370,
               width: 280, height: 320 };
    },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener(ev, fn) {
      const list = listeners[ev] || [];
      const i = list.indexOf(fn);
      if (i >= 0) list.splice(i, 1);
    },
    querySelector(sel) { return findAll(el, sel)[0] || null; },
    querySelectorAll(sel) { return findAll(el, sel); },
    closest(sel) {
      let node = el;
      while (node) {
        if (matches(node, sel)) return node;
        node = node.parentNode;
      }
      return null;
    },
    fire(ev, extra) {
      (listeners[ev] || []).forEach((fn) => fn(Object.assign(
        { target: el, button: 0, clientX: 0, clientY: 0,
          preventDefault() {}, stopPropagation() {} }, extra || {})));
    },
    click(extra) { el.fire('click', extra); },
    focus() {},
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
function matches(node, sel) {
  if (!node || !node.classList) return false;
  if (sel.startsWith('.')) return node.classList.contains(sel.slice(1));
  if (sel.startsWith('[')) {
    const m = /\[([\w-]+)(?:="([^"]*)")?\]/.exec(sel);
    if (!m) return false;
    if (m[1].startsWith('data-')) {
      const key = m[1].slice(5).replace(/-(\w)/g, (_x, c) => c.toUpperCase());
      return key in node.dataset;
    }
    return node.getAttribute(m[1]) !== null;
  }
  const [tag, attr] = sel.split('[');
  if (attr && node.tagName !== tag.toUpperCase()) return false;
  if (attr) {
    const m = /([\w-]+)(?:="([^"]*)")?/.exec(attr);
    return node.getAttribute(m[1]) === (m[2] === undefined ? node.getAttribute(m[1]) : m[2])
      || node.type === m[2];
  }
  return node.tagName === sel.toUpperCase();
}
function findAll(el, sel) {
  const last = String(sel).trim().split(/\s+/).pop();
  return walk(el).filter((n) => {
    if (last.startsWith('input')) {
      if (n.tagName !== 'INPUT') return false;
      const m = /type="([^"]+)"/.exec(last);
      return !m || n.type === m[1];
    }
    return matches(n, last);
  });
}

const body = mkEl('body');
global.document = {
  body,
  createElement: mkEl,
  createTextNode: mkText,
  getElementById: (id) => byId[id] || null,
  querySelector: () => null,
  querySelectorAll: () => [],
  _keys: [],
  addEventListener(ev, fn) { if (ev === 'keydown') this._keys.push(fn); },
  removeEventListener(ev, fn) {
    if (ev !== 'keydown') return;
    const i = this._keys.indexOf(fn);
    if (i >= 0) this._keys.splice(i, 1);
  },
  key(k) { this._keys.slice().forEach((fn) => fn({ key: k })); },
};
const docListeners = {};
global.window = {
  innerWidth: 1400, innerHeight: 900,
  addEventListener() {}, removeEventListener() {},
};
global.document.addEventListener = global.document.addEventListener.bind(global.document);
// pointer events used while dragging live on document
global.document.addEventListener = (function (orig) {
  return function (ev, fn) {
    if (ev === 'keydown') return orig.call(global.document, ev, fn);
    (docListeners[ev] = docListeners[ev] || []).push(fn);
  };
})(global.document.addEventListener);
global.document.removeEventListener = (function (orig) {
  return function (ev, fn) {
    if (ev === 'keydown') return orig.call(global.document, ev, fn);
    const list = docListeners[ev] || [];
    const i = list.indexOf(fn);
    if (i >= 0) list.splice(i, 1);
  };
})(global.document.removeEventListener);
function firePointer(ev, x, y) {
  (docListeners[ev] || []).slice().forEach((fn) => fn({ clientX: x, clientY: y }));
}

// ── load the real modules ────────────────────────────────────────
const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f), 'utf8');
function load(file, name) {
  const src = readUi(file);
  const mod = { exports: {} };
  new Function('module', 'exports', 'window', 'document', src)(
    mod, mod.exports, global.window, global.document);
  global[name] = mod.exports;
  return mod.exports;
}
const ColorPicker = load('js/color-picker.js', 'ColorPicker');
const Labels = load('js/labels.js', 'Labels');
const css = readUi('css/labels.css');

// a fake bridge that records what the UI asked the backend to do
const calls = [];
global.App = { bridge: null };
function connect() {
  const record = (name) => (...args) => { calls.push([name, ...args]); return true; };
  global.App.bridge = {
    get_labels: (cb) => cb(JSON.stringify(Labels._fixture || {})),
    label_create: record('label_create'),
    label_update: record('label_update'),
    label_delete: record('label_delete'),
    label_assign: record('label_assign'),
    label_unassign: record('label_unassign'),
    label_set_for: record('label_set_for'),
    label_set_filter: record('label_set_filter'),
    label_clear_filter: record('label_clear_filter'),
  };
}
global.LogConsole = { log() {} };

// ── assertion kit ────────────────────────────────────────────────
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

const STATE = {
  defs: [
    { id: 'lbl_1', name: 'Rude', color: '#ff3b30' },
    { id: 'lbl_2', name: 'VIP', color: '#34c759' },
  ],
  assign: { Nick: ['lbl_1', 'lbl_2'], Other: ['lbl_1'] },
  filter: { include: [], exclude: [] },
  palette: ColorPicker.COLORS.map((c) => c.hex),
};
function reset() {
  calls.length = 0;
  body.children = [];
  Labels.applyState(JSON.parse(JSON.stringify(STATE)));
}

// ═════════════════════════════════════════════════════════════════
// the colour picker
// ═════════════════════════════════════════════════════════════════
t('there are exactly 20 preset colours', () => {
  eq(ColorPicker.COLORS.length, 20);
});

t('the palette is the 5×4 grid from the spec, in order', () => {
  eq(ColorPicker.COLORS.map((c) => c.name), [
    'Red', 'Orange', 'Yellow', 'Lime', 'Green',
    'Teal', 'Cyan', 'Sky Blue', 'Blue', 'Indigo',
    'Violet', 'Purple', 'Magenta', 'Pink', 'Hot Pink',
    'Coral', 'Amber', 'Chartreuse', 'Spring Green', 'Aqua',
  ]);
});

t('every colour is a bright hex value', () => {
  ColorPicker.COLORS.forEach((c) => {
    ok(/^#[0-9a-f]{6}$/i.test(c.hex), c.name + ' → ' + c.hex);
  });
});

t('the grid is five across and four down', () => {
  ok(/\.cp-grid[^}]*grid-template-columns:\s*repeat\(5/.test(css),
     'the CSS must lay the swatches out 5 per row');
  eq(ColorPicker.COLORS.length / 5, 4, 'four rows');
});

t('opening shows a title bar that says Pick Color, with a ✕', () => {
  body.children = [];
  const box = ColorPicker.open({ color: '#ff3b30' });
  ok(body.children.indexOf(box) >= 0, 'the popup is attached to the page');
  eq(box.querySelector('.cp-title').textContent, 'Pick Color');
  eq(box.querySelector('.cp-close').textContent, '✕');
  ok(box.querySelector('.cp-cancel'), 'a Cancel button');
  eq(box.querySelectorAll('.cp-dot').length, 20);
  ColorPicker.close();
});

t('the popup is about 280 by 320', () => {
  eq(ColorPicker.WIDTH, 280);
  eq(ColorPicker.HEIGHT, 320);
  const box = ColorPicker.open({});
  eq(box.style.width, '280px');
  ColorPicker.close();
});

t('the current colour wears the white ring', () => {
  const box = ColorPicker.open({ color: '#0a84ff' });
  const ringed = box.querySelectorAll('.cp-dot')
    .filter((d) => d.classList.contains('selected'));
  eq(ringed.length, 1);
  eq(ringed[0].dataset.color, '#0a84ff');
  // since the 2026-09-09 token completion the ring colour is the
  // --text-on-accent token — assert it resolves to white
  ok(/\.cp-dot\.selected[^}]*border-color:\s*(#fff|var\(--text-on-accent\))/i
     .test(css), 'the ring is the on-accent colour in the CSS');
  const vars = readUi('css/variables.css');
  ok(/--text-on-accent:\s*#ffffff/.test(vars),
     'and --text-on-accent is white');
  ColorPicker.close();
});

t('picking a colour reports it and closes the popup', () => {
  let got = '';
  const box = ColorPicker.open({ onPick: (hex) => { got = hex; } });
  box.querySelectorAll('.cp-dot')[6].click();
  eq(got, ColorPicker.COLORS[6].hex);
  ok(!ColorPicker.isOpen, 'the popup closes after a choice');
  eq(body.children.length, 0, 'and leaves nothing behind');
});

t('Cancel closes without choosing anything', () => {
  let got = '', cancelled = false;
  const box = ColorPicker.open({ onPick: (h) => { got = h; },
                                 onCancel: () => { cancelled = true; } });
  box.querySelector('.cp-cancel').click();
  eq(got, '');
  ok(cancelled, 'the caller is told');
  ok(!ColorPicker.isOpen);
});

t('the ✕ in the title bar closes it too', () => {
  const box = ColorPicker.open({});
  box.querySelector('.cp-close').click();
  ok(!ColorPicker.isOpen);
});

t('Escape closes it', () => {
  ColorPicker.open({});
  global.document.key('Escape');
  ok(!ColorPicker.isOpen);
});

t('the popup can be dragged by its title bar', () => {
  ColorPicker._pos = null;
  const box = ColorPicker.open({});
  const before = box.style.left;
  box.querySelector('.cp-bar').fire('pointerdown', { clientX: 120, clientY: 60 });
  firePointer('pointermove', 320, 260);
  firePointer('pointerup', 320, 260);
  ok(box.style.left !== before, 'it moved horizontally');
  eq(box.style.left, '300px');
  eq(box.style.top, '250px');
  ColorPicker.close();
});

t('it reopens where the user parked it', () => {
  const again = ColorPicker.open({});
  eq(again.style.left, '300px');
  eq(again.style.top, '250px');
  ColorPicker.close();
  ColorPicker._pos = null;
});

t('it can never be dragged off screen', () => {
  const box = ColorPicker.open({});
  box.querySelector('.cp-bar').fire('pointerdown', { clientX: 120, clientY: 60 });
  firePointer('pointermove', -900, -900);
  firePointer('pointerup', -900, -900);
  ok(parseInt(box.style.left, 10) >= 0, 'left ' + box.style.left);
  ok(parseInt(box.style.top, 10) >= 0, 'top ' + box.style.top);
  ColorPicker.close();
  ColorPicker._pos = null;
});

// ═════════════════════════════════════════════════════════════════
// the pills (People + Full User Database)
// ═════════════════════════════════════════════════════════════════
t('a person shows one pill per label, with the name and colour', () => {
  reset();
  const host = Labels.pills('Nick');
  eq(host.querySelectorAll('.label-pill').length, 2);
  const [first] = host.querySelectorAll('.label-pill');
  ok(first.textContent.indexOf('Rude') >= 0, first.textContent);
  eq(first.style.borderColor, '#ff3b30');
});

t('a person without labels gets no pills at all', () => {
  reset();
  eq(Labels.pills('Nobody').children.length, 0);
});

t('the pill text is inserted as text, never as markup', () => {
  Labels.applyState({
    defs: [{ id: 'x', name: '<img src=x onerror=alert(1)>', color: '#ff3b30' }],
    assign: { Nick: ['x'] }, filter: { include: [], exclude: [] },
  });
  const host = Labels.pills('Nick');   // the stub throws on innerHTML
  ok(host.textContent.indexOf('<img') >= 0, 'shown literally');
  reset();
});

t('every pill carries an ✕', () => {
  reset();
  const host = Labels.pills('Nick');
  eq(host.querySelectorAll('.label-pill-x').length, 2);
});

t('the ✕ removes the label from THAT person only', () => {
  reset();
  connect();
  const host = Labels.pills('Nick');
  host.querySelectorAll('.label-pill-x')[0].click();
  eq(calls.length, 1);
  eq(calls[0], ['label_unassign', 'Nick', 'lbl_1']);
  ok(!calls.some((c) => c[0] === 'label_delete'),
     'a row must never delete the label everywhere');
});

t('the ✕ never triggers the row click behind it', () => {
  reset();
  connect();
  let rowClicked = false;
  const row = mkEl('tr');
  row.addEventListener('click', () => { rowClicked = true; });
  const host = row.appendChild(Labels.pills('Nick'));
  host.querySelectorAll('.label-pill-x')[0].click();
  ok(!rowClicked, 'the click is swallowed by the pill');
});

t('a caller can render read-only pills (no ✕)', () => {
  reset();
  const host = Labels.pills('Nick', { removable: false });
  eq(host.querySelectorAll('.label-pill-x').length, 0);
});

t('both tables get the very same renderer', () => {
  const userTable = readUi('js/user-table.js');
  const userDb = readUi('js/history-db.js');
  ok(/Labels\.pills\(/.test(userTable), 'People uses Labels.pills');
  ok(/Labels\.pills\(/.test(userDb), 'the Full User Database uses Labels.pills');
});

// ═════════════════════════════════════════════════════════════════
// the filter
// ═════════════════════════════════════════════════════════════════
t('no filter means everybody passes', () => {
  reset();
  ok(!Labels.filterActive);
  ok(Labels.allows('Nick'));
  ok(Labels.allows('Nobody'));
});

t('exclude skips the labelled people (ignore "Rude")', () => {
  reset();
  Labels.applyState(Object.assign({}, STATE,
    { filter: { include: [], exclude: ['lbl_1'] } }));
  ok(Labels.filterActive);
  ok(!Labels.allows('Nick'));
  ok(!Labels.allows('Other'));
  ok(Labels.allows('Nobody'));
});

t('include is a whitelist', () => {
  Labels.applyState(Object.assign({}, STATE,
    { filter: { include: ['lbl_2'], exclude: [] } }));
  ok(Labels.allows('Nick'));
  ok(!Labels.allows('Other'));
  ok(!Labels.allows('Nobody'));
});

t('exclusion beats inclusion — same rule as the backend', () => {
  Labels.applyState(Object.assign({}, STATE,
    { filter: { include: ['lbl_2'], exclude: ['lbl_1'] } }));
  ok(!Labels.allows('Nick'), 'an ignored person stays ignored');
});

// ═════════════════════════════════════════════════════════════════
// the Label Manager window
// ═════════════════════════════════════════════════════════════════
function buildManager() {
  Object.keys(byId).forEach((k) => delete byId[k]);
  ['winLabels', 'labelActiveList', 'labelNameInput', 'labelColorBtn',
   'labelAddBtn', 'labelFilterList', 'labelIncludeBtn', 'labelExcludeBtn',
   'labelClearFilterBtn', 'labelFilterState', 'labelPersonSelect',
   'labelAssignList', 'labelAssignBtn', 'labelAssignHint', 'labelAssignTarget',
  ].forEach((id) => { byId[id] = mkEl('div'); });
  byId.labelNameInput = mkEl('input');
  byId.labelPersonSelect = mkEl('select');
  Labels._wired = false;
  Labels.selected = new Set();
  Labels.person = '';
  Labels.editing = '';
  Labels.editName = '';
  Labels.editColor = '';
  connect();
  Labels._fixture = STATE;
  Labels.init();
  Labels.applyState(JSON.parse(JSON.stringify(STATE)));
  calls.length = 0;
}

t('the manager lists every active label with a global ✕', () => {
  buildManager();
  const items = byId.labelActiveList.querySelectorAll('.label-manage-item');
  eq(items.length, 2);
  ok(items[0].textContent.indexOf('Rude') >= 0);
  eq(byId.labelActiveList.querySelectorAll('.label-del').length, 2);
});

t('that ✕ deletes the label system-wide', () => {
  buildManager();
  byId.labelActiveList.querySelectorAll('.label-del')[0].click();
  eq(calls[0], ['label_delete', 'lbl_1']);
});

t('creating a label sends the name and the chosen colour', () => {
  buildManager();
  Labels.setDraftColor('#34c759');
  byId.labelNameInput.value = '  Short answering  ';
  byId.labelAddBtn.click();
  eq(calls[0], ['label_create', 'Short answering', '#34c759']);
  eq(byId.labelNameInput.value, '', 'the field is cleared for the next one');
});

t('a nameless label is refused before it reaches the backend', () => {
  buildManager();
  byId.labelNameInput.value = '   ';
  byId.labelAddBtn.click();
  eq(calls.length, 0);
});

t('the colour button opens the picker and takes the choice', () => {
  buildManager();
  byId.labelColorBtn.click();
  ok(ColorPicker.isOpen, 'the picker opened');
  ColorPicker.pick('#e935c1');
  eq(Labels.draftColor, '#e935c1');
  eq(byId.labelColorBtn.style.background, '#e935c1');
});

t('Include Selected sends the ticked labels as an include rule', () => {
  buildManager();
  Labels.selected = new Set(['lbl_2']);
  byId.labelIncludeBtn.click();
  eq(calls[0][0], 'label_set_filter');
  eq(JSON.parse(calls[0][1]), { include: ['lbl_2'], exclude: [] });
});

t('Exclude Selected sends them as an exclude rule', () => {
  buildManager();
  Labels.selected = new Set(['lbl_1']);
  byId.labelExcludeBtn.click();
  eq(JSON.parse(calls[0][1]), { include: [], exclude: ['lbl_1'] });
});

t('a label can only be on one side of the filter', () => {
  buildManager();
  Labels.applyState(Object.assign({}, STATE,
    { filter: { include: ['lbl_1'], exclude: [] } }));
  Labels.selected = new Set(['lbl_1']);
  byId.labelExcludeBtn.click();
  eq(JSON.parse(calls[0][1]), { include: [], exclude: ['lbl_1'] });
});

t('pressing the same side again clears those labels', () => {
  buildManager();
  Labels.applyState(Object.assign({}, STATE,
    { filter: { include: [], exclude: ['lbl_1'] } }));
  Labels.selected = new Set(['lbl_1']);
  byId.labelExcludeBtn.click();
  eq(JSON.parse(calls[0][1]), { include: [], exclude: [] });
});

t('nothing ticked = nothing sent, with a hint instead', () => {
  buildManager();
  Labels.selected = new Set();
  byId.labelIncludeBtn.click();
  eq(calls.length, 0);
});

t('Clear removes the filter', () => {
  buildManager();
  byId.labelClearFilterBtn.click();
  eq(calls[0], ['label_clear_filter']);
});

t('the header explains the active filter in plain words', () => {
  buildManager();
  Labels.applyState(Object.assign({}, STATE,
    { filter: { include: [], exclude: ['lbl_1'] } }));
  const text = byId.labelFilterState.textContent;
  ok(/Rude/.test(text), text);
  ok(/never/i.test(text), text);
});

t('with no filter the header says so — no blank panel', () => {
  buildManager();
  ok(/No label filter/i.test(byId.labelFilterState.textContent),
     byId.labelFilterState.textContent);
});

t('an empty label list explains how to make one', () => {
  buildManager();
  Labels.applyState({ defs: [], assign: {}, filter: { include: [], exclude: [] } });
  ok(/Add Label/i.test(byId.labelActiveList.textContent),
     byId.labelActiveList.textContent);
});

// ── section 4: assign to person ──────────────────────────────────
t('the dropdown follows the person selected elsewhere', () => {
  buildManager();
  Labels.setPerson('Other');
  eq(byId.labelPersonSelect.value, 'Other');
  ok(/Other/.test(byId.labelAssignHint.textContent));
});

t('the ticked boxes start from what the person already carries', () => {
  buildManager();
  Labels.setPerson('Other');
  const boxes = byId.labelAssignList.querySelectorAll('input[type="checkbox"]');
  eq(boxes.length, 2);
  eq(boxes.map((b) => b.checked), [true, false]);
});

t('Assign sends the whole ticked set for that person', () => {
  buildManager();
  Labels.setPerson('Other');
  const boxes = byId.labelAssignList.querySelectorAll('input[type="checkbox"]');
  boxes[1].checked = true;
  byId.labelAssignBtn.click();
  eq(calls[0][0], 'label_set_for');
  eq(calls[0][1], 'Other');
  eq(JSON.parse(calls[0][2]), ['lbl_1', 'lbl_2']);
});

t('unticking a box removes that label from the person', () => {
  buildManager();
  Labels.setPerson('Nick');
  const boxes = byId.labelAssignList.querySelectorAll('input[type="checkbox"]');
  boxes[0].checked = false;
  byId.labelAssignBtn.click();
  eq(JSON.parse(calls[0][2]), ['lbl_2']);
});

t('with nobody selected the section says what to do', () => {
  buildManager();
  ok(/Click a nick/i.test(byId.labelAssignList.textContent),
     byId.labelAssignList.textContent);
  ok(byId.labelAssignBtn.disabled, 'Assign is disabled until a person is picked');
});

t('a person option shows the labels they already have', () => {
  buildManager();
  Labels.setPerson('Nick');
  const options = byId.labelPersonSelect.children
    .filter((o) => o.value === 'Nick');
  ok(options.length === 1, 'the person is listed once');
  ok(/Rude/.test(options[0].textContent), options[0].textContent);
});

// ── badge click = assign (the bug fix), edit = rename, ✕ = delete ──
t('each active label entry has three separate zones: badge, edit, ✕', () => {
  buildManager();
  const items = byId.labelActiveList.querySelectorAll('.label-manage-item');
  eq(items.length, 2);
  items.forEach((item) => {
    eq(item.querySelectorAll('.label-pill').length, 1, 'one badge');
    eq(item.querySelectorAll('.label-manage-edit').length, 1, 'one edit');
    eq(item.querySelectorAll('.label-del').length, 1, 'one delete');
    eq(item.querySelector('.label-manage-edit').textContent, 'edit');
  });
});

t('clicking the badge with a person selected assigns that label', () => {
  buildManager();
  Labels.setPerson('Other');          // Other carries lbl_1 (Rude) only
  calls.length = 0;
  const items = byId.labelActiveList.querySelectorAll('.label-manage-item');
  const badge = items[1].querySelector('.label-pill');   // VIP = lbl_2
  badge.click();
  eq(calls.length, 1, 'exactly one backend call');
  eq(calls[0], ['label_assign', 'Other', 'lbl_2']);
});

t('clicking the badge of an already-assigned label takes it away', () => {
  buildManager();
  Labels.setPerson('Other');          // Other carries lbl_1 (Rude)
  calls.length = 0;
  const items = byId.labelActiveList.querySelectorAll('.label-manage-item');
  items[0].querySelector('.label-pill').click();   // Rude = lbl_1
  eq(calls[0], ['label_unassign', 'Other', 'lbl_1']);
});

t('a badge click with no person selected assigns nothing', () => {
  buildManager();
  calls.length = 0;
  const items = byId.labelActiveList.querySelectorAll('.label-manage-item');
  items[0].querySelector('.label-pill').click();
  eq(calls.length, 0, 'no backend call without a target');
  ok(byId.labelActiveList.textContent.indexOf('Rude') >= 0,
     'the list itself is untouched');
});

t('the badges of the current target wear the assigned ring and a ✓', () => {
  buildManager();
  Labels.setPerson('Nick');           // Nick carries both labels
  const pills = byId.labelActiveList.querySelectorAll('.label-pill');
  eq(pills.length, 2);
  eq(pills.filter((p) => p.classList.contains('assigned')).length, 2);
  ok(pills[0].textContent.indexOf('✓') >= 0, pills[0].textContent);
});

t('the badge tooltip says what the click will do', () => {
  buildManager();
  Labels.setPerson('Other');
  const items = byId.labelActiveList.querySelectorAll('.label-manage-item');
  const badge = items[1].querySelector('.label-pill');   // VIP, not assigned
  ok(/assign.*VIP.*Other/i.test(badge.title), badge.title);
  const taken = items[0].querySelector('.label-pill');   // Rude, assigned
  ok(/take.*Rude.*away/i.test(taken.title), taken.title);
});

t('clicking "edit" opens an inline editor prefilled with name and colour', () => {
  buildManager();
  byId.labelActiveList.querySelectorAll('.label-manage-edit')[0].click();
  eq(byId.labelActiveList.querySelectorAll('.label-edit-row').length, 1,
     'the entry becomes the editor');
  const input = byId.labelActiveList.querySelector('.label-edit-input');
  eq(input.value, 'Rude');
  eq(byId.labelActiveList.querySelector('.label-edit-color').style.background,
     '#ff3b30');
  ok(/Save/.test(byId.labelActiveList.textContent), 'a Save button');
  ok(/Cancel/.test(byId.labelActiveList.textContent), 'a Cancel button');
});

t('saving the editor sends only the changed fields to label_update', () => {
  buildManager();
  byId.labelActiveList.querySelectorAll('.label-manage-edit')[0].click();
  const input = byId.labelActiveList.querySelector('.label-edit-input');
  input.value = 'Annoying';
  input.fire('input');
  byId.labelActiveList.querySelector('.label-edit-color').click();
  ColorPicker.pick('#e935c1');
  byId.labelActiveList.querySelector('.label-edit-save').click();
  eq(calls.length, 1);
  eq(calls[0], ['label_update', 'lbl_1', 'Annoying', '#e935c1']);
  eq(byId.labelActiveList.querySelectorAll('.label-edit-row').length, 0,
     'the editor closes after saving');
});

t('Enter saves the editor, Escape cancels it', () => {
  buildManager();
  byId.labelActiveList.querySelectorAll('.label-manage-edit')[0].click();
  let input = byId.labelActiveList.querySelector('.label-edit-input');
  input.fire('keydown', { key: 'Escape' });
  eq(byId.labelActiveList.querySelectorAll('.label-edit-row').length, 0);
  eq(calls.length, 0, 'cancel touches nothing');

  byId.labelActiveList.querySelectorAll('.label-manage-edit')[0].click();
  input = byId.labelActiveList.querySelector('.label-edit-input');
  input.value = 'Annoying';
  input.fire('input');
  input.fire('keydown', { key: 'Enter' });
  eq(calls[0], ['label_update', 'lbl_1', 'Annoying', '']);
});

t('renaming to the same name sends nothing at all', () => {
  buildManager();
  byId.labelActiveList.querySelectorAll('.label-manage-edit')[0].click();
  byId.labelActiveList.querySelector('.label-edit-save').click();
  eq(calls.length, 0);
  eq(byId.labelActiveList.querySelectorAll('.label-edit-row').length, 0);
});

t('the ✕ still deletes system-wide and never assigns', () => {
  buildManager();
  Labels.setPerson('Other');
  calls.length = 0;
  byId.labelActiveList.querySelectorAll('.label-del')[0].click();
  eq(calls.length, 1);
  eq(calls[0], ['label_delete', 'lbl_1']);
  ok(!calls.some((c) => c[0] === 'label_assign'),
     'the ✕ must not double as an assign click');
});

// ── quick assign: the target chip and the table row highlight ────
t('the target chip follows the person selected elsewhere', () => {
  buildManager();
  eq(byId.labelAssignTarget.textContent, 'click a person to quick-assign');
  ok(!byId.labelAssignTarget.classList.contains('on'));
  Labels.setPerson('Other');
  ok(/Other/.test(byId.labelAssignTarget.textContent),
     byId.labelAssignTarget.textContent);
  ok(byId.labelAssignTarget.classList.contains('on'));
});

t('setPerson keeps Section 4 and the hint in sync', () => {
  buildManager();
  Labels.setPerson('Other');
  eq(byId.labelPersonSelect.value, 'Other');
  ok(/Other/.test(byId.labelAssignHint.textContent),
     byId.labelAssignHint.textContent);
});

t('the People table rows carry data-nick and react to plain row clicks', () => {
  const src = readUi('js/user-table.js');
  ok(/<tr class="\$\{rowCls\}" data-nick="\$\{attr\}">/.test(src),
     'every row is addressable by nick');
  ok(/Labels\.setPerson\(row\.dataset\.nick\)/.test(src),
     'a click anywhere on the row targets the person');
  ok(/markLabelTarget\(nick\)/.test(src),
     'the target highlight moves in place');
  ok(/row-label-target/.test(src), 'render stamps the target class');
});

t('the Storage table also follows the quick-assign target', () => {
  const src = readUi('js/history-db.js');
  ok(/markLabelTarget\(nick\)/.test(src),
     'the target highlight moves in place');
  ok(/row-label-target/.test(src), 'render stamps the target class');
});

t('the CSS styles the zones, the chip and the target row', () => {
  ok(/\.label-manage-edit/.test(css), 'the edit zone is styled');
  ok(/\.label-pill-check/.test(css), 'the assigned ✓ is styled');
  ok(/\.label-edit-row/.test(css), 'the inline editor is styled');
  ok(/\.label-target-chip/.test(css), 'the target chip is styled');
  ok(/tr\.row-label-target/.test(css), 'the target row is highlighted');
});

// ── reporting ────────────────────────────────────────────────────
console.log('labels_ui: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
