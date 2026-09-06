/* ═══════════════════════════════════════════════════════════════
   history-model.js — the pure half of the message-archive UI

   Owns the *loaded window* of a conversation: which rows are on screen,
   when to ask Python for more (lazy loading with a configurable preload
   margin), how live rows from the passive collector are merged, and how
   much stays in memory.

   DOM-free on purpose — tests/test_history_lazy_paging.js runs this exact
   file in Node (AGENT_RULES RULE 6/8).

   A conversation row as it arrives from the bridge:

       { ord, fp, dir:'in'|'out', from, kind:'text'|'image'|'gif',
         text, media:{ id, url, kind, state } | null, time:'HH:MM',
         day:'YYYY-MM-DD' }

   `ord` is the archive's per-person position and is the only anchor used
   for paging; `fp` is the dedup fingerprint.
   ═══════════════════════════════════════════════════════════════ */

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.HistoryModel = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const DEFAULTS = { pageSize: 50, preloadRows: 40, maxRows: 400 };

  // ── static helpers (also used directly by the views) ─────────

  /** 'YYYY-MM-DD' → the day before, without touching the clock. */
  function previousDay(day) {
    const parts = String(day || '').split('-').map(Number);
    if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return '';
    const d = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  }

  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November',
                  'December'];

  /** Human label for a day separator ("Today", "Yesterday", "5 September 2026"). */
  function dayLabel(day, today) {
    if (!day) return 'Unknown date';
    if (today && day === today) return 'Today';
    if (today && day === previousDay(today)) return 'Yesterday';
    const parts = String(day).split('-').map(Number);
    if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return day;
    return parts[2] + ' ' + (MONTHS[parts[1] - 1] || '') + ' ' + parts[0];
  }

  /** Group consecutive rows that share a day: [{ day, label, items }]. */
  function groupByDay(items, opts) {
    const today = (opts && opts.today) ||
      new Date().toISOString().slice(0, 10);
    const out = [];
    (items || []).forEach((item) => {
      const day = item.day || '';
      const last = out[out.length - 1];
      if (last && last.day === day) last.items.push(item);
      else out.push({ day, label: dayLabel(day, today), items: [item] });
    });
    return out;
  }

  /** Bridge row → view row (who said it, what to draw, what to copy). */
  function toRow(item, ctx) {
    ctx = ctx || {};
    const side = item.dir === 'out' ? 'out' : 'in';
    const showImages = ctx.showImages !== false;
    const kind = item.kind || 'text';
    const media = item.media
      ? {
          id: item.media.id,
          url: item.media.url || '',
          kind: item.media.kind || kind,
          state: item.media.state || '',
          path: item.media.path || '',
          copyable: true,
          show: showImages,
        }
      : null;
    return {
      type: 'msg',
      ord: item.ord,
      fp: item.fp,
      side: side,
      author: item.from || (side === 'out' ? (ctx.myNick || 'me')
                                           : (ctx.nick || '')),
      partner: ctx.nick || '',
      myNick: ctx.myNick || '',
      time: item.time || '',
      day: item.day || '',
      kind: kind,
      text: item.text || '',
      media: media,
      placeholder: media
        ? (media.kind === 'gif' ? 'GIF — click to copy'
                                : 'Image — click to copy')
        : '',
    };
  }

  /** Split `text` into [{ text, hit }] segments — literal, case-insensitive. */
  function highlight(text, query) {
    const src = text == null ? '' : String(text);
    const needle = query == null ? '' : String(query);
    if (!needle) return [{ text: src, hit: false }];
    const hay = src.toLowerCase();
    const q = needle.toLowerCase();
    const out = [];
    let at = 0;
    for (;;) {
      const found = hay.indexOf(q, at);
      if (found < 0) break;
      if (found > at) out.push({ text: src.slice(at, found), hit: false });
      out.push({ text: src.slice(found, found + q.length), hit: true });
      at = found + q.length;
    }
    if (at < src.length) out.push({ text: src.slice(at), hit: false });
    return out;
  }

  /** Plain text for the clipboard — both nicks and the times survive. */
  function clipboardText(items, ctx) {
    ctx = ctx || {};
    return (items || []).map((item) => {
      const row = item.type === 'msg' ? item : toRow(item, ctx);
      const body = row.text ||
        (row.media ? (row.media.url || '[' + row.kind + ']') : '');
      return (row.time ? row.time + ' ' : '') + row.author + ': ' + body;
    }).join('\n');
  }

  // ── the paging model ─────────────────────────────────────────

  function create(options) {
    const cfg = Object.assign({}, DEFAULTS, options || {});
    const model = {
      pageSize: cfg.pageSize,
      preloadRows: cfg.preloadRows,
      maxRows: cfg.maxRows,
      nick: '',
      myNick: '',
      showImages: cfg.showImages !== false,
      items: [],
      gaps: [],
      total: 0,
      loading: false,
      hasOlder: true,
      hasNewer: false,
      missing: false,
      pendingLive: 0,
      buffer: [],
    };

    Object.defineProperty(model, 'isEmpty', {
      get() { return model.items.length === 0; },
    });
    Object.defineProperty(model, 'firstOrd', {
      get() { return model.items.length ? model.items[0].ord : null; },
    });
    Object.defineProperty(model, 'lastOrd', {
      get() {
        return model.items.length
          ? model.items[model.items.length - 1].ord : null;
      },
    });

    /** Start over — a different person, or a forced reload of this one. */
    model.reset = function (opts) {
      opts = opts || {};
      if (opts.nick !== undefined) model.nick = opts.nick;
      if (opts.myNick !== undefined) model.myNick = opts.myNick;
      if (opts.showImages !== undefined) model.showImages = !!opts.showImages;
      if (opts.preloadRows !== undefined)
        model.preloadRows = Number(opts.preloadRows) || model.preloadRows;
      if (opts.pageSize !== undefined)
        model.pageSize = Number(opts.pageSize) || model.pageSize;
      model.items = [];
      model.gaps = [];
      model.total = 0;
      model.loading = false;
      model.hasOlder = true;
      model.hasNewer = false;
      model.missing = false;
      model.pendingLive = 0;
      model.buffer = [];
      return model;
    };

    function request(extra) {
      model.loading = true;
      return Object.assign({ nick: model.nick, limit: model.pageSize },
                           extra || {});
    }

    /** Newest page for this person. */
    model.requestInitial = function () {
      model.loading = true;
      return { nick: model.nick, limit: model.pageSize,
               before_ord: null, after_ord: null };
    };

    /** One page of older rows, or null when there is nothing to fetch. */
    model.requestOlder = function () {
      if (model.loading || !model.hasOlder || !model.items.length) return null;
      return request({ before_ord: model.items[0].ord });
    };

    /** One page of newer rows, or null. */
    model.requestNewer = function () {
      if (model.loading || !model.hasNewer || !model.items.length) return null;
      return request({ after_ord: model.items[model.items.length - 1].ord });
    };

    /** Jump back to the live tail: drop the buffer and reload from the end. */
    model.requestLatest = function () {
      model.buffer = [];
      model.pendingLive = 0;
      model.loading = true;
      return { nick: model.nick, limit: model.pageSize,
               before_ord: null, after_ord: null, latest: true };
    };

    /** True when `ord` is close enough to the top to prefetch older rows. */
    model.needsOlder = function (ord) {
      if (!model.hasOlder || model.loading || !model.items.length) return false;
      const index = model.items.findIndex((r) => r.ord === ord);
      if (index < 0) return false;
      return index <= model.preloadRows;
    };

    /** True when `ord` is close enough to the bottom to prefetch newer rows. */
    model.needsNewer = function (ord) {
      if (!model.hasNewer || model.loading || !model.items.length) return false;
      const index = model.items.findIndex((r) => r.ord === ord);
      if (index < 0) return false;
      return index >= model.items.length - 1 - model.preloadRows;
    };

    function mergeGaps(gaps) {
      const seen = new Set(model.gaps.map((g) => g.ord + ':' + g.reason));
      (gaps || []).forEach((gap) => {
        const key = gap.ord + ':' + gap.reason;
        if (!seen.has(key)) { seen.add(key); model.gaps.push(gap); }
      });
      model.gaps.sort((a, b) => a.ord - b.ord);
    }

    function trim(position) {
      if (model.items.length <= model.maxRows) return;
      if (position === 'older') {
        // The user is reading upwards: keep the rows just loaded and drop
        // the newest ones — they can always be paged back in.
        model.items = model.items.slice(0, model.maxRows);
        model.hasNewer = true;
      } else {
        model.items = model.items.slice(model.items.length - model.maxRows);
        model.hasOlder = true;
      }
    }

    /**
     * Fold a bridge page into the loaded window.
     * `opts.position`: 'initial' (replace), 'older', 'newer' — inferred
     * from the page when omitted.
     */
    model.applyPage = function (page, opts) {
      opts = opts || {};
      model.loading = false;
      if (!page || (page.nick && model.nick && page.nick !== model.nick))
        return model;               // a stale answer for another person
      const incoming = (page.items || []).slice();
      let position = opts.position;
      if (!position) {
        if (!model.items.length) position = 'initial';
        else if (incoming.length &&
                 incoming[incoming.length - 1].ord < model.items[0].ord)
          position = 'older';
        else position = 'newer';
      }
      if (position === 'initial') {
        model.items = incoming;
        model.gaps = [];
        model.hasNewer = page.has_newer !== undefined ? !!page.has_newer : false;
        model.hasOlder = page.has_more !== undefined ? !!page.has_more : false;
        model.pendingLive = 0;
        model.buffer = [];
      } else {
        const byOrd = new Map();
        model.items.forEach((row) => byOrd.set(row.ord, row));
        incoming.forEach((row) => { if (!byOrd.has(row.ord)) byOrd.set(row.ord, row); });
        model.items = Array.from(byOrd.values()).sort((a, b) => a.ord - b.ord);
        if (position === 'older' && page.has_more !== undefined)
          model.hasOlder = !!page.has_more;
        if (position === 'newer' && page.has_newer !== undefined)
          model.hasNewer = !!page.has_newer;
      }
      if (page.total !== undefined) model.total = page.total;
      model.missing = !!page.missing;
      mergeGaps(page.gaps);
      trim(position);
      return model;
    };

    /**
     * Rows pushed by the passive collector. They are only merged when the
     * view really is at the live end; otherwise they are counted so the UI
     * can offer a "jump to latest".
     */
    model.appendLive = function (rows) {
      const incoming = (rows || []).slice();
      if (!incoming.length) return 0;
      if (model.hasNewer) {
        model.buffer = model.buffer.concat(incoming);
        model.pendingLive = model.buffer.length;
        return 0;
      }
      const seen = new Set(model.items.map((r) => r.ord + '|' + r.fp));
      const fresh = incoming.filter((r) => !seen.has(r.ord + '|' + r.fp));
      if (!fresh.length) return 0;
      model.items = model.items.concat(fresh).sort((a, b) => a.ord - b.ord);
      model.total += fresh.length;
      trim('newer');
      return fresh.length;
    };

    /** The loaded window with day separators and gap markers woven in. */
    model.rowsWithMarkers = function (ctx) {
      const context = Object.assign({ nick: model.nick, myNick: model.myNick,
                                      showImages: model.showImages },
                                    ctx || {});
      const out = [];
      let day = null;
      let gapIndex = 0;
      const gaps = model.gaps.slice();
      model.items.forEach((item) => {
        while (gapIndex < gaps.length && gaps[gapIndex].ord <= item.ord) {
          const gap = gaps[gapIndex++];
          out.push({ type: 'gap', ord: gap.ord, reason: gap.reason || '',
                     note: gap.note || '' });
        }
        if (item.day && item.day !== day) {
          day = item.day;
          out.push({ type: 'day', day: day,
                     label: dayLabel(day, context.today) });
        }
        out.push(toRow(item, context));
      });
      while (gapIndex < gaps.length) {
        const gap = gaps[gapIndex++];
        out.push({ type: 'gap', ord: gap.ord, reason: gap.reason || '',
                   note: gap.note || '' });
      }
      return out;
    };

    /** Day groups of view rows — the default rendering path. */
    model.groups = function (ctx) {
      const context = Object.assign({ nick: model.nick, myNick: model.myNick,
                                      showImages: model.showImages },
                                    ctx || {});
      return groupByDay(model.items.map((i) => toRow(i, context)), context);
    };

    return model;
  }

  return {
    create, DEFAULTS,
    groupByDay, dayLabel, previousDay, toRow, highlight, clipboardText,
  };
});
