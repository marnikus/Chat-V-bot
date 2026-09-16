/* chat_agent-scroll.js — the scroll probes: where the conversation is
   scrolled to, scroll-to-top, and restore (Round II Area A).

   Split out of backend/js/chat_agent.js; the install facade lists its
   parts. Owns `_lastBeforeTops` (module state, per-install like the old
   IIFE local). Cross-part calls resolve at call time.
*/
'use strict';

const ChatAgentScroll = {
  _lastBeforeTops: [],

  scrollMetrics(box) {
    return { top: ChatAgentDom.num(box.scrollTop),
             height: ChatAgentDom.num(box.scrollHeight),
             client: ChatAgentDom.num(box.clientHeight) };
  },

  scrollInfo() {
    var box = this.chatScroller();
    var top = ChatAgentDom.num(box.scrollTop),
        height = ChatAgentDom.num(box.scrollHeight),
        client = ChatAgentDom.num(box.clientHeight);
    return { top: top, height: height, client: client,
             atTop: top <= 4,
             atBottom: height === 0 || top + client >= height - 4 };
  },

  /** Whether `el` is one of the real scrollers: the messages root, a
     virtual-scroll viewport, or an ancestor with scrolling overflow. */
  scrollerClassify(el, root) {
    var tag = String(el.tagName || '').toLowerCase();
    var cls = '';
    if (el.classList && el.classList.contains) {
      cls = String(el.className || '');
    } else if (el.getAttribute) {
      cls = String(el.getAttribute('class') || '');
    }
    var isMessagesRoot = cls.indexOf('messages-root') >= 0 ||
                         tag === 'app-messages';
    var isVirtual = cls.indexOf('cdk-virtual-scrollable') >= 0 ||
                    cls.indexOf('virtual-scroll-viewport') >= 0;
    var overflow = '';
    try {
      if (typeof window.getComputedStyle === 'function' && el !== root) {
        overflow = String(window.getComputedStyle(el).overflowY || '')
          .toLowerCase();
      }
    } catch (e) { /* stubs without computed style */ }
    return isMessagesRoot || isVirtual ||
           overflow === 'scroll' || overflow === 'auto';
  },

  /** Every element that can actually scroll the conversation.
   *
   * `messagesRoot()` returns the CONTENT wrapper (the observer's element),
   * not necessarily the box that has `overflow-y:scroll`. We therefore
   * walk up from that wrapper and collect the real scrollers. The first
   * such element is what `state()` reports and `scrollToTop()` drives. */
  scrollerCandidates() {
    var root = ChatAgentPane.messagesRoot() || ChatAgentPane.visiblePane().pane ||
               ChatAgentDom.qs(document, '.messages-root') ||
               ChatAgentDom.qs(document, 'app-messages');
    var candidates = [], seen = [];
    for (var el = root; el; el = el.parentElement) {
      if (seen.indexOf(el) >= 0) break;
      seen.push(el);
      if (this.scrollerClassify(el, root)) candidates.push(el);
    }
    if (!candidates.length) candidates.push(root || {});
    return candidates;
  },

  chatScroller() {
    return this.scrollerCandidates()[0];
  },

  dispatchScroll(box) {
    if (box && typeof box.dispatchEvent === 'function' &&
        typeof window.Event === 'function') {
      try { box.dispatchEvent(new Event('scroll', { bubbles: true })); }
      catch (e) { /* a stub with no Event must never break the collector */ }
    }
  },

  /** Scroll the chat to the very first message. Returns the old position. */
  scrollToTop() {
    ChatAgentPush.reattach();
    this._lastBeforeTops = [];
    var boxes = this.scrollerCandidates();
    var primary = boxes[0];
    var beforeTop = ChatAgentDom.num(primary.scrollTop);
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i];
      this._lastBeforeTops.push(ChatAgentDom.num(box.scrollTop));
      if (typeof box.scrollTo === 'function') {
        try {
          box.scrollTo({ top: 0, behavior: 'auto' });
        } catch (e) {
          try { box.scrollTo(0, 0); } catch (e2) { /* ignore */ }
        }
      }
      box.scrollTop = 0;
      this.dispatchScroll(box);
    }
    var top = ChatAgentDom.num(primary.scrollTop);
    return { ok: true, beforeTop: beforeTop, top: top,
             atTop: top <= 4, height: ChatAgentDom.num(primary.scrollHeight),
             count: ChatAgentPane.containers().length, boxes: boxes.length };
  },

  /** Put the conversation back where the user had it. */
  restoreScroll(top) {
    ChatAgentPush.reattach();
    var boxes = this.scrollerCandidates();
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i];
      var target = i < this._lastBeforeTops.length
        ? this._lastBeforeTops[i] : ChatAgentDom.num(top);
      box.scrollTop = target;
      this.dispatchScroll(box);
    }
    var primary = boxes[0] || {};
    return { ok: true, top: ChatAgentDom.num(primary.scrollTop) };
  },
};
