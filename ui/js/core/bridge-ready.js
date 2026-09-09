// bridge-ready.js — shared QWebChannel ready helper (ES module, no bundler)
// Usage: import { bridgeReady } from './core/bridge-ready.js'; bridgeReady(b => { ... });
let _bridge = null;
let _queue = [];
let _ready = false;

function _flush() {
  _ready = true;
  const q = _queue.slice();
  _queue = [];
  q.forEach(fn => { try { fn(_bridge); } catch (e) { console.error(e); } });
}

export function bridgeReady(cb) {
  if (_ready && _bridge) { cb(_bridge); return; }
  _queue.push(cb);
  if (_queue.length > 1) return;
  // Qt WebChannel is injected as qrc:///qtwebchannel/qwebchannel.js
  function tryInit() {
    if (typeof QWebChannel === 'undefined') { setTimeout(tryInit, 30); return; }
    // eslint-disable-next-line no-undef
    new QWebChannel(qt.webChannelTransport, channel => {
      _bridge = channel.objects.bridge || channel.objects.chatflow;
      if (!_bridge) { console.warn('bridge object not found'); return; }
      _flush();
    });
  }
  tryInit();
}

export function getBridge() { return _bridge; }
