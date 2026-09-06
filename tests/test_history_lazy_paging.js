/* Tests for the history paging model (ui/js/history-model.js).

   The model is the pure half of the archive UI: it owns the loaded window
   of rows, decides WHEN to ask Python for more (lazy loading with a
   configurable preload margin), de-duplicates live appends against rows
   already on screen, and caps how much stays in memory. It touches no DOM,
   so Node can execute the real shipped file.

   Run:  node tests/test_history_lazy_paging.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(
  path.join(__dirname, '..', 'ui', 'js', 'history-model.js'), 'utf8');
const module_ = { exports: {} };
new Function('module', 'exports', src)(module_, module_.exports);
const H = module_.exports;

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error((msg || 'eq') + '\n  got:  ' + ja + '\n  want: ' + jb);
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }

/** rows as the bridge sends them: ascending `ord`, oldest first */
function rows(from, to, over) {
  const out = [];
  for (let o = from; o <= to; o++) {
    out.push(Object.assign({
      ord: o, fp: 'fp' + o, dir: o % 2 ? 'out' : 'in',
      from: o % 2 ? 'Me' : 'Nick', kind: 'text', text: 'line ' + o,
      media: null, time: '17:31', day: '2026-09-06',
    }, over || {}));
  }
  return out;
}

const page = (from, to, over) => Object.assign({
  nick: 'Nick', items: rows(from, to), total: 1000,
  has_more: from > 1, has_newer: to < 1000, gaps: [], missing: false,
}, over || {});

function model(opts) {
  const m = H.create(Object.assign({ pageSize: 50, preloadRows: 10,
                                     maxRows: 200 }, opts || {}));
  m.reset({ nick: 'Nick', myNick: 'Me' });
  return m;
}

// ── loading the first page ───────────────────────────────────────

t('a fresh model is empty and knows both nicks', () => {
  const m = model();
  eq(m.items.length, 0);
  eq(m.nick, 'Nick');
  eq(m.myNick, 'Me');
  ok(m.loading === false, 'nothing in flight yet');
});

t('the first request asks for the newest page', () => {
  const m = model();
  const req = m.requestInitial();
  eq(req.nick, 'Nick');
  eq(req.limit, 50);
  ok(req.before_ord == null && req.after_ord == null, 'anchored at the end');
});

t('applying the first page fills the model newest-last', () => {
  const m = model();
  m.requestInitial();
  m.applyPage(page(951, 1000, { has_newer: false }));
  eq(m.items.length, 50);
  eq(m.items[0].ord, 951);
  eq(m.items[49].ord, 1000);
  eq(m.total, 1000);
  ok(m.loading === false, 'the request is finished');
});

// ── lazy paging upward ───────────────────────────────────────────

t('scrolling near the top asks for older rows', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(951, 1000, { has_newer: false }));
  ok(!m.needsOlder(m.items[30].ord), 'the middle must not trigger a load');
  ok(m.needsOlder(m.items[5].ord), 'within the preload margin it must');
  const req = m.requestOlder();
  eq(req.before_ord, 951);
  eq(req.limit, 50);
});

t('the preload margin is configurable', () => {
  const m = model({ preloadRows: 40 });
  m.requestInitial(); m.applyPage(page(951, 1000, { has_newer: false }));
  ok(m.needsOlder(m.items[30].ord), 'a bigger margin triggers earlier');
});

t('only one request is in flight at a time', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(951, 1000, { has_newer: false }));
  ok(m.requestOlder(), 'the first request is issued');
  eq(m.requestOlder(), null, 'a second must be suppressed');
  m.applyPage(page(901, 950), { position: 'older' });
  ok(m.requestOlder(), 'and allowed again once the answer arrived');
});

t('older rows are prepended in order, without gaps or duplicates', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(951, 1000, { has_newer: false }));
  m.requestOlder(); m.applyPage(page(901, 950), { position: 'older' });
  eq(m.items.length, 100);
  eq(m.items[0].ord, 901);
  eq(m.items[99].ord, 1000);
  const ords = m.items.map((r) => r.ord);
  eq(ords, ords.slice().sort((a, b) => a - b), 'still ascending');
});

t('an overlapping page does not duplicate rows', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(951, 1000, { has_newer: false }));
  m.requestOlder(); m.applyPage(page(941, 960), { position: 'older' });
  eq(new Set(m.items.map((r) => r.ord)).size, m.items.length);
  eq(m.items.length, 60);
});

t('reaching the beginning stops the paging', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(1, 50, { has_more: false, has_newer: false }));
  ok(!m.hasOlder, 'the model knows it is at the start');
  eq(m.requestOlder(), null, 'no further requests');
  ok(m.needsOlder(1) === false, 'and the scroll handler stays quiet');
});

t('an empty answer also ends the paging', () => {
  const m = model();
  m.requestInitial();
  m.applyPage({ nick: 'Nick', items: [], total: 0, has_more: false,
                has_newer: false, gaps: [], missing: true });
  eq(m.items.length, 0);
  ok(m.isEmpty, 'the view can show an empty state');
  ok(m.missing, 'an unknown nick is flagged');
});

// ── live appends ─────────────────────────────────────────────────

t('live rows are appended when the view is at the bottom', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(951, 1000, { has_newer: false }));
  eq(m.appendLive(rows(1001, 1002)), 2);
  eq(m.items[m.items.length - 1].ord, 1002);
  eq(m.total, 1002);
});

t('a live row already on screen is ignored', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(951, 1000, { has_newer: false }));
  eq(m.appendLive(rows(1000, 1000)), 0, 'same fingerprint, same ord');
  eq(m.items.length, 50);
});

