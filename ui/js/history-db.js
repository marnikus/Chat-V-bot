/* history-db.js — HistoryDb facade (H-B2b JS split, 448→~30)

Parts loaded before this one — see index.html:
  history-db-core.js, history-db-sort.js, history-db-render.js

Public API unchanged: window.HistoryDb
*/

'use strict';

const HistoryDb = {};

UIHelpers.mergeParts(HistoryDb, HistoryDbCore, HistoryDbSort, HistoryDbRender);

if (typeof window !== 'undefined') window.HistoryDb = HistoryDb;
