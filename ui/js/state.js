/* state.js — global UI state + top bar + control bar. */
(function () {
  "use strict";

  window.State = {
    running: false,
    paused: false,
    blocks: [],      // [{block_id, action_type, params, delay_after, enabled, position}]
    schemas: {},     // action_type -> {icon, label, params[]}
    users: [],
    counts: {},
    rules: []
  };

  function $(id) { return document.getElementById(id); }

  window.uuid = function () {
    return "b" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  };

  window.renderPill = function (stateText) {
    var pill = $("status-pill");
    pill.textContent = stateText || "Ready";
    pill.className = "pill";
    if (/Running/i.test(stateText)) pill.classList.add("running");
    else if (/Paused/i.test(stateText)) pill.classList.add("paused");
    else if (/Error|lost/i.test(stateText)) pill.classList.add("error");
  };

  window.renderCounts = function (counts) {
    State.counts = counts || {};
    $("counts").textContent =
      "Users: " + (State.counts.total || 0) +
      " • new " + (State.counts.new || 0) +
      " • queued " + (State.counts.queued || 0) +
      " • messaged " + (State.counts.messaged || 0);
  };

  window.setControls = function (running, paused) {
    State.running = running;
    State.paused = paused;
    $("btn-run").disabled = running;
    $("btn-pause").disabled = !running || paused;
    $("btn-resume").disabled = !running || !paused;
    $("btn-stop").disabled = !running;
  };

  window.updateStepCount = function () {
    $("step-count").textContent = "Steps: " + State.blocks.length;
  };

  // native menu -> UI commands
  window.uiCommand = function (cmd) {
    if (cmd === "openSettings") { if (window.openSettings) openSettings(); }
    if (cmd === "openSavePreset") { if (window.promptSavePreset) promptSavePreset(); }
  };

  document.addEventListener("DOMContentLoaded", function () {
    renderPill("Ready");
    setControls(false, false);

    $("btn-run").addEventListener("click", function () {
      callApi("runSequence", { blocks: serializeBlocks() })
        .catch(function (e) { window.logLine("err", "run failed: " + e.message); });
    });
    $("btn-pause").addEventListener("click", function () { callApi("pause"); });
    $("btn-resume").addEventListener("click", function () { callApi("resume"); });
    $("btn-stop").addEventListener("click", function () { callApi("stop"); });
    $("btn-settings").addEventListener("click", function () {
      if (window.openSettings) openSettings();
    });
  });
})();
