/* chat_agent-push.js — the MutationObserver push buffer: buffer new lines
   and push a debounced notification through the `__cvbPush` binding, so
   Python feels responsive without polling (Round II Area A).

   Split out of backend/js/chat_agent.js; the install facade lists its
   parts. Owns the push-policy constants (BUFFER_MAX, PUSH_DEBOUNCE_MS)
   and ALL observer/buffer module state — re-created per install exactly
   like the old IIFE locals. Cross-part calls resolve at call time.
*/
'use strict';

const ChatAgentPush = {
  BUFFER_MAX: 500,         // push buffer cap before we start dropping
  PUSH_DEBOUNCE_MS: 120,

  _buffer: [],
  _dropped: 0,
  _observer: null,
  _observedRoot: null,
  _pushTimer: null,

  pending() { return this._buffer.length; },
  droppedCount() { return this._dropped; },

  bufferRecord(record) {
    this._buffer.push(ChatAgentParse.strip(record));
    while (this._buffer.length > this.BUFFER_MAX) {
      this._buffer.shift(); this._dropped++;
    }
  },

  schedulePush(count, kind) {
    if (this._pushTimer) clearTimeout(this._pushTimer);
    var self = this;
    this._pushTimer = setTimeout(function () {
      self._pushTimer = null;
      self.sendPush(count, kind);
    }, this.PUSH_DEBOUNCE_MS);
  },

  sendPush(count, kind) {
    var hook = window.__cvbPush;
    if (typeof hook !== 'function') return;
    var summary = ChatAgentPane.describe();
    var authors = ChatAgentParse.authorsOf(ChatAgentParse.walk());
    try {
      hook(JSON.stringify({
        kind: kind || 'append',
        agent: ChatAgent.version,
        count: count,
        partner: summary.partner,
        title: summary.title,
        me: summary.me,
        tab: summary.tab,
        in_authors: authors.inbound,
        out_authors: authors.outbound,
        authors: authors.all,
        pending: this._buffer.length,
        dropped: this._dropped,
        items: this._buffer.slice(-this.BUFFER_MAX),
      }));
    } catch (e) { /* the page must never break because we cannot push */ }
  },

  /** Message nodes added by these mutations (descend into wrappers). */
  addedMessageNodes(mutations) {
    var added = [];
    for (var i = 0; i < mutations.length; i++) {
      var nodes = mutations[i].addedNodes || [];
      for (var j = 0; j < nodes.length; j++) {
        var node = nodes[j];
        if (!node || typeof node.querySelectorAll !== 'function') continue;
        if (node.classList && node.classList.contains('message-container')) {
          added.push(node);
        } else {
          added = added.concat(ChatAgentDom.qsa(node, 'div.message-container'));
        }
      }
    }
    return added;
  },

  onMutations(mutations) {
    var added = this.addedMessageNodes(mutations);
    if (!added.length) return;
    var records = ChatAgentParse.walk();
    var byNode = new Map();
    for (var k = 0; k < records.length; k++)
      byNode.set(records[k].node, records[k]);
    var tail = true;
    for (var a = 0; a < added.length; a++) {
      var record = byNode.get(added[a]);
      if (!record) continue;
      if (record.idx < records.length - added.length) tail = false;
      this.bufferRecord(record);
    }
    this.schedulePush(records.length, tail ? 'append' : 'change');
  },

  install() {
    var root = ChatAgentPane.messagesRoot();
    if (!root || typeof MutationObserver !== 'function') return false;
    if (this._observer) this._observer.disconnect();
    var self = this;
    this._observer = new MutationObserver(function (m) { self.onMutations(m); });
    this._observer.observe(root, { childList: true, subtree: true });
    this._observedRoot = root;
    return true;
  },

  /* Switching tabs swaps the whole pane. An observer left on the old pane
     would keep pushing the previous (or the room's) conversation, so every
     probe re-checks that we are watching the pane that is on screen. */
  reattach() {
    var root = ChatAgentPane.messagesRoot();
    if (root && root !== this._observedRoot) {
      this._buffer = [];
      this.install();
    }
  },

  uninstall() {
    if (this._observer) { this._observer.disconnect(); this._observer = null; }
    this._observedRoot = null;
    if (this._pushTimer) { clearTimeout(this._pushTimer); this._pushTimer = null; }
  },

  /** Take whatever the observer buffered since the last drain. */
  drain() {
    var items = this._buffer;
    var lost = this._dropped;
    this._buffer = [];
    this._dropped = 0;
    return { ok: true, items: items, dropped: lost };
  },
};
