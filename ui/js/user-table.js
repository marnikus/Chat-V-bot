/* user-table.js — UserTable facade (H-B2b JS split, 448→~30)

Parts loaded before this one — see index.html:
  user-table-core.js, user-table-render.js, user-table-actions.js

Public API unchanged: window.UserTable
*/

'use strict';

const UserTable = {};

UIHelpers.mergeParts(UserTable, UserTableCore, UserTableRender, UserTableActions);

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) }).ready(() => UserTable.init());

if (typeof window !== 'undefined') window.UserTable = UserTable;
