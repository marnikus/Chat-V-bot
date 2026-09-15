/* labels-render.js — pill renderer for Labels facade (H-B2b JS split)

Shared pill renderer: pills(), pill(), tint(), _notice(), plus repaintTables.

Design: AREA_H §6.4 — ≤200 LOC, named responsibility.
*/

'use strict';

const LabelsRender = {
  pills(nick, options) {
    options = options || {};
    const host = document.createElement('span');
    host.className = 'label-pills';
    host.dataset.nick = String(nick == null ? '' : nick);
    const items = options.labels || this.forNick(nick);
    if (!items.length) {
      if (options.emptyText) {
        const empty = document.createElement('span');
        empty.className = 'label-empty';
        empty.textContent = options.emptyText;
        host.appendChild(empty);
      }
      return host;
    }
    items.forEach((label) => {
      host.appendChild(this.pill(label, nick, options));
    });
    return host;
  },

  pill(label, nick, options) {
    options = options || {};
    const color = String((label && label.color) || '#8892a6');
    const pill = document.createElement('span');
    pill.className = 'label-pill';
    pill.dataset.labelId = String((label && label.id) || '');
    pill.style.background = this.tint(color, 0.22);
    pill.style.borderColor = color;
    pill.style.color = '#fff';
    pill.title = options.title || ((label && label.name ? label.name : '') +
      (options.removable === false ? '' : ' — ✕ removes it from this person only'));
    if (options.marked) {
      const check = document.createElement('span');
      check.className = 'label-pill-check';
      check.textContent = '✓';
      pill.appendChild(check);
    }
    const dot = document.createElement('span');
    dot.className = 'label-pill-dot';
    dot.style.background = color;
    pill.appendChild(dot);
    const text = document.createElement('span');
    text.className = 'label-pill-text';
    text.textContent = (label && label.name) || '';
    pill.appendChild(text);
    if (options.assigned) {
      pill.classList.add('assigned');
      pill.style.background = this.tint(color, 0.42);
      pill.style.boxShadow = '0 0 0 1.5px ' + color;
    }
    if (options.removable !== false) {
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'label-pill-x';
      x.textContent = '✕';
      x.title = 'Remove “' + ((label && label.name) || '') + '” from ' + (nick || 'this person');
      x.addEventListener('click', (event) => {
        if (event && event.stopPropagation) event.stopPropagation();
        if (event && event.preventDefault) event.preventDefault();
        if (typeof options.onRemove === 'function')
          options.onRemove(label.id, nick);
        else this.unassign(nick, label.id);
      });
      pill.appendChild(x);
    }
    return pill;
  },

  tint(hex, alpha) {
    const clean = String(hex || '').replace('#', '');
    const full = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean;
    const num = parseInt(full || '888888', 16);
    const r = (num >> 16) & 255, g = (num >> 8) & 255, b = num & 255;
    return 'rgba(' + r + ',' + g + ',' + b + ',' + (alpha == null ? 0.22 : alpha) + ')';
  },

  _notice(text) {
    const note = document.createElement('div');
    note.className = 'label-notice';
    note.textContent = text;
    return note;
  },

  repaintTables() {
    if (typeof UserTable !== 'undefined' && UserTable.render)
      UserTable.render(UserTable.users);
    if (typeof HistoryDb !== 'undefined' && HistoryDb.render)
      HistoryDb.render();
    if (typeof HistoryStore !== 'undefined' && HistoryStore.renderHeader)
      HistoryStore.renderHeader();
  },
};

if (typeof window !== 'undefined') window.LabelsRender = LabelsRender;
