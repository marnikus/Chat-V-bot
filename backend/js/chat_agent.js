/* In-page collector agent — install facade (Round II Area A split, 803→~140).

   Injected once per document (Runtime.evaluate now, and
   Page.addScriptToEvaluateOnNewDocument for later navigations). Everything
   expensive happens in the parts, in the page, where the DOM is local:

     * every message node is parsed at most once (chat_agent-parse.js);
     * `state()` ships a summary, never the conversation;
     * `slice(a, b)` ships exactly the range Python asked for;
     * a MutationObserver buffers new lines and pushes a debounced
       notification through `__cvbPush` (chat_agent-push.js).

   The fingerprint is mirrored byte-for-byte in Python
   (backend/history_models.py) and both are pinned by tests.

   Kept ES5-ish on purpose: it has to run inside whatever the site's
   renderer is, without a build step.

   Parts loaded before this one — see backend/chat_agent_js.py PARTS
   (install concatenates them in this order, like <script> tags):
     chat_agent-fingerprint.js, chat_agent-dom.js, chat_agent-parse.js,
     chat_agent-pane.js, chat_agent-push.js, chat_agent-scroll.js
*/
'use strict';

var CVB_AGENT_VERSION = 11;
var CVB_HEAD_FPS = 5;       // how many leading fingerprints state() ships
var CVB_TAIL_FPS = 25;      // …and how many trailing ones

var ChatAgent = {
  version: CVB_AGENT_VERSION,

  /** state() with no chat on the page (no anchor, no message nodes). */
  emptyState() {
    return { ok: false, reason: 'no chat on this page',
             agent: this.version, tab: 'none', partner: '', title: '',
             me: '', participants: 0, count: 0, head: [], tail: [],
             authors: [], in_authors: [], out_authors: [], panes: 0,
             pending: ChatAgentPush.pending(),
             scroll: { top: 0, height: 0, client: 0 } };
  },

  /** The ok:true payload of state() (assembled from the walk's records). */
  okState(records, summary, authors, pv) {
    var fps = records.map(function (r) { return r.fp; });
    var anyFps = records.map(function (r) { return r.fpAny || ''; });
    return {
      ok: true,
      agent: this.version,
      tab: summary.tab,
      partner: summary.partner,
      title: summary.title,
      me: summary.me,
      participants: summary.participants,
      count: records.length,
      authors: authors.all,
      in_authors: authors.inbound,
      out_authors: authors.outbound,
      panes: pv.panes,
      pane_source: pv.source || '',
      pane_same: !!pv.sameAsLast,
      head: fps.slice(0, CVB_HEAD_FPS),
      tail: fps.slice(Math.max(0, fps.length - CVB_TAIL_FPS)),
      head_any: anyFps.slice(0, CVB_HEAD_FPS),
      tail_any: anyFps.slice(Math.max(0, anyFps.length - CVB_TAIL_FPS)),
      pending: ChatAgentPush.pending(),
      dropped: ChatAgentPush.droppedCount(),
      scroll: ChatAgentScroll.scrollInfo(),
    };
  },

  /** A cheap summary of the conversation — never its contents. */
  state() {
    ChatAgentPush.reattach();
    var anchor = ChatAgentDom.qs(document, 'app-messages') ||
                 ChatAgentDom.qs(document, '.messages-root') ||
                 ChatAgentDom.qs(document, '.tab-item.active');
    if (!anchor && !ChatAgentPane.containers().length)
      return this.emptyState();
    var records = ChatAgentParse.walk();
    return this.okState(records, ChatAgentPane.describe(),
                        ChatAgentParse.authorsOf(records),
                        ChatAgentPane.visiblePane());
  },

  /** Exactly the half-open range [from, to) of message records. */
  slice(from, to) {
    ChatAgentPush.reattach();
    var records = ChatAgentParse.walk();
    var a = Math.max(0, Math.min(records.length, ChatAgentDom.num(from)));
    var b = Math.max(a, Math.min(records.length, ChatAgentDom.num(to)));
    return { ok: true, from: a, to: b, count: records.length,
             items: records.slice(a, b).map(ChatAgentParse.strip,
                                            ChatAgentParse) };
  },

  drain() { return ChatAgentPush.drain(); },

  fingerprint(dir, from, time, kind, payload, occ) {
    return ChatAgentFp.fingerprint(dir, from, time, kind, payload, occ);
  },

  scrollToTop() { return ChatAgentScroll.scrollToTop(); },
  restoreScroll(top) { return ChatAgentScroll.restoreScroll(top); },

  stats() {
    var s = ChatAgentParse.statsSnapshot();
    return { parsed: s.parsed, cached: s.cached, walks: s.walks,
             pending: ChatAgentPush.pending(),
             dropped: ChatAgentPush.droppedCount() };
  },

  install() { return ChatAgentPush.install(); },
  uninstall() { ChatAgentPush.uninstall(); },
};

// Install-once guard: a same-version agent stays; an older one (or the
// collector restarting) is replaced after uninstalling cleanly.
(function installChatAgent() {
  if (window.__cvbAgent && window.__cvbAgent.version === CVB_AGENT_VERSION) {
    return window.__cvbAgent.version;
  }
  if (window.__cvbAgent && window.__cvbAgent.uninstall) {
    try { window.__cvbAgent.uninstall(); } catch (e) { /* ignore */ }
  }
  window.__cvbAgent = ChatAgent;
  ChatAgent.install();
  return CVB_AGENT_VERSION;
})();
