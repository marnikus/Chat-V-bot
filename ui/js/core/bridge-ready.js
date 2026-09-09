/* BridgeReady — the ONE QWebChannel handshake + boot queue.

  Before: app.js owned the handshake and every panel wired its own
  `DOMContentLoaded` init; panels could boot before the bridge existed
  and had to null-check App.bridge everywhere.

  After: index.html loads this file first; it performs the single
  handshake and exposes

      BridgeReady.ready(fn)   // run fn(bridge) once the bridge exists
                              // (immediately if it already does; on
                              // plain DOM ready when running standalone
                              // in node tests)
      BridgeReady.bridge      // the live bridge object or null

  App.bridge / App.ready stay assigned for every existing consumer.
*/
'use strict';

window.BridgeReady = (function () {
  const queue = [];
  let bridge = null;
  let connected = false;

  function flush() {
    while (queue.length) {
      try {
        queue.shift()(bridge);
      } catch (e) {
        console.error('BridgeReady handler failed:', e);
      }
    }
  }

  function onChannel(channel) {
    bridge = channel.objects.bridge;
    connected = true;
    // `App` is declared as a top-level `const` in app.js — a classic
    // script's top-level const/let lives in the global LEXICAL scope,
    // NOT on window, so window.App is undefined in the real page. Resolve
    // the binding itself; fall back to window.App for environments that
    // publish it there (node harnesses). Without this the page boots in
    // "standalone mode" and every bridge call no-ops (looked like all
    // data was gone — 2026-09-09 incident).
    const app = (typeof App !== 'undefined') ? App : window.App;
    if (app) {
      app.bridge = bridge;
      app.ready = true;
    }
    console.log('QWebChannel connected');
    flush();
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (typeof QWebChannel !== 'undefined' &&
        typeof qt !== 'undefined' && qt.webChannelTransport) {
      new QWebChannel(qt.webChannelTransport, onChannel);
    } else {
      console.warn('QWebChannel not available — running in standalone mode');
      connected = true;       // nothing to wait for: boot on DOM ready
      flush();
    }
  });

  return {
    ready(fn) {
      if (connected) fn(bridge);
      else queue.push(fn);
    },
    get bridge() { return bridge; },
    get connected() { return connected; },
  };
})();
