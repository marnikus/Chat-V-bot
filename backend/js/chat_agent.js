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

  var VERSION = 3;
  var HEAD_FPS = 5;         // how many leading fingerprints state() ships
  var TAIL_FPS = 25;        // …and how many trailing ones
  var BUFFER_MAX = 500;     // push buffer cap before we start dropping
  var PUSH_DEBOUNCE_MS = 120;
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
  function containers() {
    return qsa(document, 'div.message-container');
  }

  /** the element that new messages are appended to (observer target) */
  function messagesRoot() {
    var nodes = containers();
    if (!nodes.length) {
      return qs(document, '.messages-root') || qs(document, 'app-messages');
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

  // ── the push buffer ────────────────────────────────────────────
  var buffer = [];
  var dropped = 0;
  var observer = null;
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
    try {
      hook(JSON.stringify({
        kind: kind || 'append',
        agent: VERSION,
        count: count,
        partner: summary.partner,
        me: summary.me,
        tab: summary.tab,
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
    return true;
  }

  function uninstall() {
    if (observer) { observer.disconnect(); observer = null; }
    if (pushTimer) { clearTimeout(pushTimer); pushTimer = null; }
  }

  // ── the public probes ──────────────────────────────────────────
  function describe() {
    var active = qs(document, '.tab-item.active');
    var tab = 'none', partner = '';
    if (active) {
      var icon = qs(active, 'mat-icon.chat-type-icon') || qs(active, 'mat-icon');
      var name = icon ? icon.getAttribute('data-mat-icon-name') : '';
      tab = name === 'user' ? 'private' : 'room';
      partner = ownText(qs(active, 'p.chat-title'));
    }
    var counter = qs(document, '.users-counter');
    var mine = qs(document, '.primary-text.bold');
    return {
      tab: tab,
      partner: partner,
      me: clean(mine ? mine.textContent : ''),
      participants: counter ? num(clean(counter.textContent)) : 0,
    };
  }

  function scrollInfo() {
    var root = messagesRoot();
    for (var el = root; el; el = el.parentElement) {
      if (num(el.scrollHeight) > num(el.clientHeight) + 4) break;
    }
    var box = el || root || {};
    var top = num(box.scrollTop), height = num(box.scrollHeight),
        client = num(box.clientHeight);
    return { top: top, height: height, client: client,
             atTop: top <= 4,
             atBottom: height === 0 || top + client >= height - 4 };
  }

  function state() {
    var anchor = qs(document, 'app-messages') || qs(document, '.messages-root') ||
                 qs(document, '.tab-item.active');
    if (!anchor && !containers().length) {
      return { ok: false, reason: 'no chat on this page', agent: VERSION,
               tab: 'none', partner: '', me: '', participants: 0, count: 0,
               head: [], tail: [], pending: buffer.length,
               scroll: { top: 0, height: 0, client: 0 } };
    }
    var records = walk();
    var fps = records.map(function (r) { return r.fp; });
    var summary = describe();
    return {
      ok: true,
      agent: VERSION,
      tab: summary.tab,
      partner: summary.partner,
      me: summary.me,
      participants: summary.participants,
      count: records.length,
      head: fps.slice(0, HEAD_FPS),
      tail: fps.slice(Math.max(0, fps.length - TAIL_FPS)),
      pending: buffer.length,
      dropped: dropped,
      scroll: scrollInfo(),
    };
  }

  function slice(from, to) {
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
