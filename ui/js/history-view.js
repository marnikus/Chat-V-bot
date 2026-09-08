/* ═══════════════════════════════════════════════════════════════
   history-view.js — renders archive rows into the DOM

   Every promise made to the user lives here:
     · chat text is inserted as TEXT, never as markup (hostile input)
     · the text stays selectable, so it can be copied normally
     · images and GIFs copy on a plain left click
     · both nicks (the partner's and mine) are always on screen

   Nodes are built with createElement/createTextNode only — never by
   assigning markup strings. tests/test_history_render.js runs this exact
   file against a DOM stub that throws if a markup setter is touched.
   ═══════════════════════════════════════════════════════════════ */

var HistoryView = (function () {
  'use strict';

  const Model = (typeof HistoryModel !== 'undefined') ? HistoryModel
    : (typeof window !== 'undefined' ? window.HistoryModel : null);

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null && text !== '')
      node.appendChild(document.createTextNode(String(text)));
    return node;
  }

  /** Append `text` with the search query highlighted (as text nodes). */
  function appendHighlighted(host, text, query) {
    const segments = (Model && query)
      ? Model.highlight(text, query)
      : [{ text: text == null ? '' : String(text), hit: false }];
    segments.forEach((segment) => {
      if (!segment.text) return;
      if (segment.hit) host.appendChild(el('span', 'hit', segment.text));
      else host.appendChild(document.createTextNode(segment.text));
    });
  }

  // ── one message row ──────────────────────────────────────────

  /** the saved file when there is one, the remote url only as a fallback */
  function mediaSrc(media) {
    const asUrl = (typeof HistoryModel !== 'undefined' && HistoryModel.fileUrl)
      ? HistoryModel.fileUrl : (p) => String(p || '');
    return media.src || asUrl(media.path) || media.url || '';
  }

  /** A failed/missing image gets a visible "restore" marker, not a broken
   *  <img> that the user cannot act on. */
  function mediaRestoreNode(media, opts, row) {
    const box = el('div', 'msg-media-restore');
    box.dataset.mediaId = String(media.id == null ? '' : media.id);
    box.appendChild(el('span', 'msg-media-restore-kind',
                       media.kind === 'gif' ? 'GIF' : 'Image'));
    box.appendChild(el('span', 'msg-media-restore-label', 'click to restore'));
    box.title = media.url || '';
    if (typeof opts.onRestoreMedia === 'function') {
      box.addEventListener('click', (event) => {
        if (event && event.button) return;          // left click only
        if (event && event.preventDefault) event.preventDefault();
        opts.onRestoreMedia(media.id, row);
      });
    }
    return box;
  }

  function mediaNode(row, opts) {
    const media = row.media;
    if (!media) return null;
    if (media.show === false || opts.showImages === false) {
      const off = el('span', 'msg-media-off',
                     row.placeholder ||
                     (media.kind === 'gif' ? 'GIF (images off)'
                                           : 'Image (images off)'));
      off.dataset.mediaId = String(media.id == null ? '' : media.id);
      off.title = media.url || '';
      return off;
    }
    const usable = media.path &&
      media.state !== 'failed' && media.state !== 'skipped' &&
      media.state !== 'missing' && media.state !== 'evicted';
    if (!usable) return mediaRestoreNode(media, opts, row);
    const wrap = el('div', 'msg-media-box');
    const img = document.createElement('img');
    img.className = 'msg-media' + (media.kind === 'gif' ? ' is-gif' : '');
    img.dataset.mediaId = String(media.id == null ? '' : media.id);
    img.setAttribute('src', mediaSrc(media));
    img.setAttribute('alt', media.kind === 'gif' ? 'GIF' : 'image');
    img.setAttribute('loading', 'lazy');
    img.title = 'Click to copy';
    img.addEventListener('error', (event) => {
      if (event && event.preventDefault) event.preventDefault();
      wrap.replaceChildren(mediaRestoreNode(media, opts, row));
    });
    if (typeof opts.onCopyMedia === 'function') {
      img.addEventListener('click', (event) => {
        if (event && event.button) return;          // left click only
        if (event && event.preventDefault) event.preventDefault();
        opts.onCopyMedia(media.id, row);
      });
    }
    wrap.appendChild(img);
    return wrap;
  }

  function messageNode(row, opts) {
    const wrap = el('div', 'msg ' + (row.side === 'out' ? 'out' : 'in'));
    wrap.dataset.ord = String(row.ord);
    wrap.dataset.fp = String(row.fp == null ? '' : row.fp);
    if (row.id != null && row.id !== '') wrap.dataset.id = String(row.id);
    const head = el('div', 'msg-head');
    head.appendChild(el('span', 'msg-author', row.author));
    head.appendChild(el('span', 'msg-time', row.time));
    // Remove THIS message from the history. Soft delete on the backend, so
    // the global Ctrl+Z brings it straight back.
    if (typeof opts.onDeleteMessage === 'function' && row.id != null &&
        row.id !== '') {
      const del = el('button', 'msg-del', '✕');
      del.type = 'button';
      del.title = 'Remove this message from the history (Ctrl+Z restores it)';
      del.dataset.id = String(row.id);
      del.addEventListener('click', (event) => {
        if (event && event.preventDefault) event.preventDefault();
        if (event && event.stopPropagation) event.stopPropagation();
        opts.onDeleteMessage(row.id, row);
      });
      head.appendChild(del);
    }
    wrap.appendChild(head);
    const body = el('div', 'msg-text');
    if (String(row.text || '').trim()) appendHighlighted(body, row.text, opts.query);
    else if (!row.media) {
      body.classList.add('msg-text-missing');
      body.appendChild(document.createTextNode('[text not captured]'));
      body.title = 'Use Backfill older in the open private chat to retry capture.';
    }
    wrap.appendChild(body);
    const media = mediaNode(row, opts);
    if (media) wrap.appendChild(media);
    return wrap;
  }

  function gapNode(row) {
    const reason = String(row.reason || '');
    const wrap = el('div', 'msg-gap');
    wrap.dataset.ord = String(row.ord);
    wrap.appendChild(document.createTextNode(
      '⚠ gap in the archive — some messages here are missing' +
      (reason ? ' (' + reason.replace(/_/g, ' ') + ')' : '')));
    return wrap;
  }

  function dayNode(row) {
    const wrap = el('div', 'day-sep');
    wrap.appendChild(el('span', 'day-sep-label', row.label || row.day || ''));
    return wrap;
  }

  function nodeFor(row, opts) {
    if (!row) return null;
    if (row.type === 'gap') return gapNode(row);
    if (row.type === 'day') return dayNode(row);
    return messageNode(row, opts);
  }

  // ── public rendering entry points ────────────────────────────

  /** Replace the contents of `host` with these rows / markers. */
  function renderRows(host, rows, opts) {
    opts = opts || {};
    if (!host) return host;
    const nodes = [];
    (rows || []).forEach((row) => {
      const node = nodeFor(row, opts);
      if (node) nodes.push(node);
    });
    host.replaceChildren.apply(host, nodes);
    return host;
  }

  /** Day-grouped rendering: a separator above every group. */
  function renderGroups(host, groups, opts) {
    opts = opts || {};
    if (!host) return host;
    const nodes = [];
    (groups || []).forEach((group) => {
      nodes.push(dayNode({ label: group.label, day: group.day }));
      (group.items || []).forEach((item) => {
        const row = item.type === 'msg' ? item
          : (Model ? Model.toRow(item, opts) : item);
        const node = nodeFor(row, opts);
        if (node) nodes.push(node);
      });
    });
    host.replaceChildren.apply(host, nodes);
    return host;
  }

  /** The header of a person window: both nicks and the totals. */
  function renderHeader(host, info) {
    if (!host) return host;
    info = info || {};
    const stats = info.stats || null;
    const nodes = [];
    const title = el('div', 'history-title');
    title.appendChild(el('span', 'history-partner', info.nick || '—'));
    title.appendChild(el('span', 'history-arrow', ' ⇄ '));
    title.appendChild(el('span', 'history-me',
                         info.myNick ? info.myNick : 'my nick not set'));
    // The same label pills as in both tables, ✕ removes the label from this
    // person only.
    if (typeof info.pill === 'function' && (info.labels || []).length) {
      const pills = el('span', 'label-pills');
      info.labels.forEach((label) => pills.appendChild(info.pill(label)));
      title.appendChild(pills);
    }
    nodes.push(title);
    const meta = el('div', 'history-meta');
    if (stats) {
      const count = stats.messages != null ? stats.messages
                                           : (stats.message_count || 0);
      meta.appendChild(el('span', 'history-count', String(count) + ' messages'));
      if (stats.cleared_messages)
        meta.appendChild(el('span', 'history-cleared', ' · ' + stats.cleared_messages + ' cleared'));
      if (stats.first_day || stats.last_day) {
        meta.appendChild(el('span', 'history-range',
                            (stats.first_day || '?') + ' → ' +
                            (stats.last_day || '?')));
      }
      const media = stats.media_count != null ? stats.media_count : stats.media;
      if (media) {
        meta.appendChild(el('span', 'history-media', String(media) + ' media'));
      }
    } else {
      meta.appendChild(el('span', 'history-count', 'no messages archived yet'));
    }
    nodes.push(meta);
    host.replaceChildren.apply(host, nodes);
    return host;
  }

  /** Global search results, grouped per person. */
  function renderSearchGroups(host, groups, opts) {
    opts = opts || {};
    if (!host) return host;
    const nodes = [];
    (groups || []).forEach((group) => {
      const wrap = el('div', 'search-group');
      const head = el('div', 'search-group-head');
      head.appendChild(el('span', 'search-group-nick', group.nick || '—'));
      head.appendChild(el('span', 'search-group-count',
                          String((group.items || []).length) + ' hits'));
      wrap.appendChild(head);
      (group.items || []).forEach((hit) => {
        const line = el('div', 'search-hit');
        line.dataset.ord = String(hit.ord == null ? '' : hit.ord);
        line.dataset.nick = String(group.nick || '');
        if (hit.time) line.appendChild(el('span', 'msg-time', hit.time));
        const body = el('span', 'msg-text');
        appendHighlighted(body, hit.snippet || hit.text || '', opts.query);
        line.appendChild(body);
        if (typeof opts.onOpenHit === 'function') {
          line.addEventListener('click', () =>
            opts.onOpenHit(group.nick, hit.ord));
        }
        wrap.appendChild(line);
      });
      nodes.push(wrap);
    });
    host.replaceChildren.apply(host, nodes);
    return host;
  }

  /** A short one-line state banner (empty state, errors, hints). */
  function renderNotice(host, text, kind) {
    if (!host) return host;
    const note = el('div', 'history-notice' + (kind ? ' ' + kind : ''), text);
    host.replaceChildren(note);
    return host;
  }

  /** Copy from a node created by *appendMediaPath* (no renderer context). */
  function copyFromView(mediaId) {
    const store = (typeof HistoryStore !== 'undefined') ? HistoryStore
      : (typeof window !== 'undefined' ? window.HistoryStore : null);
    if (store && store.copyMedia) store.copyMedia(String(mediaId));
  }

  function appendMediaPath(host, mediaId, path, kind) {
    const want = String(mediaId == null ? '' : mediaId);
    const src = mediaSrc({ path: path });
    if (!want || !src) return false;
    let changed = false;
    host.querySelectorAll('.msg-media').forEach((node) => {
      if (String(node.dataset.mediaId) !== want) return;
      node.setAttribute('src', src);
      changed = true;
    });
    host.querySelectorAll('.msg-media-restore').forEach((node) => {
      if (String(node.dataset.mediaId) !== want) return;
      const wrap = document.createElement('div');
      wrap.className = 'msg-media-box';
      const img = document.createElement('img');
      img.className = 'msg-media' + (kind === 'gif' ? ' is-gif' : '');
      img.dataset.mediaId = want;
      img.setAttribute('src', src);
      img.setAttribute('alt', kind === 'gif' ? 'GIF' : 'image');
      img.setAttribute('loading', 'lazy');
      img.title = 'Click to copy';
      img.addEventListener('click', (event) => {
        if (event && event.button) return;          // left click only
        if (event && event.preventDefault) event.preventDefault();
        copyFromView(mediaId);
      });
      wrap.appendChild(img);
      if (typeof node.replaceWith === 'function') node.replaceWith(wrap);
      else if (node.parentNode) {
        const at = node.parentNode.children.indexOf(node);
        if (at >= 0) node.parentNode.children.splice(at, 1, wrap);
        wrap.parentNode = node.parentNode;
      }
      changed = true;
    });
    return changed;
  }

  /**
   * A file finished caching after the rows were drawn: point the <img> at
   * it without re-rendering (and without losing the scroll position).
   */
  function applyMediaPath(host, mediaId, path, kind) {
    if (!host || !host.querySelectorAll) return false;
    const want = String(mediaId == null ? '' : mediaId);
    if (!want || !mediaSrc({ path: path })) return false;
    return appendMediaPath(host, want, path, kind);
  }

  return {
    renderRows, renderGroups, renderHeader, renderSearchGroups, renderNotice,
    appendHighlighted, messageNode, gapNode, dayNode, mediaSrc,
    applyMediaPath, el,
  };
})();

if (typeof window !== 'undefined') window.HistoryView = HistoryView;
if (typeof module === 'object' && module.exports) module.exports = HistoryView;
