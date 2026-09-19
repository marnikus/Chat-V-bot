/* Run the real shipped agent against the supplied eight synthetic DOM pages.
   GOLDEN_RECORD=1 prints replacement approvals; never update them merely to
   make a refactor pass. Review intended behavior changes first. */
'use strict';
const fs = require('fs');
const path = require('path');
const { buildChat } = require('./dom_stub.js');
const { PAGES } = require('./golden_dom/pages.js');
const SRC = fs.readFileSync(
  path.join(__dirname, '..', 'backend', 'js', 'chat_agent.js'), 'utf8');
const STATE_KEYS = ['ok', 'tab', 'partner', 'title', 'me', 'participants',
                    'count', 'panes', 'authors', 'in_authors', 'out_authors', 'head', 'tail'];
const ITEM_KEYS = ['fp', 'dir', 'from', 'kind', 'text', 'media', 'time', 'occ'];
function install(spec) {
  const env = buildChat(spec);
  new Function('window', 'document', 'MutationObserver', 'setTimeout',
               'clearTimeout', SRC)(env.window, env.document,
    env.MutationObserver, env.setTimeout, env.clearTimeout);
  return { env, agent: env.window.__cvbAgent };
}
const pick = (obj, keys) => keys.reduce((o, k) => { o[k] = obj[k]; return o; }, {});
function observe(name) {
  const page = PAGES[name];
  const { env, agent } = install(page.spec);
  if (page.arrange) page.arrange(env, agent);
  const state = agent.state();
  const slice = agent.slice(0, state.count);
  return { state: pick(state, STATE_KEYS),
           items: slice.items.map((it) => pick(it, ITEM_KEYS)) };
}
const actual = {};
Object.keys(PAGES).forEach((name) => { actual[name] = observe(name); });
if (process.env.GOLDEN_RECORD) {
  process.stdout.write('const APPROVED = ' + JSON.stringify(actual, null, 1) + ';\n');
  process.exit(0);
}
const APPROVED = require('./golden_dom/approvals.js');
let failed = 0;
Object.keys(PAGES).forEach((name) => {
  const want = JSON.stringify(APPROVED[name]);
  const got = JSON.stringify(actual[name]);
  if (want !== got) {
    failed += 1;
    console.error('GOLDEN MISMATCH ' + name + '\n  want: ' + want + '\n  got: ' + got);
  }
});
Object.keys(APPROVED).forEach((name) => {
  if (!PAGES[name]) { failed += 1; console.error('orphan approval: ' + name); }
});
console.log(failed ? failed + ' golden page(s) drifted'
                   : Object.keys(PAGES).length + ' golden pages approved');
process.exit(failed ? 1 : 0);
