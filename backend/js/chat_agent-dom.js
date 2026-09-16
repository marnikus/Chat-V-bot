/* chat_agent-dom.js — tiny DOM helpers + identification-free people facts
   (Round II Area A).

   Split out of backend/js/chat_agent.js; the install facade lists its
   parts. Everything here is pure: a function reads nodes it is handed and
   returns values, never the conversation. Rule kept from the original:
   identification NEVER comes from avatars or icons — `containerOf` /
   `countPaneUsers` count rendered user-items only (2026-09-08 bug class).
*/
'use strict';

const ChatAgentDom = {
  qs(root, sel) {
    try { return root ? root.querySelector(sel) : null; }
    catch (e) { return null; }
  },

  qsa(root, sel) {
    try { return root ? Array.prototype.slice.call(root.querySelectorAll(sel)) : []; }
    catch (e) { return []; }
  },

  clean(text) { return String(text == null ? '' : text).trim(); },

  /** text of `el` without the text of its child elements (unread badges…) */
  ownText(el) {
    if (!el) return '';
    var text = String(el.textContent || '');
    var kids = el.children || [];
    for (var i = 0; i < kids.length; i++) {
      var kid = String(kids[i].textContent || '');
      if (kid) text = text.replace(kid, '');
    }
    return this.clean(text);
  },

  isAncestor(maybe, node) {
    for (var p = node; p; p = p.parentElement) if (p === maybe) return true;
    return false;
  },

  num(value) { var n = Number(value); return isFinite(n) ? n : 0; },

  normNick(x) {
    return String(x == null ? '' : x).trim().toLowerCase();
  },

  distinctNicks(names, maxN) {
    var out = [];
    for (var i = 0; i < names.length; i++) {
      var n = this.clean(names[i]);
      if (n && out.indexOf(n) < 0 && out.length < maxN) out.push(n);
    }
    return out;
  },

  isHidden(el) {
    if (!el) return true;
    var tag = String(el.tagName || '').toLowerCase();
    if (tag === 'body' || tag === 'html') return false;
    if (el.hidden === true) return true;
    if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return true;
    if ('offsetParent' in el && el.offsetParent === null) return true;
    return false;
  },

  visible(el) {
    for (var p = el; p; p = p.parentElement) if (this.isHidden(p)) return false;
    return true;
  },

  inDocument(el) {
    for (var p = el; p; p = p.parentElement) {
      if (p === document || p === document.body) return true;
    }
    return false;
  },

  classContains(cls, token) {
    if (!cls) return false;
    return cls.indexOf(token) >= 0;
  },

  containerOf(el) {
    for (var p = el; p; p = p.parentElement) {
      var cls = String(p.className || '');
      if (this.classContains(cls, 'container') ||
          this.classContains(cls, 'pane-host'))
        return p;
    }
    return null;
  },

  /** The pane's own people, counted without any identification metadata.
   *
   * A private pane can render without a readable `.users-counter` —
   * exactly the identification-free chats this agent must still serve.
   * Counting DISTINCT user-item nicks (the partner and me) keeps the
   * "exactly two people" fact available; no avatar class or gender icon
   * is consulted. */
  countPaneUsers(container) {
    if (!container) return 0;
    var items = this.qsa(container, 'user-item'), seen = {}, n = 0;
    for (var i = 0; i < items.length; i++) {
      var el = this.qs(items[i], '.primary-text');
      var nick = this.normNick(el ? el.textContent : '');
      if (!nick || seen[nick]) continue;
      seen[nick] = 1;
      n += 1;
    }
    return n;
  },
};