t('live rows are held back while older history is on screen', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(500, 549));   // has_newer: true
  eq(m.appendLive(rows(1001, 1001)), 0, 'must not jump across a gap');
  eq(m.pendingLive, 1, 'but it is remembered');
  ok(m.hasNewer, 'the view can offer a jump-to-latest');
});

t('jumping to the latest clears the buffer and reloads', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(500, 549));
  m.appendLive(rows(1001, 1001));
  const req = m.requestLatest();
  ok(req && req.before_ord == null, 'a fresh tail request');
  m.applyPage(page(953, 1002, { has_newer: false }), { position: 'initial' });
  eq(m.pendingLive, 0);
  eq(m.items[m.items.length - 1].ord, 1002);
});

// ── memory ───────────────────────────────────────────────────────

t('the loaded window is capped', () => {
  const m = model({ maxRows: 120 });
  m.requestInitial(); m.applyPage(page(881, 1000, { has_newer: false }));
  m.requestOlder(); m.applyPage(page(831, 880), { position: 'older' });
  ok(m.items.length <= 120, 'rows in memory: ' + m.items.length);
  eq(m.items[0].ord, 831, 'trimming drops the far end, not the new rows');
  ok(m.hasNewer, 'and the model knows rows were dropped below');
});

t('reset clears everything', () => {
  const m = model();
  m.requestInitial(); m.applyPage(page(951, 1000, { has_newer: false }));
  m.reset({ nick: 'Other', myNick: 'Me' });
  eq(m.items.length, 0);
  eq(m.nick, 'Other');
  ok(m.hasOlder, 'a new person starts unpaged');
});

t('a page for the wrong person is discarded', () => {
  const m = model();
  m.requestInitial();
  m.applyPage(page(951, 1000, { nick: 'Someone Else' }));
  eq(m.items.length, 0, 'a stale answer must never land in the wrong window');
});

// ── grouping, gaps and rendering data ────────────────────────────

t('rows are grouped by day with readable labels', () => {
  const items = rows(1, 2).concat(rows(3, 4, { day: '2026-09-05' }));
  const groups = H.groupByDay(items, { today: '2026-09-06' });
  eq(groups.length, 2);
  eq(groups[0].day, '2026-09-06');
  ok(/today/i.test(groups[0].label), 'label: ' + groups[0].label);
  ok(/yesterday/i.test(groups[1].label), 'label: ' + groups[1].label);
  eq(groups[1].items.length, 2);
});

t('a gap in the archive is exposed as a marker row', () => {
  const m = model();
  m.requestInitial();
  m.applyPage(page(951, 1000, { has_newer: false,
                                gaps: [{ ord: 975, reason: 'alignment_lost' }] }));
  const marks = m.rowsWithMarkers().filter((r) => r.type === 'gap');
  eq(marks.length, 1);
  eq(marks[0].ord, 975);
  ok(/alignment/i.test(marks[0].reason), 'the reason survives to the UI');
});

t('the view model labels who said what, both ways', () => {
  const m = model();
  const mine = H.toRow(rows(1, 1, { dir: 'out', from: 'Me' })[0],
                       { nick: 'Nick', myNick: 'Me' });
  const theirs = H.toRow(rows(2, 2, { dir: 'in', from: 'Nick' })[0],
                         { nick: 'Nick', myNick: 'Me' });
  eq(mine.side, 'out');
  eq(mine.author, 'Me');
  eq(theirs.side, 'in');
  eq(theirs.author, 'Nick');
});

t('media rows carry a copyable reference and honour the images toggle', () => {
  const row = H.toRow({ ord: 5, fp: 'x', dir: 'in', from: 'Nick', kind: 'gif',
                        text: '', media: { id: 7, url: 'https://x/y.gif',
                                           kind: 'gif' }, time: '18:00',
                        day: '2026-09-06' },
                      { nick: 'Nick', myNick: 'Me', showImages: true });
  eq(row.kind, 'gif');
  eq(row.media.id, 7);
  ok(row.media.copyable, 'left click must be able to copy it');
  const off = H.toRow({ ord: 5, fp: 'x', dir: 'in', from: 'Nick', kind: 'gif',
                        text: '', media: { id: 7, url: 'https://x/y.gif',
                                           kind: 'gif' }, time: '18:00',
                        day: '2026-09-06' },
                      { nick: 'Nick', myNick: 'Me', showImages: false });
  ok(!off.media.show, 'with images off only a placeholder link is drawn');
  ok(/gif/i.test(off.placeholder), 'placeholder: ' + off.placeholder);
});

// ── search helpers ───────────────────────────────────────────────

t('highlighting splits text into plain and hit segments', () => {
  const segs = H.highlight('повезло ученикам))', 'ученик');
  eq(segs.map((s) => s.text).join(''), 'повезло ученикам))');
  eq(segs.filter((s) => s.hit).map((s) => s.text), ['ученик']);
});

t('highlighting is case insensitive, including Cyrillic', () => {
  eq(H.highlight('Привет Мир', 'привет').filter((s) => s.hit)[0].text, 'Привет');
});

t('highlighting never treats the query as a pattern', () => {
  const segs = H.highlight('a+b (c)', '+b (');
  eq(segs.filter((s) => s.hit).map((s) => s.text), ['+b (']);
  eq(H.highlight('plain', '').filter((s) => s.hit).length, 0);
});

t('copying a selection keeps both nicks and the times', () => {
  const text = H.clipboardText(rows(1, 2), { nick: 'Nick', myNick: 'Me' });
  ok(text.includes('Nick'), 'partner nick');
  ok(text.includes('Me'), 'my nick');
  ok(text.includes('line 1') && text.includes('line 2'), 'the messages');
  eq(text.split('\n').length, 2);
});

// ── reporting ────────────────────────────────────────────────────

console.log('history_lazy_paging: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
