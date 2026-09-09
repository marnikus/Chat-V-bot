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
    if (window.App) {
      window.App.bridge = bridge;
      window.App.ready = true;
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
