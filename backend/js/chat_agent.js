/* In-page collector agent.

   Injected once per document (Runtime.evaluate now, and
   Page.addScriptToEvaluateOnNewDocument for later navigations). Everything
   expensive happens HERE, in the page, where the DOM is local:

     * complete, unchanged message nodes reuse a cache; incomplete/changed
       payloads and explicit range refreshes are re-extracted;
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

  var VERSION = 13;
  var HEAD_FPS = 5;         // how many leading fingerprints state() ships
  var TAIL_FPS = 25;        // …and how many trailing ones
  var AUTHOR_MAX = 12;      // distinct nicks reported per direction
  var BUFFER_MAX = 500;     // push buffer cap before we start dropping
  var PUSH_DEBOUNCE_MS = 120;
  var AUTHOR_SCAN_MAX = 1200;   // per-pane author scan cap (keeps state cheap)
  var SEP = '\u001f';
  var INSTANCE = String(Date.now()) + '-' + String(Math.random()).slice(2);
  var epoch = 0;
  var cachePartner = '';
  function captureEpoch() { return INSTANCE + ':' + String(epoch); }

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
    var nodes = el.childNodes;
    if (nodes) {
      var direct = '';
      for (var i = 0; i < nodes.length; i++) {
        if (nodes[i].nodeType === 3 || nodes[i].nodeType === 4)
          direct += nodes[i].nodeValue || '';
      }
      return clean(direct);
    }
    // Minimal DOM adapters expose own text followed by their child text.
    // Substring replacement corrupts nicknames containing a badge's digits
    // (Svetik25 + unread 2 must never become Svetik5 + unread 2).
    var text = String(el.textContent || '');
    var kids = el.children || [];
    var childText = '';
    for (var j = 0; j < kids.length; j++) childText += String(kids[j].textContent || '');
    if (childText && text.slice(-childText.length) === childText)
      text = text.slice(0, -childText.length);
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
    var summary = describeTab();
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

  var lastPane = null;
  var lastPartner = '';

  function inDocument(el) {
    for (var p = el; p; p = p.parentElement) {
      if (p === document || p === document.body) return true;
    }
    return false;
  }

  function paneAmong(group, pane) {
    return group && group.pane === pane;
  }

  function visiblePane() {
    var summary = describeTab();
    var currentPartner = normNick(summary.partner);
    var nodes = qsa(document, 'div.message-container');
    if (!nodes.length) {
      /* No message nodes right now. The active pane can be momentarily
         empty while it is loading older history, and document order may put
         the room's .messages-root first. Falling back to the first pane in
         the document then reports the wrong scroll state and count, so the
         collector sees "empty" on a non-empty conversation. If we already
         know which pane the user is watching, keep using that pane. */
      var known = lastPane && inDocument(lastPane) ? lastPane : null;
      var pane = known || qs(document, '.messages-root') ||
                 qs(document, 'app-messages');
      return { pane: pane, nodes: nodes, panes: 0,
               source: known ? 'last' : 'first' };
    }
    var groups = paneGroups(nodes);
    /* The pane we are watching is still mounted but its nodes were removed
       while it loads older lines. Another pane may still have nodes (the
       room, or a second private chat); selecting that one is exactly the
       "visible messages exist but nothing is collected" regression. Stay on
       the known pane and report empty instead. */
    if (lastPane && inDocument(lastPane) && lastPartner &&
        currentPartner === lastPartner) {
      var hasOwnNode = false;
      for (var g = 0; g < groups.length; g++) {
        if (paneAmong(groups[g], lastPane)) { hasOwnNode = true; break; }
      }
      if (!hasOwnNode) {
        return { pane: lastPane, nodes: [], panes: groups.length,
                 source: 'last-empty' };
      }
    }
    var chosen = selectPane(nodes, groups);
    if (chosen && chosen.pane) {
      lastPane = chosen.pane;
      lastPartner = currentPartner;
    }
    return { pane: chosen ? chosen.pane : null,
             nodes: chosen ? chosen.nodes : nodes,
             panes: groups.length,
             source: groups.length === 1 ? 'single-pane' : 'author-match' };
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
  var contentRevision = 0; // changes INSIDE existing lines, not tail appends

  /** The media URL the browser is actually rendering right now.
   *
   * Lazy-loaded images start with an empty `src` and put the real address in
   * `data-src` (or set `currentSrc` only after the browser has fetched). The
   * first parse must not burn an empty URL into the archive. */
  function liveMediaUrl(img) {
    if (!img) return '';
    return clean(img.currentSrc || img.getAttribute('src') ||
                 img.getAttribute('data-src') || '');
  }

  function hasClass(node, name) {
    return !!(node && node.classList && node.classList.contains(name));
  }

  function metadata(node) {
    if (!node || !node.tagName) return false;
    var tag = String(node.tagName).toLowerCase();
    if (['svg', 'mat-icon', 'mat-menu', 'script', 'style', 'template',
         'button', 'input', 'select', 'textarea', 'avatar-item'].indexOf(tag) >= 0) return true;
    var names = ['from', 'sent-time', 'message-status', 'state-icon',
                 'additional-icon', 'avatar', 'avatar-wrapper', 'source-indicator',
                 'message-actions', 'message-menu'];
    for (var i = 0; i < names.length; i++) if (hasClass(node, names[i])) return true;
    return !!(node.hidden || (node.style && (node.style.display === 'none' ||
                                           node.style.visibility === 'hidden')));
  }

  function insideMetadata(node, scope) {
    for (var p = node; p && p !== scope; p = p.parentElement) {
      if (metadata(p)) return true;
    }
    return false;
  }

  /** Payload text only. Never fall back to a container's unfiltered textContent. */
  function messageText(root, structural) {
    if (!root) return '';
    var started = false, separator = false;
    function bodyText(text) {
      text = String(text || '');
      if (structural && !started && !separator) {
        var trimmed = clean(text);
        if (['▸', '►', '▶', '>'].indexOf(trimmed) >= 0) {
          separator = true;
          return '';
        }
        // Some layouts put the separator and body in one text node.
        if (/^\s*[▸►▶]\s*/.test(text)) {
          text = text.replace(/^\s*[▸►▶]\s*/, '');
          separator = true;
        }
      }
      if (clean(text)) started = true;
      return text;
    }
    function visit(node) {
      if (node.nodeType === 3 || node.nodeType === 4) return bodyText(node.nodeValue);
      if (node.nodeType === 8 || metadata(node)) return '';
      var tag = String(node.tagName || '').toLowerCase();
      if (tag === 'app-chat-image' || hasClass(node, 'image-wrapper')) return '';
      if (tag === 'br') return '\n';
      if (tag === 'img') {
        // Emoji belongs to text; attachment alt labels do not.
        return (!structural || hasClass(node, 'emoji') || hasClass(node, 'emoticon'))
          ? bodyText(node.getAttribute && node.getAttribute('alt')) : '';
      }
      var kids = node.childNodes;
      var text = '';
      if (kids) {
        for (var i = 0; i < kids.length; i++) text += visit(kids[i]);
      } else {
        // Small DOM adapters without text-node objects still preserve their
        // own text and element children; the browser uses childNodes above.
        text = bodyText(ownText(node));
        kids = node.children || [];
        for (var j = 0; j < kids.length; j++) text += visit(kids[j]);
      }
      return text + (tag === 'div' || tag === 'p' ? '\n' : '');
    }
    return clean(visit(root));
  }

  function payloadParts(node) {
    var scope = qs(node, '.message-content') || node;
    var span = qs(scope, 'span.message') || qs(scope, '.message-text') ||
               qs(scope, '[data-message-text]');
    var img = null;
    var images = qsa(scope, 'img');
    for (var i = 0; i < images.length; i++) {
      var candidate = images[i];
      if (insideMetadata(candidate, scope) ||
          (span && isAncestor(span, candidate)) ||
          hasClass(candidate, 'emoji') || hasClass(candidate, 'emoticon')) continue;
      img = candidate;
      break;
    }
    return { scope: scope, text: span, image: img,
             hasBody: !!(span || qs(scope, 'p.message') || qs(node, '.message-content')) };
  }

  function parseNode(node) {
    stats.parsed++;
    var dir = hasClass(node, 'my-message-background') ? 'out' : 'in';
    var parts = payloadParts(node);
    var author = qs(parts.scope, 'span.from') || qs(parts.scope, '.from');
    var from = clean(ownText(author) || (author || {}).textContent);
    var text = parts.text ? messageText(parts.text, false) : '';
    var source = text ? 'payload-element' : 'message-content';
    if (!text) text = messageText(parts.scope, true);
    var media = null, kind = 'text';
    if (parts.image) {
      var url = liveMediaUrl(parts.image);
      kind = /\.gif(\?|#|$)/i.test(url) ? 'gif' : 'image';
      media = { url: url, kind: kind };
    }
    var pending = !from || (!text && !(media && media.url)) || !!(media && !media.url);
    var reason = !pending ? '' : !from ? 'author_pending' : media ? 'media_url_pending' :
                 !parts.hasBody ? 'body_missing' : 'payload_empty';
    var stamp = qs(node, 'span.sent-time') || qs(node, '.sent-time');
    return { dir: dir, from: from, kind: kind, text: text, media: media,
             capture_pending: pending, capture_reason: reason, text_source: source,
             time: clean(stamp ? stamp.textContent : '') };
  }

  function keyOf(fields) {
    return [fields.dir, fields.from, fields.time, fields.kind,
            fields.media ? fields.media.url : fields.text].join(SEP);
  }

  /** Parse the whole conversation, reusing the cache; returns records. */
  function walk() {
    var partner = normNick(describeTab().partner);
    if (partner !== cachePartner) {
      cache = new Map();
      buffer = [];
      dropped = 0;
      if (pushTimer) { clearTimeout(pushTimer); pushTimer = null; }
      cachePartner = partner;
      epoch++;
    }
    stats.walks++;
    var nodes = containers();
    var next = new Map();
    var counts = Object.create(null);
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var fields = cache.get(node);
      var previous = fields;
      if (fields && (fields.dirty || fields.capture_pending)) fields = null;
      if (fields) {
        // a lazy <img> may have gained its real src after the first parse;
        // do not keep the empty-url record in the cache forever
        var img = payloadParts(node).image;
        var liveUrl = liveMediaUrl(img);
        var cachedUrl = fields.media ? fields.media.url : '';
        if (liveUrl !== cachedUrl) fields = null;
      }
      if (!fields) fields = parseNode(node);
      if (previous && (keyOf(previous) !== keyOf(fields) || previous.text !== fields.text))
        contentRevision++;
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
                 time: fields.time, occ: occ, idx: i, node: node,
                 capture_pending: fields.capture_pending,
                 capture_reason: fields.capture_reason, text_source: fields.text_source });
    }
    cache = next;                       // rebuilding prunes removed nodes
    stats.cached = cache.size;
    return out;
  }

  function strip(record) {
    return { fp: record.fp, dir: record.dir, from: record.from,
             kind: record.kind, text: record.text, media: record.media,
             time: record.time, occ: record.occ, idx: record.idx,
             capture_pending: !!record.capture_pending,
             capture_reason: record.capture_reason || '', text_source: record.text_source || '',
             capture_epoch: captureEpoch() };
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
    for (var i = 0; i < buffer.length; i++) {
      if (buffer[i].node === record.node) {
        buffer[i].record = strip(record);
        return;
      }
    }
    buffer.push({ node: record.node, record: strip(record) });
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
    var records = walk();
    var summary = describe();
    if (!buffer.length) return;
    var authors = authorsOf(records);
    // A pending payload can finish rendering during the debounce window.
    records.forEach(function (record) {
      for (var b = 0; b < buffer.length; b++) {
        if (buffer[b].node === record.node) buffer[b].record = strip(record);
      }
    });
    try {
      hook(JSON.stringify({
        kind: kind || 'append',
        agent: VERSION,
        capture_epoch: captureEpoch(),
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
        items: buffer.slice(-BUFFER_MAX).map(function (b) { return b.record; }),
      }));
    } catch (e) { /* the page must never break because we cannot push */ }
  }

  function messageOf(node) {
    for (var p = node; p; p = p.parentElement || p.parentNode) {
      if (p.classList && p.classList.contains('message-container')) return p;
    }
    return null;
  }

  function onMutations(mutations) {
    var affected = new Set();
    var changed = false;
    for (var i = 0; i < mutations.length; i++) {
      var mutation = mutations[i];
      var owner = messageOf(mutation.target);
      if (owner) {
        affected.add(owner);
        var cached = cache.get(owner);
        if (cached) cached.dirty = true;
        changed = true;
      }
      var nodes = mutation.addedNodes || [];
      for (var j = 0; j < nodes.length; j++) {
        var node = nodes[j];
        if (!node || typeof node.querySelectorAll !== 'function') continue;
        if (node.classList && node.classList.contains('message-container')) {
          affected.add(node);
        } else {
          qsa(node, 'div.message-container').forEach(function (n) { affected.add(n); });
        }
      }
      if ((mutation.removedNodes || []).length) {
        // Replacing a whole virtualized window can change its middle while
        // head/tail stay equal. Force a re-read, not an append-only shortcut.
        contentRevision++;
        changed = true;
      }
    }
    if (!affected.size && !changed) return;
    var records = walk();
    var tail = !changed;
    for (var k = 0; k < records.length; k++) {
      var record = records[k];
      if (!affected.has(record.node)) continue;
      if (record.idx < records.length - affected.size) tail = false;
      bufferRecord(record);
    }
    schedulePush(records.length, tail ? 'append' : 'change');
  }

  function install() {
    var root = messagesRoot();
    if (!root || typeof MutationObserver !== 'function') return false;
    if (observer) observer.disconnect();
    observer = new MutationObserver(onMutations);
    observer.observe(root, { childList: true, subtree: true, characterData: true,
                             attributes: true, attributeFilter: ['src', 'data-src', 'class'] });
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
  function classContains(cls, token) {
    if (!cls) return false;
    return cls.indexOf(token) >= 0;
  }

  function containerOf(el) {
    for (var p = el; p; p = p.parentElement) {
      var cls = String(p.className || '');
      if (classContains(cls, 'container') || classContains(cls, 'pane-host'))
        return p;
    }
    return null;
  }

  /** Active-tab facts only. `describe()` adds pane-scoped user data. */
  function describeTab() {
    var active = qs(document, '.tab-item.active');
    var tab = 'none', partner = '', title = '';
    if (active) {
      var icon = qs(active, 'mat-icon.chat-type-icon') || qs(active, 'mat-icon');
      var name = icon ? icon.getAttribute('data-mat-icon-name') : '';
      tab = name === 'user' ? 'private' : 'room';
      title = ownText(qs(active, 'p.chat-title'));
      partner = title;
    }
    var mine = qs(document, '.primary-text.bold');
    return { tab: tab, partner: partner, title: title,
             me: clean(mine ? mine.textContent : ''), participants: 0 };
  }

  function describePane(pane) {
    var base = describeTab();
    var container = containerOf(pane);
    var counter = container ? qs(container, '.users-counter') : null;
    var lists = container ? qsa(container, 'users-list') : [];
    var rosterRoot = lists.length === 1 ? lists[0] : null;
    var names = [], own = [];
    qsa(rosterRoot, 'user-item .primary-text').forEach(function (node) {
      var name = clean(ownText(node) || node.textContent);
      if (!name) return;
      names.push(name);
      if (hasClass(node, 'bold')) own.push(name);
    });
    names = distinctNicks(names);
    own = distinctNicks(own);
    var scoped = own.length === 1 && names.indexOf(own[0]) >= 0;
    var fallback = container ? qs(container, '.primary-text.bold') : null;
    fallback = fallback || qs(document, '.primary-text.bold');
    return {
      tab: base.tab, partner: base.partner, title: base.title,
      me: scoped ? own[0] : clean(fallback ? fallback.textContent : ''),
      me_source: scoped ? 'pane_roster' : 'global_fallback',
      participant_nicks: names,
      participants: counter ? num(clean(counter.textContent)) : 0,
    };
  }

  function describe() {
    var pane = lastPane || visiblePane().pane ||
               qs(document, '.messages-root') || qs(document, 'app-messages');
    return describePane(pane);
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
    var issues = {}, sources = {};
    records.forEach(function (r) {
      if (r.capture_reason) issues[r.capture_reason] = (issues[r.capture_reason] || 0) + 1;
      sources[r.text_source] = (sources[r.text_source] || 0) + 1;
    });
    var pv = visiblePane();
    return {
      ok: true,
      agent: VERSION,
      capture_epoch: captureEpoch(),
      tab: summary.tab,
      partner: summary.partner,
      title: summary.title,
      me: summary.me,
      me_source: summary.me_source,
      participant_nicks: summary.participant_nicks,
      participants: summary.participants,
      count: records.length,
      incomplete: records.filter(function (r) { return r.capture_pending; }).length,
      capture_issues: issues,
      text_sources: sources,
      content_revision: contentRevision,
      content_sig: hex8(fnv1a(fps.join(SEP), 0x811c9dc5)),
      authors: authors.all,
      in_authors: authors.inbound,
      out_authors: authors.outbound,
      panes: pv.panes,
      pane_source: pv.source || '',
      head: fps.slice(0, HEAD_FPS),
      tail: fps.slice(Math.max(0, fps.length - TAIL_FPS)),
      pending: buffer.length,
      dropped: dropped,
      scroll: scrollInfo(),
    };
  }

  function slice(from, to, refresh) {
    reattach();
    if (refresh) {
      var nodes = containers();
      for (var i = Math.max(0, num(from)); i < Math.min(nodes.length, num(to)); i++) {
        var fields = cache.get(nodes[i]);
        if (fields) fields.dirty = true;
      }
    }
    var records = walk();
    var a = Math.max(0, Math.min(records.length, num(from)));
    var b = Math.max(a, Math.min(records.length, num(to)));
    return { ok: true, from: a, to: b, count: records.length,
             agent: VERSION, capture_epoch: captureEpoch(), items: records.slice(a, b).map(strip) };
  }

  function drain() {
    var items = buffer.map(function (b) { return b.record; });
    var lost = dropped;
    buffer = [];
    dropped = 0;
    return { ok: true, items: items, dropped: lost };
  }

  function reset(nick) {
    var target = normNick(nick);
    var active = normNick(describeTab().partner);
    // Parsed-node caching is only an optimization. Evicting it cannot lose
    // another person's buffered messages or change their database cursor.
    cache = new Map();
    stats.cached = 0;
    if (!target || target === active || target === cachePartner) {
      buffer = [];
      dropped = 0;
      if (pushTimer) { clearTimeout(pushTimer); pushTimer = null; }
      contentRevision = 0;
      stats.parsed = 0;
      stats.walks = 0;
      lastBeforeTops = [];
      lastPane = null;
      lastPartner = '';
      cachePartner = active;
      epoch++;
      return { ok: true, reset: true, capture_epoch: captureEpoch() };
    }
    return { ok: true, reset: false, capture_epoch: captureEpoch() };
  }

  var agent = {
    version: VERSION,
    state: state,
    reset: reset,
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
