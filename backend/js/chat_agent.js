/* In-page collector agent.

   Injected once per document (Runtime.evaluate now, and
   Page.addScriptToEvaluateOnNewDocument for later navigations). Everything
   expensive happens HERE, in the page, where the DOM is local:

     * every message node is parsed at most once, ever (a node → record
       cache that is rebuilt — and thereby pruned — on each walk);
     * `state()` ships a summary, never the conversation;
     * `slice(a, b)` ships exactly the range Python asked for;
     * a MutationObserver buffers new lines and pushes a debounced
       notification through the `__cvbPush` binding, so Python does not have
       to poll to feel responsive.

   The fingerprint below is mirrored byte-for-byte in Python
   (backend/history_models.py) and both are pinned by tests.

   Kept ES5-ish on purpose: it has to run inside whatever the site's
   renderer is, without a build step.
*/
(function () {
  'use strict';

  var VERSION = 7;
  var HEAD_FPS = 5;         // how many leading fingerprints state() ships
  var TAIL_FPS = 25;        // …and how many trailing ones
  var AUTHOR_MAX = 12;      // distinct nicks reported per direction
  var BUFFER_MAX = 500;     // push buffer cap before we start dropping
  var PUSH_DEBOUNCE_MS = 120;
  var AUTHOR_SCAN_MAX = 1200;   // per-pane author scan cap (keeps state cheap)
  var SEP = '\u001f';

  if (window.__cvbAgent && window.__cvbAgent.version === VERSION) {
    return window.__cvbAgent.version;
  }
  if (window.__cvbAgent && window.__cvbAgent.uninstall) {
    try { window.__cvbAgent.uninstall(); } catch (e) { /* ignore */ }
  }

  // ── fingerprint (mirrored in backend/history_models.py) ────────
  function fnv1a(str, seed) {
    var h = seed >>> 0;
    for (var i = 0; i < str.length; i++) {
      h = (h ^ str.charCodeAt(i)) >>> 0;
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h >>> 0;
  }
  function hex8(n) {
    var s = (n >>> 0).toString(16);
    while (s.length < 8) s = '0' + s;
    return s;
  }
  function fingerprint(dir, from, time, kind, payload, occ) {
    var joined = [dir || '', from || '', time || '', kind || 'text',
                  payload || '', String(occ || 0)].join(SEP);
    return hex8(fnv1a(joined, 0x811c9dc5)) +
           hex8(fnv1a(joined + '\u0001', 0x01000193));
  }

  // ── tiny DOM helpers ───────────────────────────────────────────
  function qs(root, sel) {
    try { return root ? root.querySelector(sel) : null; }
    catch (e) { return null; }
  }
  function qsa(root, sel) {
    try { return root ? Array.prototype.slice.call(root.querySelectorAll(sel)) : []; }
    catch (e) { return []; }
  }
  function clean(text) { return String(text == null ? '' : text).trim(); }
  /** text of `el` without the text of its child elements (unread badges…) */
  function ownText(el) {
    if (!el) return '';
    var text = String(el.textContent || '');
    var kids = el.children || [];
    for (var i = 0; i < kids.length; i++) {
      var kid = String(kids[i].textContent || '');
      if (kid) text = text.replace(kid, '');
    }
    return clean(text);
  }
  function isAncestor(maybe, node) {
    for (var p = node; p; p = p.parentElement) if (p === maybe) return true;
    return false;
  }
  function num(value) { var n = Number(value); return isFinite(n) ? n : 0; }

  // ── the conversation ───────────────────────────────────────────
  /* The site keeps several chat panes alive at once (the main room plus one
     per open private tab). Parsing `document.querySelectorAll` blindly mixes
     them, which is how room messages used to end up in a person's archive.
     Everything below therefore works on ONE pane: the visible one. */

  function isHidden(el) {
    if (!el) return true;
    var tag = String(el.tagName || '').toLowerCase();
    if (tag === 'body' || tag === 'html') return false;
    if (el.hidden === true) return true;
    if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return true;
    if ('offsetParent' in el && el.offsetParent === null) return true;
    return false;
  }

  function visible(el) {
    for (var p = el; p; p = p.parentElement) if (isHidden(p)) return false;
    return true;
  }

  /** the conversation pane a message node belongs to (innermost match) */
  function paneOf(node) {
    for (var p = node; p; p = p.parentElement) {
      if (p.classList && p.classList.contains('messages-root')) return p;
      if (String(p.tagName || '').toLowerCase() === 'app-messages') return p;
    }
    return null;
  }

  /** [pane, nodes] of the pane the user is actually looking at.
   *
   * v6: the site keeps every open chat in the DOM, and hiding is not always a
   * `display:none` — a main-room pane can still report a measurable
   * `offsetParent` and, being much longer, would be chosen by "most nodes".
   * The active tab already tells us WHO we are talking to, so the pane is
   * selected by author evidence first: the pane whose inbound authors are
   * exactly the active partner (no strangers) beats a longer room pane. */
  function normNick(x) {
    return String(x == null ? '' : x).trim().toLowerCase();
  }

  function distinctNicks(names) {
    var out = [];
    for (var i = 0; i < names.length; i++) {
      var n = clean(names[i]);
      if (n && out.indexOf(n) < 0 && out.length < AUTHOR_MAX) out.push(n);
    }
    return out;
  }

  function paneGroups(nodes) {
    var panes = [], groups = [];
    for (var i = 0; i < nodes.length; i++) {
      var pane = paneOf(nodes[i]);
      var at = panes.indexOf(pane);
      if (at < 0) { panes.push(pane); groups.push({ pane: pane, nodes: [] }); }
      groups[panes.indexOf(pane)].nodes.push(nodes[i]);
    }
    return groups;
  }

  function groupAuthors(g) {
    var ins = [], outs = [];
    var limit = Math.min(g.nodes.length, AUTHOR_SCAN_MAX);
    for (var i = 0; i < limit; i++) {
      var node = g.nodes[i];
      var fields = cache.get(node);
      if (!fields) { fields = parseNode(node); cache.set(node, fields); }
      var name = clean(fields.from);
      if (!name) continue;
      (fields.dir === 'out' ? outs : ins).push(name);
    }
    return { inbound: distinctNicks(ins), outbound: distinctNicks(outs) };
  }

  function selectPane(nodes, groups) {
    if (groups.length <= 1) {
      return groups[0] ||
             { pane: nodes[0] ? paneOf(nodes[0]) : null, nodes: nodes, panes: 0 };
    }
    var summary = describe();
    var wantsPrivate = summary.tab === 'private' && !!clean(summary.partner);
    var title = normNick(summary.partner);
    var me = normNick(summary.me);
    var best = -1, bestScore = -Infinity;
    for (var g = 0; g < groups.length; g++) {
      var group = groups[g];
      var authors = groupAuthors(group);
      var score = 0;
      if (wantsPrivate && title) {
        var ins = authors.inbound;
        var outs = authors.outbound;
        var insAllPartner = ins.length > 0 &&
                            ins.every(function (a) { return normNick(a) === title; });
        var insForeign = ins.filter(function (a) {
          return normNick(a) !== title;
        }).length;
        var outsMe = outs.length > 0 &&
                     (me ? outs.every(function (a) { return normNick(a) === me; })
                         : outs.length === 1);
        if (insAllPartner) score += 5;
        score -= insForeign * 5;
        if (outsMe) score += 1;
        if (insAllPartner && (outs.length === 0 || outsMe)) score += 2;
        if (!ins.length && !outs.length) score -= 2;
        if (ins.length && !insAllPartner && insForeign === ins.length) score -= 2;
      }
      if (visible(group.pane)) score += 1;
      group.score = score;
      group.count = group.nodes.length;
      if (score > bestScore ||
          (score === bestScore && visible(group.pane) &&
           !visible(groups[best].pane)) ||
          (score === bestScore && visible(group.pane) ===
           visible(groups[best].pane) && group.count > groups[best].count)) {
        best = g; bestScore = score;
      }
    }
    if (best < 0) best = 0;
    return groups[best];
  }

  function visiblePane() {
    var nodes = qsa(document, 'div.message-container');
    if (!nodes.length) {
      return { pane: qs(document, '.messages-root') ||
                     qs(document, 'app-messages'), nodes: nodes, panes: 0 };
    }
    var groups = paneGroups(nodes);
    var chosen = selectPane(nodes, groups);
    return { pane: chosen.pane, nodes: chosen.nodes, panes: groups.length };
  }

  function containers() {
    return visiblePane().nodes;
  }

  /** the element that new messages are appended to (observer target) */
  function messagesRoot() {
    var found = visiblePane();
    var nodes = found.nodes;
    if (!nodes.length) {
      return found.pane || qs(document, '.messages-root') ||
             qs(document, 'app-messages');
    }
    var last = nodes[nodes.length - 1];
    for (var p = nodes[0].parentElement; p; p = p.parentElement) {
      if (isAncestor(p, last)) return p;
    }
    return nodes[0].parentElement;
  }

  var cache = new Map();     // node → parsed fields
  var stats = { parsed: 0, cached: 0, walks: 0 };

  function parseNode(node) {
    stats.parsed++;
    var dir = node.classList && node.classList.contains('my-message-background')
      ? 'out' : 'in';
    var body = qs(node, 'p.message');
    var from = '', text = '', kind = 'text', media = null;
    if (body) {
      from = clean(ownText(qs(body, 'span.from')) ||
                   (qs(body, 'span.from') || {}).textContent);
      var img = qs(body, 'app-chat-image img') || qs(body, 'img');
      if (img) {
        var url = img.getAttribute('src') || '';
        kind = /\.gif(\?|#|$)/i.test(url) ? 'gif' : 'image';
        media = { url: url, kind: kind };
      } else {
        var span = qs(body, 'span.message');
        text = clean(span ? span.textContent : '');
      }
    }
    var stamp = qs(node, 'span.sent-time') || qs(node, '.sent-time');
    return { dir: dir, from: from, kind: kind, text: text, media: media,
             time: clean(stamp ? stamp.textContent : '') };
  }

  function keyOf(fields) {
    return [fields.dir, fields.from, fields.time, fields.kind,
            fields.media ? fields.media.url : fields.text].join(SEP);
  }

  /** Parse the whole conversation, reusing the cache; returns records. */
  function walk() {
    stats.walks++;
    var nodes = containers();
    var next = new Map();
    var counts = Object.create(null);
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var fields = cache.get(node);
      if (!fields) fields = parseNode(node);
      next.set(node, fields);
      var key = keyOf(fields);
      var occ = counts[key] === undefined ? 0 : counts[key] + 1;
      counts[key] = occ;
      if (fields.fp === undefined || fields.occ !== occ) {
        fields.occ = occ;
        fields.fp = fingerprint(fields.dir, fields.from, fields.time,
                                fields.kind,
                                fields.media ? fields.media.url : fields.text,
                                occ);
      }
      out.push({ fp: fields.fp, dir: fields.dir, from: fields.from,
                 kind: fields.kind, text: fields.text, media: fields.media,
                 time: fields.time, occ: occ, idx: i, node: node });
    }
    cache = next;                       // rebuilding prunes removed nodes
    stats.cached = cache.size;
    return out;
  }

  function strip(record) {
    return { fp: record.fp, dir: record.dir, from: record.from,
             kind: record.kind, text: record.text, media: record.media,
             time: record.time, occ: record.occ, idx: record.idx };
  }

  /** distinct nicks per direction — the private-chat gate reads these */
  function authorsOf(records) {
    var ins = [], outs = [];
    for (var i = 0; i < records.length; i++) {
      var name = clean(records[i].from);
      if (!name) continue;
      var list = records[i].dir === 'out' ? outs : ins;
      if (list.indexOf(name) < 0 && list.length < AUTHOR_MAX) list.push(name);
    }
    var all = ins.slice();
    for (var o = 0; o < outs.length; o++) {
      if (all.indexOf(outs[o]) < 0) all.push(outs[o]);
    }
    return { inbound: ins, outbound: outs, all: all };
  }

  // ── the push buffer ────────────────────────────────────────────
  var buffer = [];
  var dropped = 0;
  var observer = null;
  var observedRoot = null;
  var pushTimer = null;

  function bufferRecord(record) {
    buffer.push(strip(record));
    while (buffer.length > BUFFER_MAX) { buffer.shift(); dropped++; }
  }

  function schedulePush(count, kind) {
    if (pushTimer) clearTimeout(pushTimer);
    pushTimer = setTimeout(function () {
      pushTimer = null;
      sendPush(count, kind);
    }, PUSH_DEBOUNCE_MS);
  }

  function sendPush(count, kind) {
    var hook = window.__cvbPush;
    if (typeof hook !== 'function') return;
    var summary = describe();
    var authors = authorsOf(walk());
    try {
      hook(JSON.stringify({
        kind: kind || 'append',
        agent: VERSION,
        count: count,
        partner: summary.partner,
        title: summary.title,
        me: summary.me,
        tab: summary.tab,
        in_authors: authors.inbound,
        out_authors: authors.outbound,
        authors: authors.all,
        pending: buffer.length,
        dropped: dropped,
        items: buffer.slice(-BUFFER_MAX),
      }));
    } catch (e) { /* the page must never break because we cannot push */ }
  }

  function onMutations(mutations) {
    var added = [];
    for (var i = 0; i < mutations.length; i++) {
      var nodes = mutations[i].addedNodes || [];
      for (var j = 0; j < nodes.length; j++) {
        var node = nodes[j];
        if (!node || typeof node.querySelectorAll !== 'function') continue;
        if (node.classList && node.classList.contains('message-container')) {
          added.push(node);
        } else {
          added = added.concat(qsa(node, 'div.message-container'));
        }
      }
    }
    if (!added.length) return;
    var records = walk();
    var byNode = new Map();
    for (var k = 0; k < records.length; k++) byNode.set(records[k].node, records[k]);
    var tail = true;
    for (var a = 0; a < added.length; a++) {
      var record = byNode.get(added[a]);
      if (!record) continue;
      if (record.idx < records.length - added.length) tail = false;
      bufferRecord(record);
    }
    schedulePush(records.length, tail ? 'append' : 'change');
  }

  function install() {
    var root = messagesRoot();
    if (!root || typeof MutationObserver !== 'function') return false;
    if (observer) observer.disconnect();
    observer = new MutationObserver(onMutations);
    observer.observe(root, { childList: true, subtree: true });
    observedRoot = root;
    return true;
  }

  /* Switching tabs swaps the whole pane. An observer left on the old pane
     would keep pushing the previous (or the room's) conversation, so every
     probe re-checks that we are watching the pane that is on screen. */
  function reattach() {
    var root = messagesRoot();
    if (root && root !== observedRoot) {
      buffer = [];
      install();
    }
  }

  function uninstall() {
    if (observer) { observer.disconnect(); observer = null; }
    observedRoot = null;
    if (pushTimer) { clearTimeout(pushTimer); pushTimer = null; }
  }

  // ── the public probes ──────────────────────────────────────────
  function describe() {
    var active = qs(document, '.tab-item.active');
    var tab = 'none', partner = '', title = '';
    if (active) {
      var icon = qs(active, 'mat-icon.chat-type-icon') || qs(active, 'mat-icon');
      var name = icon ? icon.getAttribute('data-mat-icon-name') : '';
      tab = name === 'user' ? 'private' : 'room';
      title = ownText(qs(active, 'p.chat-title'));
      partner = title;
    }
    var counter = qs(document, '.users-counter');
    var mine = qs(document, '.primary-text.bold');
    return {
      tab: tab,
      partner: partner,
      title: title,
      me: clean(mine ? mine.textContent : ''),
      participants: counter ? num(clean(counter.textContent)) : 0,
    };
  }

  function scrollInfo() {
    var box = chatScroller();
    var top = num(box.scrollTop), height = num(box.scrollHeight),
        client = num(box.clientHeight);
    return { top: top, height: height, client: client,
             atTop: top <= 4,
             atBottom: height === 0 || top + client >= height - 4 };
  }

  /** Every element that can actually scroll the conversation.
   *
   * `messagesRoot()` returns the CONTENT wrapper (the element the observer is
   * bound to), not necessarily the box that has `overflow-y:scroll`. We
   * therefore walk up from that wrapper and collect the real scrollers: the
   * `.messages-root` / `app-messages`, any `cdk-virtual-scrollable` viewport,
   * and any ancestor with a scrolling overflow. The first such element is the
   * one `state()` reports and `scrollToTop()` drives. */
  function scrollerCandidates() {
    var root = messagesRoot() || visiblePane().pane ||
               qs(document, '.messages-root') || qs(document, 'app-messages');
    var candidates = [], seen = [];
    for (var el = root; el; el = el.parentElement) {
      if (seen.indexOf(el) >= 0) break;
      seen.push(el);
      var tag = String(el.tagName || '').toLowerCase();
      var cls = '';
      if (el.classList && el.classList.contains) {
        var klass = String(el.className || '');
        cls = klass;
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
      var isOverflow = overflow === 'scroll' || overflow === 'auto';
      if (isMessagesRoot || isVirtual || isOverflow) candidates.push(el);
    }
    if (!candidates.length) candidates.push(root || {});
    return candidates;
  }

  function chatScroller() {
    return scrollerCandidates()[0];
  }

  function scrollMetrics(box) {
    return { top: num(box.scrollTop), height: num(box.scrollHeight),
             client: num(box.clientHeight) };
  }

  function dispatchScroll(box) {
    if (box && typeof box.dispatchEvent === 'function' &&
        typeof window.Event === 'function') {
      try { box.dispatchEvent(new Event('scroll', { bubbles: true })); }
      catch (e) { /* a stub with no Event must never break the collector */ }
    }
  }

  var lastBeforeTops = [];

  /** Scroll the chat to the very first message. Returns the old position. */
  function scrollToTop() {
    reattach();
    lastBeforeTops = [];
    var boxes = scrollerCandidates();
    var primary = boxes[0];
    var beforeTop = num(primary.scrollTop);
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i];
      lastBeforeTops.push(num(box.scrollTop));
      if (typeof box.scrollTo === 'function') {
        try {
          box.scrollTo({ top: 0, behavior: 'auto' });
        } catch (e) {
          try { box.scrollTo(0, 0); } catch (e2) { /* ignore */ }
        }
      }
      box.scrollTop = 0;
      dispatchScroll(box);
    }
    var top = num(primary.scrollTop);
    return { ok: true, beforeTop: beforeTop, top: top,
             atTop: top <= 4, height: num(primary.scrollHeight),
             count: containers().length, boxes: boxes.length };
  }

  /** Put the conversation back where the user had it. */
  function restoreScroll(top) {
    reattach();
    var boxes = scrollerCandidates();
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i];
      var target = i < lastBeforeTops.length ? lastBeforeTops[i] : num(top);
      box.scrollTop = target;
      dispatchScroll(box);
    }
    var primary = boxes[0] || {};
    return { ok: true, top: num(primary.scrollTop) };
  }

  function state() {
    reattach();
    var anchor = qs(document, 'app-messages') || qs(document, '.messages-root') ||
                 qs(document, '.tab-item.active');
    if (!anchor && !containers().length) {
      return { ok: false, reason: 'no chat on this page', agent: VERSION,
               tab: 'none', partner: '', title: '', me: '', participants: 0,
               count: 0, head: [], tail: [], authors: [], in_authors: [],
               out_authors: [], panes: 0, pending: buffer.length,
               scroll: { top: 0, height: 0, client: 0 } };
    }
    var records = walk();
    var fps = records.map(function (r) { return r.fp; });
    var summary = describe();
    var authors = authorsOf(records);
    return {
      ok: true,
      agent: VERSION,
      tab: summary.tab,
      partner: summary.partner,
      title: summary.title,
      me: summary.me,
      participants: summary.participants,
      count: records.length,
      authors: authors.all,
      in_authors: authors.inbound,
      out_authors: authors.outbound,
      panes: visiblePane().panes,
      head: fps.slice(0, HEAD_FPS),
      tail: fps.slice(Math.max(0, fps.length - TAIL_FPS)),
      pending: buffer.length,
      dropped: dropped,
      scroll: scrollInfo(),
    };
  }

  function slice(from, to) {
    reattach();
    var records = walk();
    var a = Math.max(0, Math.min(records.length, num(from)));
    var b = Math.max(a, Math.min(records.length, num(to)));
    return { ok: true, from: a, to: b, count: records.length,
             items: records.slice(a, b).map(strip) };
  }

  function drain() {
    var items = buffer;
    var lost = dropped;
    buffer = [];
    dropped = 0;
    return { ok: true, items: items, dropped: lost };
  }

  var agent = {
    version: VERSION,
    state: state,
    slice: slice,
    drain: drain,
    fingerprint: fingerprint,
    scrollToTop: scrollToTop,
    restoreScroll: restoreScroll,
    stats: function () { return { parsed: stats.parsed, cached: stats.cached,
                                  walks: stats.walks, pending: buffer.length,
                                  dropped: dropped }; },
    install: install,
    uninstall: uninstall,
  };

  window.__cvbAgent = agent;
  install();
  return VERSION;
})();
