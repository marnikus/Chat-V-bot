/* Synthetic DOM-stub scenarios reconstructed from the supplied Area A bundle.
   These are not live HTML captures. Structure follows tests/dom_stub.js.
   Changes must be checked against real browser fixtures before claiming live
   site compatibility. Agent outputs are frozen in approvals.js. */
'use strict';
const ME = 'HiHoney';
const PARTNER = 'На работе 25';
const line = (i, from, over) => Object.assign(
  { dir: from === ME ? 'out' : 'in', from, text: 'line ' + i,
    time: '17:' + String(10 + (i % 50)) }, over || {});
const chat = (n, partner) => Array.from(
  { length: n }, (_, i) => line(i, i % 2 ? ME : (partner || PARTNER)));
const PAGES = {
  private_two_nicks: {
    spec: { tab: 'user', partner: PARTNER, me: ME, participants: 2,
            messages: chat(6) },
  },
  room_many_authors: {
    spec: { tab: 'room', partner: 'Гостиная', me: ME, participants: 5,
            messages: [line(0, 'Макс__Б'), line(1, ME), line(2, 'Ански'),
                       line(3, 'Макс__Б'), line(4, 'Zed')] },
  },
  private_with_stranger: {
    spec: { tab: 'user', partner: PARTNER, me: ME, participants: 3,
            messages: [line(0, PARTNER), line(1, ME), line(2, 'Макс__Б')] },
  },
  emoji_quoted_nicks: {
    spec: { tab: 'user', partner: '"Ⓜ️ Мила" 🌸', me: 'Хорошо "Все"',
            participants: 2,
            messages: [line(0, '"Ⓜ️ Мила" 🌸'),
                       line(1, 'Хорошо "Все"', { dir: 'out' }),
                       line(2, '"Ⓜ️ Мила" 🌸', { text: 'привет 😀 "ты"' })] },
  },
  media_lines: {
    spec: { tab: 'user', partner: PARTNER, me: ME, participants: 2,
            messages: [line(0, PARTNER, { text: '', media: 'https://images.virt-chat.com/a.png' }),
                       line(1, ME, { text: '', media: 'https://images.virt-chat.com/b.gif' }),
                       line(2, PARTNER)] },
  },
  trimmed_conversation: {
    spec: { tab: 'user', partner: PARTNER, me: ME, participants: 2,
            messages: chat(12) },
    arrange(env, agent) { agent.state(); env.trim(5); },
  },
  leftover_hidden_pane: {
    spec: { tab: 'user', partner: PARTNER, me: ME, participants: 2,
            messages: chat(4) },
    arrange(env) {
      const stale = env.prependPane([line(0, 'Ански'), line(1, ME), line(2, 'Ански')]);
      stale.hide();
    },
  },
  empty_private_pane: {
    spec: { tab: 'user', partner: PARTNER, me: ME, participants: 2, messages: [] },
  },
};
module.exports = { PAGES, ME, PARTNER, line, chat };
