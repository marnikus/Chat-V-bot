/* bridge.js — QWebChannel bootstrap + event bus (Python -> JS). */
(function () {
  "use strict";

  // minimal event bus
  window.Bus = {
    _subs: {},
    on: function (name, fn) { (this._subs[name] = this._subs[name] || []).push(fn); },
    dispatch: function (name, payload) {
      (this._subs[name] || []).forEach(function (fn) {
        try { fn(payload); } catch (e) { console.error("Bus", name, e); }
      });
    }
  };

  // Python -> JS sink: window.__call(fn, payloadJson)
  window.__call = function (fn, payloadJson) {
    var payload = null;
    try { payload = payloadJson ? JSON.parse(payloadJson) : null; } catch (e) { payload = null; }
    if (fn === "onEvent") {
      if (payload && payload.name) Bus.dispatch(payload.name, payload.payload || {});
    } else if (typeof window[fn] === "function") {
      window[fn](payload || {});
    }
  };

  var api = null;
  window.api = null;

  function connect(channel) {
    api = channel.objects.chatflow;
    window.api = api;
    document.dispatchEvent(new Event("cf-api-ready"));
  }

  if (window.qt && qt.webChannelTransport) {
    new QWebChannel(qt.webChannelTransport, connect);
  } else {
    // browser (no Qt): expose a stub so the UI can be developed standalone
    connect({ objects: { chatflow: null } });
  }

  // uniform JS -> Python call helper (slots accept a JSON string payload)
  window.callApi = function (method, payload) {
    return new Promise(function (resolve, reject) {
      if (!api || typeof api[method] !== "function") {
        reject(new Error("api." + method + " unavailable"));
        return;
      }
      try {
        api[method](JSON.stringify(payload == null ? {} : payload), function (result) {
          var out = result;
          if (typeof result === "string") {
            try { out = result ? JSON.parse(result) : null; } catch (e) { out = result; }
          }
          resolve(out);
        });
      } catch (e) { reject(e); }
    });
  };
})();
