/* DOM/protocol test host. No CVB probe is recognized or answered by hand.
 * Every Runtime.evaluate executes the supplied expression in jsdom. Normal
 * responses and exceptionDetails follow CDP's envelope; observer bindings are
 * delivered as events. No external scripts, images or network resources load.
 * Install this development-only dependency with: npm ci --prefix tests
 */
'use strict';
const { JSDOM, VirtualConsole } = require('jsdom');
const readline = require('readline');
let dom = null;
const bindings = new Set();
const startupScripts = [];
function emit(value) { process.stdout.write(JSON.stringify(value) + '\n'); }
function bind(name) {
  dom.window[name] = (payload) => emit({ method: 'Runtime.bindingCalled',
    params: { name, payload: String(payload), executionContextId: 1 } });
}
function load(html) {
  if (dom) dom.window.close();
  dom = new JSDOM(html, { url: 'https://chat.example.test/chat',
    runScripts: 'outside-only', virtualConsole: new VirtualConsole() });
  bindings.forEach(bind);
  startupScripts.forEach((script) => dom.window.eval(script));
}
async function handle(request) {
  const params = request.params || {};
  let reply;
  if (request.method === 'Test.load') {
    load(params.html);
    reply = { result: {} };
  } else if (request.method === 'Runtime.addBinding') {
    bindings.add(params.name);
    bind(params.name);
    reply = { result: {} };
  } else if (request.method === 'Page.addScriptToEvaluateOnNewDocument') {
    startupScripts.push(params.source);
    reply = { result: { identifier: String(startupScripts.length) } };
  } else if (request.method === 'Runtime.evaluate') {
    try {
      const value = await dom.window.eval(params.expression);
      const remote = { type: value === null ? 'object' : typeof value };
      if (value !== undefined) remote.value = value;
      if (value === null) remote.subtype = 'null';
      reply = { result: { result: remote } };
    } catch (error) {
      reply = { result: { result: { type: 'object', subtype: 'error' },
        exceptionDetails: { text: 'Uncaught', exception: {
          description: String(error), className: error.name,
        } } } };
    }
  } else if (request.method.endsWith('.enable')) {
    reply = { result: {} };
  } else {
    reply = { error: { code: -32601, message: 'Unsupported test host method: ' + request.method } };
  }
  emit({ id: request.id, ...reply });
}
let chain = Promise.resolve();
const input = readline.createInterface({ input: process.stdin });
input.on('line', (line) => {
  chain = chain.then(() => handle(JSON.parse(line))).catch((error) => {
    process.stderr.write(String(error) + '\n');
    process.exitCode = 1;
  });
});
input.on('close', () => chain.finally(() => { if (dom) dom.window.close(); }));
