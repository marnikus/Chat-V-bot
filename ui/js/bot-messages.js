/* ═══════════════════════════════════════════════════════════════
   bot-messages.js — how ONE message becomes a row in the Bot Chat window

   Split out of bot-chat.js, which owns the verification flow (approve /
   reject / retry / send) and should be readable as that flow alone. This
   file is the other job: turning an archive row into DOM.

   It draws NO media of its own. `HistoryModel.toRow` already resolves a
   cached file into a loadable src and `HistoryView.mediaNode` already draws
   every state the database has — cached, pending, failed, missing, evicted,
   images-off — so a GIF here looks like the same GIF in the DB window and
   there is ONE renderer to fix (RULE 5). The fallback below exists only for
   the case where those modules are absent; a message is never silently
   blank.

   Nodes are built with createElement/textContent only: a message is user
   (or model) text and must never become markup.

   ideal-size: 75 lines reason=deliberately small. It is the one seam that
   was genuinely separable from bot-chat.js's verification flow; growing it
   to a "nicer" size would mean pulling that flow back in.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BotMessages = {
  /** Draw one message into `host`. `onRestore(mediaId, row)` is called when
   *  the user clicks the restore marker of a file that is no longer cached. */
  bubble(item, host, onRestore) {
    const row = document.createElement('div');
    row.className = 'bot-msg ' + (item.dir === 'out' ? 'out' : 'in');
    const who = document.createElement('span');
    who.className = 'bot-msg-who';
    who.textContent = (item.from || (item.dir === 'out' ? 'me' : 'them')) +
      (item.time ? ' · ' + item.time : '');
    const body = document.createElement('div');
    body.className = 'bot-msg-text';
    body.textContent = item.text || '';
    row.appendChild(who);
    row.appendChild(body);
    const media = this._media(item, row, onRestore);
    if (media) row.appendChild(media);
    if (host) host.appendChild(row);
    return row;
  },

  /** The media block of one message, drawn by the DB window's renderer.
   *  A message whose file is gone gets the clickable "restore" marker. */
  _media(item, row, onRestore) {
    if (!item || !item.media) return null;
    if (typeof HistoryModel === 'undefined' ||
        typeof HistoryView === 'undefined') return this._mediaFallback(item);
    const viewRow = HistoryModel.toRow(item, { showImages: true });
    const node = HistoryView.mediaNode(viewRow, {
      showImages: true,
      onRestoreMedia: () => onRestore(item.media.id, row),
    });
    return node || this._mediaFallback(item);
  },

  /** Never a blank message: say what the attachment is even with no renderer. */
  _mediaFallback(item) {
    const media = item.media || {};
    const note = document.createElement('span');
    note.className = 'bot-msg-media-note';
    const kind = media.kind || item.kind || 'attachment';
    note.textContent = '[' + kind + ']' +
      (media.state && media.state !== 'cached' ? ' · ' + media.state : '');
    note.title = media.url || '';
    return note;
  },
};

if (typeof window !== 'undefined') window.BotMessages = BotMessages;
if (typeof module !== 'undefined') module.exports = BotMessages;
