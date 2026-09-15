/* db-panel.js — DbPanel facade (H-B2b JS split, 354→~20)

Parts loaded before this one — see index.html:
  db-panel-core.js, db-panel-actions.js, db-panel-render.js

Public API unchanged: window.DbPanel
*/

'use strict';

const DbPanel = {};

UIHelpers.mergeParts(DbPanel, DbPanelCore, DbPanelActions, DbPanelRender);

if (typeof window !== 'undefined') window.DbPanel = DbPanel;
if (typeof module === 'object' && module.exports) module.exports = DbPanel;
