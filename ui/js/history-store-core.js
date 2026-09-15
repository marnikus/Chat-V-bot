/* history-store-core.js — bootstrap + myNick + settings for HistoryStore facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const HistoryStoreCore = {
  model: null,
  nick: '',
  myNick: '',
  showImages: true,
  preloadRows: 40,
  pageSize: 50,
  query: '',
  scope: 'person',
  _seq: 0,
  _open: null,
  _els: {},

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winHistory'),
      header: $('historyHeader'),
      list: $('historyList'),
      search: $('historySearchInput'),
      global: $('historySearchGlobalBtn'),
      images: $('historyImagesToggle'),
      folder: $('historyFolderBtn'),
      clear: $('historyClearBtn'),
      removePerson: $('historyDeletePersonBtn'),
      latest: $('historyLatestBtn'),
      myNick: $('myNickInput'),
    };
    if (!this._els.list) return;
    this.model = HistoryModel.create({ pageSize: this.pageSize, preloadRows: this.preloadRows, maxRows: 400 });
    this._els.list.addEventListener('scroll', () => this._onScroll());
    if (this._els.search) {
      this._els.search.addEventListener('input', () => {
        this.query = this._els.search.value.trim();
        this._debounceSearch();
      });
    }
    if (this._els.global) {
      this._els.global.addEventListener('click', () => {
        this.scope = this.scope === 'person' ? 'global' : 'person';
        this._els.global.classList.toggle('active', this.scope === 'global');
        this._debounceSearch();
      });
    }
    if (this._els.images) {
      this._els.images.addEventListener('change', () => {
        this.showImages = !!this._els.images.checked;
        this.saveSettings();
        this.render();
      });
    }
    if (this._els.latest) this._els.latest.addEventListener('click', () => this.jumpToLatest());
    if (this._els.folder) this._els.folder.addEventListener('click', () => this.openFolder());
    if (this._els.clear) this._els.clear.addEventListener('click', () => this.clearHistory());
    if (this._els.removePerson) this._els.removePerson.addEventListener('click', () => this.deletePerson());
    this.initMyNick();
    this.renderEmpty('Click a nick in User Memory to read the whole conversation with that person.');
  },

  initMyNick() {
    const input = this._els.myNick;
    if (!input) return;
    const commit = () => {
      const value = input.value.trim();
      if (value === this.myNick) return;
      this.myNick = value;
      if (App.bridge && App.bridge.set_my_nick) App.bridge.set_my_nick(value);
      input.classList.add('saved');
      setTimeout(() => input.classList.remove('saved'), 900);
    };
    input.addEventListener('change', commit);
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { commit(); input.blur(); } });
    if (App.bridge && App.bridge.get_my_nick) App.bridge.get_my_nick((value) => this.setMyNick(value || ''));
  },

  setMyNick(value) {
    this.myNick = value || '';
    if (this._els.myNick && this._els.myNick.value !== this.myNick) this._els.myNick.value = this.myNick;
    if (this.model) this.model.myNick = this.myNick;
    if (this.nick) this.renderHeader();
    if (typeof CollectorPanel !== 'undefined') CollectorPanel.setMyNick(this.myNick);
  },

  applySettings(settings) {
    const preview = (settings && settings.preview) || {};
    if (preview.preload_rows) this.preloadRows = Number(preview.preload_rows);
    if (preview.page_size) this.pageSize = Number(preview.page_size);
    if (preview.show_images !== undefined) this.showImages = !!preview.show_images;
    if (this._els.images) this._els.images.checked = this.showImages;
    if (this.model) {
      this.model.preloadRows = this.preloadRows;
      this.model.pageSize = this.pageSize;
      this.model.showImages = this.showImages;
    }
  },

  saveSettings() {
    if (!App.bridge || !App.bridge.save_history_settings) return;
    App.bridge.save_history_settings(JSON.stringify({ preview: { preload_rows: this.preloadRows, page_size: this.pageSize, show_images: this.showImages } }));
  },
};

if (typeof window !== 'undefined') window.HistoryStoreCore = HistoryStoreCore;
