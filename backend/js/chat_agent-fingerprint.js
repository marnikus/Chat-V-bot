/* chat_agent-fingerprint.js — the record fingerprint (Round II Area A).

   Split out of backend/js/chat_agent.js; the install facade lists its
   parts. This is the value the page computes per message line so Python
   can re-find "the same line" across walks.

   MIRROR-LOCK: the algorithm below is mirrored byte-for-byte in Python
   (backend/history_models.py) and both sides are pinned by tests
   (tests/test_chat_parser_delta.py, tests/unit/backend/test_history_models.py).
   Do not touch the math — extend only.
*/
'use strict';

const ChatAgentFp = {
  // record-field separator: a control char real chat text never contains
  SEP: '\u001f',

  fnv1a(str, seed) {
    var h = seed >>> 0;
    for (var i = 0; i < str.length; i++) {
      h = (h ^ str.charCodeAt(i)) >>> 0;
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h >>> 0;
  },

  hex8(n) {
    var s = (n >>> 0).toString(16);
    while (s.length < 8) s = '0' + s;
    return s;
  },

  fingerprint(dir, from, time, kind, payload, occ) {
    var joined = [dir || '', from || '', time || '', kind || 'text',
                  payload || '', String(occ || 0)].join(this.SEP);
    return this.hex8(this.fnv1a(joined, 0x811c9dc5)) +
           this.hex8(this.fnv1a(joined + '\u0001', 0x01000193));
  },
};
