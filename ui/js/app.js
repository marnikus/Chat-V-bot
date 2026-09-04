/* app.js — bootstrap: wire panels + engine events. */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    document.addEventListener("cf-api-ready", function () {
      logLine("ok", "API connected");
      initPalette();
      // load the default sequence on first start
      callApi("getPresets").then(function (data) {
        var presets = (data && data.presets) || [];
        if (!presets.length) loadDefaultSequence();
      });
      wireEngineEvents();
    });
  });

  function loadDefaultSequence() {
    // 🏠 →  → 🎯 →  → ⌨ → 📷 → 📤 → 🚪 (docs §8.3 example)
    var d = function (type, params, delay) {
      return { block_id: uuid(), action_type: type, params: params || {},
               delay_after: delay == null ? 1.0 : delay, enabled: true, position: 0 };
    };
    loadBlocks([
      d("go_main_tab", { tab_title: "Гостиная" }, 1.0),
      d("scroll_parse", {}, 2.0),
      d("pick_target", { order: "top" }, 0.5),
      d("click_user", {}, 1.0),
      d("type_message", { source: "single" }, 0.8),
      d("attach_image", {}, 0.5),
      d("send_message", {}, 2.0),
      d("close_tab", {}, 1.0)
    ]);
  }

  function wireEngineEvents() {
    Bus.on("status", function (p) {
      var map = { IDLE: "Ready", CONNECTING: "Connecting…", RUNNING: "Running",
        PAUSED: "Paused", STOPPING: "Stopping…", ERROR: "Error", DEGRADED: "Connection lost" };
      var text = map[p.state] || p.state;
      renderPill(text);
      setControls(
        p.state === "RUNNING" || p.state === "STOPPING",
        p.state === "PAUSED");
    });
    Bus.on("users_found", function () {
      // debounce via tracker's own timer
      window.refreshTracker && (window.refreshTracker._t = window.refreshTracker._t);
      clearTimeout(wireEngineEvents._tt);
      wireEngineEvents._tt = setTimeout(refreshTracker, 300);
    });
    Bus.on("target_picked", function (p) {
      renderCounts(Object.assign({}, State.counts,
        { queued: (State.counts.queued || 1) - 1 > 0 ? (State.counts.queued || 1) - 1 : 0 }));
    });
    Bus.on("message_sent", function (p) {
      renderCounts(Object.assign({}, State.counts,
        { queued: Math.max(0, (State.counts.queued || 1) - 1),
          messaged: (State.counts.messaged || 0) + 1 }));
    });
    Bus.on("run_summary", function () { refreshTracker(); });
    Bus.on("connection_lost", function () {
      setControls(false, false);
    });
  }
})();
