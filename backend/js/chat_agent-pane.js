/* chat_agent-pane.js — the conversation pane model: which pane is on
   screen, and who the pane itself says is talking (Round II Area A).

   Split out of backend/js/chat_agent.js; the install facade lists its
   parts. The site keeps every open chat alive in the DOM (the main room
   plus one pane per private tab); parsing `document.querySelectorAll`
   blindly mixes them — room messages used to end up in a person's
   archive. Everything here therefore works on ONE pane: the visible one.

   Owns the pane stickiness state (`_lastPane`, `_lastPartner`) — module
   state, re-created per install exactly like the old IIFE locals.
   Cross-part calls resolve at call time (objects, not bare functions).
*/
'use strict';

const ChatAgentPane = {
  _lastPane: null,
  _lastPartner: '',

  /** the conversation pane a message node belongs to (innermost match) */
  paneOf(node) {
    for (var p = node; p; p = p.parentElement) {
      if (p.classList && p.classList.contains('messages-root')) return p;
      if (String(p.tagName || '').toLowerCase() === 'app-messages') return p;
    }
    return null;
  },

  paneGroups(nodes) {
    var panes = [], groups = [];
    for (var i = 0; i < nodes.length; i++) {
      var pane = this.paneOf(nodes[i]);
      var at = panes.indexOf(pane);
      if (at < 0) { panes.push(pane); groups.push({ pane: pane, nodes: [] }); }
      groups[panes.indexOf(pane)].nodes.push(nodes[i]);
    }
    return groups;
  },

  /** Author-evidence score of one pane group.
   *
   * v6: hiding is not always `display:none` — a main-room pane can still
   * report a measurable `offsetParent` and, being longer, would win "most
   * nodes". The active tab already says WHO we are talking to, so the pane
   * whose inbound authors are exactly the active partner (no strangers)
   * beats a longer room pane. */
  scoreGroup(group, wantsPrivate, title, me) {
    var authors = ChatAgentParse.groupAuthors(group);
    var score = 0;
    if (wantsPrivate && title) {
      var ins = authors.inbound;
      var outs = authors.outbound;
      var insAllPartner = ins.length > 0 &&
        ins.every(function (a) { return ChatAgentDom.normNick(a) === title; });
      var insForeign = ins.filter(function (a) {
        return ChatAgentDom.normNick(a) !== title;
      }).length;
      var outsMe = outs.length > 0 &&
        (me ? outs.every(function (a) { return ChatAgentDom.normNick(a) === me; })
            : outs.length === 1);
      if (insAllPartner) score += 5;
      score -= insForeign * 5;
      if (outsMe) score += 1;
      if (insAllPartner && (outs.length === 0 || outsMe)) score += 2;
      if (!ins.length && !outs.length) score -= 2;
      if (ins.length && !insAllPartner && insForeign === ins.length) score -= 2;
    }
    if (ChatAgentDom.visible(group.pane)) score += 1;
    return score;
  },

  /** [pane, nodes] of the pane the user is actually looking at. */
  selectPane(nodes, groups) {
    if (groups.length <= 1) {
      return groups[0] ||
             { pane: nodes[0] ? this.paneOf(nodes[0]) : null,
               nodes: nodes, panes: 0 };
    }
    var summary = this.describeTab();
    var wantsPrivate = summary.tab === 'private' &&
                       !!ChatAgentDom.clean(summary.partner);
    var title = ChatAgentDom.normNick(summary.partner);
    var me = ChatAgentDom.normNick(summary.me);
    var best = -1, bestScore = -Infinity;
    for (var g = 0; g < groups.length; g++) {
      var group = groups[g];
      var score = this.scoreGroup(group, wantsPrivate, title, me);
      group.score = score;
      group.count = group.nodes.length;
      var bestVisible = best >= 0 && ChatAgentDom.visible(groups[best].pane);
      var thisVisible = ChatAgentDom.visible(group.pane);
      if (score > bestScore ||
          (score === bestScore && thisVisible && !bestVisible) ||
          (score === bestScore && thisVisible === bestVisible &&
           group.count > groups[best].count)) {
        best = g; bestScore = score;
      }
    }
    if (best < 0) best = 0;
    return groups[best];
  },

  paneAmong(group, pane) {
    return group && group.pane === pane;
  },

  /** No message nodes: keep the known pane (an active pane can be
     momentarily empty while it loads older history, and document order may
     put the room's .messages-root first — falling back there reports the
     wrong scroll state and count). */
  noNodesPane(nodes) {
    var known = this._lastPane && ChatAgentDom.inDocument(this._lastPane)
      ? this._lastPane : null;
    var pane = known || ChatAgentDom.qs(document, '.messages-root') ||
               ChatAgentDom.qs(document, 'app-messages');
    return { pane: pane, nodes: nodes, panes: 0,
             source: known ? 'last' : 'first' };
  },

  /** The pane we are watching is still mounted but its nodes were removed
     while it loads older lines. Another pane may still have nodes (the
     room, or a second private chat); selecting that one is exactly the
     "visible messages exist but nothing is collected" regression. */
  stalePaneStay(groups, currentPartner) {
    if (!this._lastPane || !ChatAgentDom.inDocument(this._lastPane) ||
        !this._lastPartner || currentPartner !== this._lastPartner)
      return null;
    for (var g = 0; g < groups.length; g++) {
      if (this.paneAmong(groups[g], this._lastPane)) return null;
    }
    return { pane: this._lastPane, nodes: [], panes: groups.length,
             source: 'last-empty' };
  },

  visiblePane() {
    var summary = this.describeTab();
    var currentPartner = ChatAgentDom.normNick(summary.partner);
    var nodes = ChatAgentDom.qsa(document, 'div.message-container');
    if (!nodes.length) return this.noNodesPane(nodes);
    var groups = this.paneGroups(nodes);
    var stay = this.stalePaneStay(groups, currentPartner);
    if (stay) return stay;
    var chosen = this.selectPane(nodes, groups);
    var sameAsLast = !!(chosen && chosen.pane && chosen.pane === this._lastPane);
    if (chosen && chosen.pane) {
      this._lastPane = chosen.pane;
      this._lastPartner = currentPartner;
    }
    return { pane: chosen ? chosen.pane : null,
             nodes: chosen ? chosen.nodes : nodes,
             panes: groups.length, sameAsLast: sameAsLast };
  },

  containers() {
    return this.visiblePane().nodes;
  },

  /** the element that new messages are appended to (observer target) */
  messagesRoot() {
    var found = this.visiblePane();
    var nodes = found.nodes;
    if (!nodes.length) {
      return found.pane || ChatAgentDom.qs(document, '.messages-root') ||
             ChatAgentDom.qs(document, 'app-messages');
    }
    var last = nodes[nodes.length - 1];
    for (var p = nodes[0].parentElement; p; p = p.parentElement) {
      if (ChatAgentDom.isAncestor(p, last)) return p;
    }
    return nodes[0].parentElement;
  },

  /** Active-tab facts only. `describe()` adds pane-scoped user data. */
  describeTab() {
    var active = ChatAgentDom.qs(document, '.tab-item.active');
    var tab = 'none', partner = '', title = '';
    if (active) {
      var icon = ChatAgentDom.qs(active, 'mat-icon.chat-type-icon') ||
                 ChatAgentDom.qs(active, 'mat-icon');
      var name = icon ? icon.getAttribute('data-mat-icon-name') : '';
      title = ChatAgentDom.ownText(ChatAgentDom.qs(active, 'p.chat-title'));
      /* The main room is the ONLY tab we identify positively, by its own
         icon. Every other open tab that names a person in its title IS a
         private chat (2026-09-08: partners without identifiable avatars
         were refused with "Not in private tab now"). */
      tab = name === 'room' ? 'room'
                            : (ChatAgentDom.clean(title) ? 'private' : 'none');
      partner = title;
    }
    var mine = ChatAgentDom.qs(document, '.primary-text.bold');
    return { tab: tab, partner: partner, title: title,
             me: ChatAgentDom.clean(mine ? mine.textContent : ''),
             participants: 0 };
  },

  describePane(pane) {
    var base = this.describeTab();
    var container = ChatAgentDom.containerOf(pane);
    var counter = container ? ChatAgentDom.qs(container, '.users-counter') : null;
    var mine = container ? ChatAgentDom.qs(container, '.primary-text.bold') : null;
    var globalMine = ChatAgentDom.qs(document, '.primary-text.bold');
    var count = counter ? ChatAgentDom.num(ChatAgentDom.clean(counter.textContent)) : 0;
    return {
      tab: base.tab,
      partner: base.partner,
      title: base.title,
      me: ChatAgentDom.clean(mine ? mine.textContent :
                             (globalMine ? globalMine.textContent : '')),
      participants: count > 0 ? count : ChatAgentDom.countPaneUsers(container),
    };
  },

  describe() {
    var pane = this._lastPane || this.visiblePane().pane ||
               ChatAgentDom.qs(document, '.messages-root') ||
               ChatAgentDom.qs(document, 'app-messages');
    return this.describePane(pane);
  },
};
