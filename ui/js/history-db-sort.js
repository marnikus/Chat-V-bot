/* history-db-sort.js — sort + request + error + live for HistoryDb facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const HistoryDbSort = {
  _wireSortHeaders() {
    document.querySelectorAll('#userdbTable th[data-sort]').forEach((th) => {
      th.addEventListener('click', () => this.sortBy(th.dataset.sort));
      th.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.sortBy(th.dataset.sort); }
      });
    });
  },

  sortBy(key) {
    if (!key || !Object.prototype.hasOwnProperty.call(this.NATURAL, key)) return;
    if (this.sortKey === key) this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
    else { this.sortKey = key; this.sortDir = this.NATURAL[key]; }
    this._updateSortHeaders();
    this.reload();
  },

  _updateSortHeaders() {
    document.querySelectorAll('#userdbTable th[data-sort]').forEach((th) => {
      const active = th.dataset.sort === this.sortKey;
      const arrow = th.querySelector('.sort-arrow');
      if (arrow) arrow.textContent = window.UIHelpers.sortArrow(active, this.sortDir === 'desc' ? -1 : 1);
      th.setAttribute('aria-sort', active ? (this.sortDir === 'asc' ? 'ascending' : 'descending') : 'none');
      th.classList.toggle('sort-active', active);
    });
  },

  onError(scope) {
    if (scope !== 'userdb_page' && scope !== 'userdb_stats') return;
    this.loading = false;
    if (this._retries >= this.RETRY_MAX || this._retryTimer) return;
    this._retries += 1;
    this._retryTimer = setTimeout(() => { this._retryTimer = null; this.reload({ keepScroll: true, _retry: true }); }, this.RETRY_MS);
  },

  onPage(reqId, json) {
    let data = null;
    try { data = JSON.parse(json); } catch (e) { data = null; }
    if (!data) { this.loading = false; return; }
    this.loading = false;
    clearTimeout(this._retryTimer); this._retryTimer = null; this._retries = 0;
    if (data.persons !== undefined && data.items === undefined) { this.onStats(data); return; }
    const items = data.items || [];
    if (data.offset ? data.offset === 0 : !this.rows.length) this.rows = items;
    else {
      const seen = new Set(this.rows.map((r) => r.nick));
      items.forEach((item) => { if (!seen.has(item.nick)) this.rows.push(item); });
    }
    this.total = data.total != null ? data.total : this.rows.length;
    this.hasMore = !!data.has_more;
    this.render();
  },

  onStats(data) {
    if (!this._els.foot) return;
    const parts = [];
    if (data.persons != null) parts.push(data.persons + ' people');
    if (data.messages != null) parts.push(data.messages + ' messages');
    if (data.media != null) parts.push(data.media + ' media');
    const bytes = data.bytes != null ? data.bytes : data.media_bytes;
    if (bytes != null) parts.push((bytes / 1048576).toFixed(1) + ' MB cached');
    if (data.gaps) parts.push(data.gaps + ' gaps');
    this._els.foot.textContent = parts.join(' · ');
  },

  onChanged() { clearTimeout(this._liveTimer); this.reload(); },

  liveChanged(reason) {
    this._liveReason = reason || '';
    clearTimeout(this._liveTimer);
    this._liveTimer = setTimeout(() => { this._liveReason = ''; if (this._els.body) this.reload({ keepScroll: true }); }, 400);
  },

  _onScroll() {
    const list = this._els.list;
    if (!list || this.loading || !this.hasMore) return;
    const remaining = list.scrollHeight - list.scrollTop - list.clientHeight;
    if (remaining < 120) this._request(this.rows.length);
  },

  deletePerson(nick) { if (!App.bridge || !App.bridge.history_delete_person) return; App.bridge.history_delete_person(nick, false); },

  clearHistory(nick) { if (!App.bridge || !App.bridge.history_clear_person) return; App.bridge.history_clear_person(nick); },

  labelPerson(nick) { if (typeof Labels === 'undefined') return; Labels.setPerson(nick, { focus: true }); },

  markLabelTarget(nick) {
    const body = this._els.body;
    if (!body || !body.querySelectorAll) return;
    const clean = String(nick || '').trim();
    body.querySelectorAll('tr[data-nick]').forEach((row) => {
      const on = !!clean && row.dataset.nick === clean;
      row.classList.toggle('row-label-target', on);
      if (on && row.scrollIntoView) row.scrollIntoView({ block: 'nearest' });
    });
  },

  highlightNick(nick) {
    this._flashNick = String(nick || '').trim();
    if (!this._flashNick) return;
    this.query = this._flashNick;
    if (this._els.search) this._els.search.value = this._flashNick;
    this._flashIfPresent();
    this.reload();
  },
};

if (typeof window !== 'undefined') window.HistoryDbSort = HistoryDbSort;
