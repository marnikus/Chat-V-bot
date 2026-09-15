/* history-store.js — HistoryStore facade (H-B2b JS split, 458→~30)

Parts loaded before this one — see index.html:
  history-store-core.js, history-store-open.js, history-store-bridge.js,
  history-store-scroll.js, history-store-render.js

Public API unchanged: window.HistoryStore
*/

'use strict';

const HistoryStore = {};

UIHelpers.mergeParts(HistoryStore,
  HistoryStoreCore, HistoryStoreOpen, HistoryStoreBridge,
  HistoryStoreScroll, HistoryStoreRender);

if (typeof window !== 'undefined') window.HistoryStore = HistoryStore;
