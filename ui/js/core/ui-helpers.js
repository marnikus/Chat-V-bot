/* UIHelpers — the small DOM builders that were copy-pasted across panels.

  esc(s)            HTML-escape any user text before it lands in markup
  el(tag, cls, text)  one element, no ceremony
  chip(opts)        the standard chip: [icon+title][meta][×]
                    used by the URL bookmarks and both preset pickers
  sortArrow(active, dir)  the ▲▼ / ▲ / ▼ header indicator

  Everything builds DOM nodes and sets textContent — user text never
  becomes markup (RULE 8).
*/
'use strict';

window.UIHelpers = {
  esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  },

  el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null && text !== '') {
      node.textContent = String(text);
    }
    return node;
  },

  /**
   * The standard removable chip.
   * opts: { title, meta, icon, selected, tooltip, onLoad, onDelete,
   *         deleteTitle }
   */
  chip(opts) {
    const o = opts || {};
    const node = this.el('span',
      'chip' + (o.selected ? ' chip-selected' : ''));
    if (o.tooltip) node.title = o.tooltip;
    const title = this.el('span', 'chip-title',
      (o.icon ? o.icon + ' ' : '') + (o.title || ''));
    title.title = o.title || '';
    node.appendChild(title);
    if (o.meta) {
      const meta = this.el('span', 'chip-meta', o.meta);
      node.appendChild(meta);
    }
    const x = this.el('span', 'chip-x', '×');
    x.title = o.deleteTitle || 'Delete';
    node.appendChild(x);
    if (typeof o.onLoad === 'function') {
      node.addEventListener('click', o.onLoad);
    }
    if (typeof o.onDelete === 'function') {
      x.addEventListener('click', (ev) => {
        ev.stopPropagation();
        o.onDelete(ev);
      });
    }
    return node;
  },

  /** ▲▼ idle · ▲ ascending · ▼ descending */
  sortArrow(active, direction) {
    if (!active) return '▲▼';
    return direction > 0 ? '▲' : '▼';
  },
};
