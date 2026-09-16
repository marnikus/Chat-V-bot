/* chat_agent-parse.js — node → record parsing, the parse cache, and the
   conversation walk (Round II Area A).

   Split out of backend/js/chat_agent.js; the install facade lists its
   parts. Owns the two parse-policy caps (AUTHOR_MAX, AUTHOR_SCAN_MAX —
   single ownership per constant) and the module state that the walk
   maintains (`_cache`: node → parsed fields, rebuilt — and thereby pruned —
   each walk; `_stats`: parsed/cached/walks counters).

   Cross-part calls resolve at CALL time (objects, not bare functions):
   ChatAgentDom for DOM reads, ChatAgentFp for fingerprints, and
   ChatAgentPane.containers() for "the nodes of the visible pane".
*/
'use strict';

const ChatAgentParse = {
  AUTHOR_MAX: 12,          // distinct nicks reported per direction
  AUTHOR_SCAN_MAX: 1200,   // per-pane author scan cap (keeps state cheap)

  _cache: new Map(),       // node → parsed fields
  _stats: { parsed: 0, cached: 0, walks: 0 },

  statsSnapshot() {
    return { parsed: this._stats.parsed, cached: this._stats.cached,
             walks: this._stats.walks };
  },

  /** The media URL the browser is actually rendering right now.
   *
   * Lazy-loaded images start with an empty `src` and put the real address
   * in `data-src` (or set `currentSrc` only after the browser has
   * fetched). The first parse must not burn an empty URL into the
   * archive. */
  liveMediaUrl(img) {
    if (!img) return '';
    return ChatAgentDom.clean(img.currentSrc || img.getAttribute('src') ||
                              img.getAttribute('data-src') || '');
  },

  /** { url, kind } of the image inside one message body, or null. */
  mediaOf(body) {
    var img = ChatAgentDom.qs(body, 'app-chat-image img') ||
              ChatAgentDom.qs(body, 'img');
    if (!img) return null;
    var url = this.liveMediaUrl(img);
    return { url: url, kind: /\.gif(\?|#|$)/i.test(url) ? 'gif' : 'image' };
  },

  /** First parse of one message node. Cache callers must re-validate via
     liveFields() — Angular renders in passes (see fieldsStale). */
  parseNode(node) {
    this._stats.parsed++;
    var dir = node.classList && node.classList.contains('my-message-background')
      ? 'out' : 'in';
    var body = ChatAgentDom.qs(node, 'p.message');
    var from = '', text = '', kind = 'text', media = null;
    if (body) {
      var fromEl = ChatAgentDom.qs(body, 'span.from');
      from = ChatAgentDom.clean(ChatAgentDom.ownText(fromEl) ||
                                (fromEl || {}).textContent);
      media = this.mediaOf(body);
      if (media) kind = media.kind;
      else {
        var span = ChatAgentDom.qs(body, 'span.message');
        text = ChatAgentDom.clean(span ? span.textContent : '');
      }
    }
    var stamp = ChatAgentDom.qs(node, 'span.sent-time') ||
                ChatAgentDom.qs(node, '.sent-time');
    return { dir: dir, from: from, kind: kind, text: text, media: media,
             time: ChatAgentDom.clean(stamp ? stamp.textContent : '') };
  },

  /** The parse-relevant fields of a node, re-read cheaply.
   *
   * Caching the first parse would burn `text:''` into the archive forever
   * — the exact "only nicks, no message text" bug — so every walk compares
   * these fields against the cache and re-parses on ANY change (text,
   * nick, time, media url). */
  liveFields(node) {
    var body = ChatAgentDom.qs(node, 'p.message');
    var img = body ? (ChatAgentDom.qs(body, 'app-chat-image img') ||
                      ChatAgentDom.qs(body, 'img'))
                   : null;
    var span = body ? ChatAgentDom.qs(body, 'span.message') : null;
    var stamp = ChatAgentDom.qs(node, 'span.sent-time') ||
                ChatAgentDom.qs(node, '.sent-time');
    var fromEl = body ? ChatAgentDom.qs(body, 'span.from') : null;
    return {
      from: body ? ChatAgentDom.clean(ChatAgentDom.ownText(fromEl) ||
                                      (fromEl || {}).textContent) : '',
      text: span ? ChatAgentDom.clean(span.textContent) : '',
      hasMedia: !!img,
      mediaUrl: img ? this.liveMediaUrl(img) : '',
      time: ChatAgentDom.clean(stamp ? stamp.textContent : '')
    };
  },

  fieldsStale(fields, live) {
    if (!fields) return true;
    if (fields.from !== live.from || fields.time !== live.time) return true;
    if (live.hasMedia) {
      return !fields.media || fields.media.url !== live.mediaUrl;
    }
    return !!fields.media || fields.text !== live.text;
  },

  keyOf(fields) {
    return [fields.dir, fields.from, fields.time, fields.kind,
            fields.media ? fields.media.url : fields.text]
      .join(ChatAgentFp.SEP);
  },

  /** Assign occurrence index + fingerprints to `fields` (mutates fields,
     returns the record pushed into `out`). `fpAny` is the same fingerprint
     WITHOUT the author: a partner renaming themselves re-renders every
     line under the new nick — fpAny still matches the conversation the
     cursor ended with, so the rename continues the same person. */
  recordFor(fields, node, i, counts, out) {
    var key = this.keyOf(fields);
    var occ = counts[key] === undefined ? 0 : counts[key] + 1;
    counts[key] = occ;
    if (fields.fp === undefined || fields.fpAny === undefined ||
        fields.occ !== occ) {
      fields.occ = occ;
      var payload = fields.media ? fields.media.url : fields.text;
      fields.fp = ChatAgentFp.fingerprint(fields.dir, fields.from,
                                          fields.time, fields.kind,
                                          payload, occ);
      fields.fpAny = ChatAgentFp.fingerprint(fields.dir, '', fields.time,
                                             fields.kind, payload, occ);
    }
    var record = { fp: fields.fp, fpAny: fields.fpAny, dir: fields.dir,
                   from: fields.from, kind: fields.kind, text: fields.text,
                   media: fields.media, time: fields.time, occ: occ,
                   idx: i, node: node };
    out.push(record);
    return record;
  },

  /** Parse the whole conversation, reusing the cache; returns records. */
  walk() {
    this._stats.walks++;
    var nodes = ChatAgentPane.containers();
    var next = new Map();
    var counts = Object.create(null);
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var fields = this._cache.get(node);
      if (fields && this.fieldsStale(fields, this.liveFields(node))) {
        // the node changed after its first parse (lazy media, or a late
        // text span) — never keep the stale payload-less fields
        fields = null;
      }
      if (!fields) fields = this.parseNode(node);
      next.set(node, fields);
      this.recordFor(fields, node, i, counts, out);
    }
    this._cache = next;                 // rebuilding prunes removed nodes
    this._stats.cached = this._cache.size;
    return out;
  },

  strip(record) {
    return { fp: record.fp, dir: record.dir, from: record.from,
             kind: record.kind, text: record.text, media: record.media,
             time: record.time, occ: record.occ, idx: record.idx };
  },

  /** distinct nicks per direction — the private-chat gate reads these */
  authorsOf(records) {
    var ins = [], outs = [];
    for (var i = 0; i < records.length; i++) {
      var name = ChatAgentDom.clean(records[i].from);
      if (!name) continue;
      var list = records[i].dir === 'out' ? outs : ins;
      if (list.indexOf(name) < 0 && list.length < this.AUTHOR_MAX)
        list.push(name);
    }
    var all = ins.slice();
    for (var o = 0; o < outs.length; o++) {
      if (all.indexOf(outs[o]) < 0) all.push(outs[o]);
    }
    return { inbound: ins, outbound: outs, all: all };
  },

  /** Parse-backed nick evidence of one pane group (pane selection scores
     on it). Lives with the cache because it IS the cache reading. */
  groupAuthors(g) {
    var ins = [], outs = [];
    var limit = Math.min(g.nodes.length, this.AUTHOR_SCAN_MAX);
    for (var i = 0; i < limit; i++) {
      var node = g.nodes[i];
      var fields = this._cache.get(node);
      if (!fields) { fields = this.parseNode(node); this._cache.set(node, fields); }
      var name = ChatAgentDom.clean(fields.from);
      if (!name) continue;
      (fields.dir === 'out' ? outs : ins).push(name);
    }
    return { inbound: ChatAgentDom.distinctNicks(ins, this.AUTHOR_MAX),
             outbound: ChatAgentDom.distinctNicks(outs, this.AUTHOR_MAX) };
  },
};
