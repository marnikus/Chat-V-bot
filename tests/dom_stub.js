/* Minimal DOM stub for the chat-page agent tests.

   It is deliberately small: it implements ONLY the DOM surface the in-page
   agent (backend/js/chat_agent.js) is allowed to use, so the stub doubles
   as the agent's API contract. If the agent ever reaches for something
   else, these tests break — which is the point.

   Supported:
     document.querySelector / querySelectorAll
     element.querySelector / querySelectorAll / children / childElementCount
     element.classList.contains / className / textContent / getAttribute
     element.offsetParent / parentElement / tagName
     MutationObserver(childList on a single target) — fired by env.emit()
     setTimeout / clearTimeout — run by env.flushTimers()

   Selector support: comma groups, descendant combinators, and compound
   selectors of tag + .class + [attr] / [attr="value"].

   The page shape mirrors the real saved pages in this repository
   (Вирт чат privat.html / Вирт чат.html) — see docs DOM_SELECTORS.md.
*/
'use strict';

// ── selector engine ──────────────────────────────────────────────

function parseCompound(part) {
  const out = { tag: '', classes: [], attrs: [] };
  const re = /([.#]?[\w-]+)|\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/g;
  let m;
  while ((m = re.exec(part))) {
    if (m[2]) out.attrs.push([m[2], m[3] === undefined ? null : m[3]]);
    else if (m[1][0] === '.') out.classes.push(m[1].slice(1));
    else out.tag = m[1].toLowerCase();
  }
  return out;
}

function matchesCompound(el, c) {
  if (c.tag && el.tagName.toLowerCase() !== c.tag) return false;
  for (const cls of c.classes) if (!el.classList.contains(cls)) return false;
  for (const [name, value] of c.attrs) {
    const got = el.getAttribute(name);
    if (got === null || got === undefined) return false;
    if (value !== null && String(got) !== value) return false;
  }
  return true;
}

function descendants(root, out) {
  out = out || [];
  for (const c of root.children) { out.push(c); descendants(c, out); }
  return out;
}

function queryAll(root, selector) {
  const found = [];
  for (const group of String(selector).split(',')) {
    const parts = group.trim().split(/\s+/).filter(Boolean).map(parseCompound);
    if (!parts.length) continue;
    let level = descendants(root);
    for (let i = 0; i < parts.length; i++) {
      const compound = parts[i];
      const hits = level.filter((el) => matchesCompound(el, compound));
      if (i === parts.length - 1) {
        hits.forEach((h) => { if (found.indexOf(h) < 0) found.push(h); });
      } else {
        level = hits.reduce((acc, h) => acc.concat(descendants(h)), []);
      }
    }
  }
  return found;
}

// ── element ──────────────────────────────────────────────────────

class El {
  constructor(tag, opts) {
    opts = opts || {};
    this.tagName = String(tag).toUpperCase();
    this.className = opts.class || '';
    this._text = opts.text || '';
    this._attrs = opts.attrs || {};
    this.children = [];
    this.parentElement = null;
    this.hidden = !!opts.hidden;
  }
  get classList() {
    const cls = String(this.className).trim().split(/\s+/).filter(Boolean);
    return { contains: (c) => cls.indexOf(c) >= 0 };
  }
  get childElementCount() { return this.children.length; }
  get offsetParent() { return this.hidden ? null : (this.parentElement || {}); }
  get textContent() {
    if (!this.children.length) return this._text;
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  set textContent(v) { this._text = v; this.children = []; }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this._attrs, name)
      ? this._attrs[name] : null;
  }
  setAttribute(name, value) { this._attrs[name] = value; }
  append(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }
  remove(child) {
    const i = this.children.indexOf(child);
    if (i >= 0) this.children.splice(i, 1);
  }
  querySelector(sel) { return queryAll(this, sel)[0] || null; }
  querySelectorAll(sel) { return queryAll(this, sel); }
}

const el = (tag, opts, kids) => {
  const node = new El(tag, opts);
  (kids || []).forEach((k) => node.append(k));
  return node;
};

// ── page builder — mirrors the real Angular markup ───────────────

function messageNode(m) {
  const inner = [];
  inner.push(el('span', { class: 'additional-icon' }, [
    el('mat-icon', { attrs: { 'data-mat-icon-name': m.gender || 'male' } }),
    el('mat-icon', { attrs: { 'data-mat-icon-name': m.badge || 'anonymous' } }),
  ]));
  inner.push(el('span', { class: 'mat-mdc-menu-trigger from',
                          text: m.from }));
  inner.push(el('span', { text: ' ▸ ' }));
  if (m.media) {
    inner.push(el('app-chat-image', {}, [
      el('div', { class: 'image-wrapper' }, [
        el('mat-icon', { class: 'source-indicator',
                         attrs: { 'data-mat-icon-name': 'image' } }),
        el('img', { attrs: { src: m.media, loading: 'lazy',
                             alt: 'chat image' } }),
      ]),
    ]));
  } else {
    inner.push(el('span', { class: 'message', text: m.text || '' }));
  }
  const container = el('div', {
    class: 'message-container ' + (m.dir === 'out' ? 'my-message-background'
                                                   : 'general-background'),
  }, [
    el('mat-menu', {}),
    el('div', { class: 'message-content' }, [
      el('p', { class: 'message' }, inner),
      el('div', { class: 'message-status' }, [
        el('span', { class: 'sent-time', text: m.time || '17:31' }),
        el('span', { class: 'sent state-icon' }),
      ]),
    ]),
  ]);
  return el('div', {}, [container,
                        el('mat-divider', { class: 'mat-divider' })]);
}

function tabNode(spec) {
  const kids = [
    el('mat-icon', { class: 'chat-type-icon',
                     attrs: { 'data-mat-icon-name': spec.kind } }),
    el('p', { class: 'chat-title', text: spec.title },
       spec.unread ? [el('span', { class: 'unread', text: String(spec.unread) })]
                   : []),
  ];
  if (spec.kind === 'user') kids.push(el('button', { class: 'tab-close-button' }));
  return el('div', {
    class: 'cdk-drag mat-ripple tab-item' + (spec.active ? ' active' : ''),
    attrs: { role: 'tab' },
  }, kids);
}

function userItem(nick, me) {
  return el('container-item', {}, [
    el('user-item', {}, [
      el('div', { class: 'user-container' }, [
        el('avatar-item', {}, [
          el('div', { class: 'avatar-wrapper female-avatar guest-avatar' }),
        ]),
        el('div', { class: 'text-stack' }, [
          el('div', { class: 'primary-text-line' }, [
            el('span', { class: 'primary-text' + (me ? ' bold' : ''),
                         text: ' ' + nick + ' ' }),
          ]),
        ]),
      ]),
    ]),
  ]);
}

/**
 * Build a page environment.
 *   buildChat({ tab:'private'|'room', partner, me, participants, messages:[…] })
 * Returns { window, document, root, append, prepend, trim, emit, flushTimers,
 *           pushes, observers }.
 */
function buildChat(spec) {
  spec = spec || {};
  const partner = spec.partner || 'На работе 25';
  const me = spec.me || 'HiHoney';
  const participants = spec.participants == null ? 2 : spec.participants;
  const kind = spec.tab === 'room' ? 'room' : 'user';

  const messagesRoot = el('div', { class: 'messages-root' });
  (spec.messages || []).forEach((m) => messagesRoot.append(messageNode(m)));

  const userRows = [el('container-item', {}, [
    el('users-header-item', {}, [
      el('div', { class: 'header-container' }, [
        el('div', { class: 'text-stack' }, [
          el('div', { class: 'primary-text-line' }, [
            el('span', { class: 'primary-text', text: 'Пользователи' }),
          ]),
          el('div', { class: 'secondary-text' }, [
            el('span', { class: 'users-counter', text: String(participants) }),
          ]),
        ]),
      ]),
    ]),
  ]), userItem(me, true), userItem(partner, false)];
  for (let i = 2; i < participants; i++) userRows.push(userItem('Extra' + i));

  const root = el('body', {}, [
    el('app-tab-scroller', {}, [
      el('div', { class: 'tabs-list' }, [
        tabNode({ kind: 'room', title: 'Гостиная', active: kind === 'room',
                  unread: 5 }),
        tabNode({ kind: 'user', title: partner, active: kind === 'user' }),
      ]),
    ]),
    el('div', { class: 'container' }, [
      el('app-messages', { class: 'messages' }, [messagesRoot]),
      el('users-list', {}, [
        el('cdk-virtual-scroll-viewport', { class: 'users-list-viewport' },
           userRows),
      ]),
    ]),
  ]);

  const timers = [];
  const observers = [];
  const pushes = [];

  class MutationObserverStub {
    constructor(cb) { this.cb = cb; this.target = null; observers.push(this); }
    observe(target) { this.target = target; }
    disconnect() { this.target = null; }
  }

  const win = {
    __cvbPush: (payload) => { pushes.push(payload); },
    MutationObserver: MutationObserverStub,
  };
  const doc = {
    querySelector: (s) => queryAll(root, s)[0] || null,
    querySelectorAll: (s) => queryAll(root, s),
    body: root,
  };

  const env = {
    window: win,
    document: doc,
    root,
    messagesRoot,
    pushes,
    observers,
    MutationObserver: MutationObserverStub,
    setTimeout: (fn, ms) => { timers.push(fn); return timers.length; },
    clearTimeout: () => {},
    flushTimers() {
      const pending = timers.splice(0, timers.length);
      pending.forEach((fn) => fn());
    },
    append(...msgs) {
      const nodes = msgs.map((m) => { const n = messageNode(m);
                                      messagesRoot.append(n); return n; });
      env.emit(nodes);
      return nodes;
    },
    prepend(...msgs) {
      const nodes = msgs.map((m) => messageNode(m));
      messagesRoot.children = nodes.concat(messagesRoot.children);
      nodes.forEach((n) => { n.parentElement = messagesRoot; });
      env.emit(nodes);
      return nodes;
    },
    trim(keep) {
      messagesRoot.children = messagesRoot.children.slice(-keep);
    },
    emit(added) {
      observers.forEach((o) => {
        if (o.target === messagesRoot) o.cb([{ addedNodes: added }], o);
      });
    },
    setTab(kindNext) {
      queryAll(root, '.tab-item').forEach((tab) => {
        const icon = tab.querySelector('mat-icon.chat-type-icon');
        const isRoom = icon.getAttribute('data-mat-icon-name') === 'room';
        const active = (kindNext === 'room') === isRoom;
        tab.className = 'cdk-drag mat-ripple tab-item' + (active ? ' active' : '');
      });
    },
  };
  return env;
}

module.exports = { buildChat, El, el, queryAll, messageNode };
