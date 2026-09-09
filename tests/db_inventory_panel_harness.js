/* Real Bridge/SQLite payloads enter the shipped DB panel in its real HTML.
   The QWebChannel transport/native desktop are controlled, not the renderer. */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const dom = new JSDOM(fs.readFileSync(path.join(root, 'ui/index.html'), 'utf8'), {
  runScripts: 'outside-only', url: 'https://local.test/',
});
const w = dom.window;
const calls = [];
w.App = { bridge: {
  db_info: (id) => calls.push(['db_info', id]),
  db_create: (name) => calls.push(['db_create', name]),
  db_load: (file) => calls.push(['db_load', file]),
  db_delete: (file) => calls.push(['db_delete', file]),
  db_clean: () => calls.push(['db_clean']),
  db_reveal: (file, cb) => {
    calls.push(['db_reveal', file]);
    cb(JSON.stringify((input.reveal_results || {})[file] || {
      ok: false, error: 'No controlled native reveal response for this path.',
    }));
  },
} };
w.PresetsUI = { confirm: (_title, _body, _label, yes) => yes() };
w.eval(fs.readFileSync(path.join(root, 'ui/js/db-panel.js'), 'utf8'));
const panel = w.DbPanel;
panel.init();
let stale = panel._pending;
const snapshots = [];
for (const event of input.events) {
  if (event.type === 'info') panel.onInfo(panel._pending, JSON.stringify(event.payload));
  if (event.type === 'remember_request') stale = panel._pending;
  if (event.type === 'stale_info') panel.onInfo(stale, JSON.stringify(event.payload));
  if (event.type === 'change') panel.onChanged(JSON.stringify(event.payload));
  if (event.type === 'create') {
    w.document.getElementById('dbNewNameInput').value = event.name;
    panel.create();
  }
  if (event.type === 'click_name') {
    const row = Array.from(w.document.querySelectorAll('.db-row'))
      .find((el) => el.dataset.path === event.path);
    if (!row) throw new Error('Missing clickable inventory row: ' + event.path);
    row.querySelector('.db-row-name').click();
  }
  const rows = Array.from(w.document.querySelectorAll('.db-row')).map((row) => ({
    path: row.dataset.path,
    name: row.querySelector('.db-row-name').textContent,
    filename_tag: row.querySelector('.db-row-name').tagName,
    title: row.querySelector('.db-row-name').title,
    detail: (row.querySelector('.db-row-detail') || {}).textContent || '',
    active: row.classList.contains('active'),
    buttons: Array.from(row.querySelectorAll('.btn-small')).map((btn) => ({
      text: btn.textContent, disabled: btn.disabled,
    })),
  }));
  snapshots.push({ rows, active: panel.activePath, busy: panel.busy,
    status: w.document.getElementById('dbConnStatus').textContent,
    folder: w.document.getElementById('dbFolderHint').textContent,
    calls: calls.slice(),
  });
}
console.log(JSON.stringify(snapshots));
w.close();
